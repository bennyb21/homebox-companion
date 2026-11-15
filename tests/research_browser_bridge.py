"""Browser RPC -> real ASGI -> unchanged LiteLLM handler, offline HTTP only.

Only Homebox/auth boundaries are fixtures. No API result, provider, client factory,
parser or settings route is replaced. A fresh process blocks sockets before imports.
"""

# ruff: noqa: E402 -- isolation must precede application/SDK imports
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(sys.argv[1])
os.environ.clear()
os.environ.update(HOME=str(STATE), LITELLM_LOCAL_MODEL_COST_MAP="True", DO_NOT_TRACK="1")
os.chdir(STATE)
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
sys.dont_write_bytecode = True
OUTPUT = sys.stdout
sys.stdout = sys.stderr  # SDK banners cannot corrupt the line protocol.

import asyncio
import json
import socket
from copy import deepcopy
from types import SimpleNamespace
from typing import Never
from unittest.mock import AsyncMock, patch

attempts = []


def forbidden(*args: object, **kwargs: object) -> Never:
    attempts.append("blocked")
    raise AssertionError("Socket/DNS forbidden in offline browser bridge")


socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
# ty treats this module function as an exact function object, not a callable signature.
patch.object(socket, "getaddrinfo", forbidden).start()

import httpx
from pydantic import SecretStr
from test_research_citation_contract import cited_response

from homebox_companion.core import config
from homebox_companion.core import persistent_settings as ps
from server.app import create_app
from server.dependencies import get_verified_gateway, require_auth

TYPE = "00000000-0000-4000-8000-000000000010"
TEMPLATE = "00000000-0000-4000-8000-000000000020"
KEY = "KEY-CONFIDENTIALITY-CANARY"
RAW = "RAW-PROVIDER-CONFIDENTIALITY-CANARY"


async def main():
    ps.SETTINGS_FILE = STATE / "settings.yaml"
    config.settings = config.Settings(_env_file=None, disable_update_check=True)
    ps.save_settings(
        ps.PersistentSettings(
            research_enabled=True,
            research_profile_name="default",
            llm_profiles=[
                ps.ModelProfile(
                    name="default", model="gpt-6-luna", status=ps.ProfileStatus.PRIMARY, api_key=SecretStr(KEY)
                ),
                ps.ModelProfile(
                    name="Off research",
                    model="gpt-6.1-terra",
                    status=ps.ProfileStatus.OFF,
                    credential_source="profile",
                    credential_profile_name="default",
                ),
                ps.ModelProfile(
                    name="Unverified",
                    model="gpt-6-terra",
                    status=ps.ProfileStatus.OFF,
                    credential_source="profile",
                    credential_profile_name="default",
                ),
            ],
        )
    )
    app = create_app(config.settings)
    app.state.research_db_path = STATE / "research.sqlite3"
    item = {
        "id": "item-1",
        "name": "Synthetic saved item",
        "entityType": {"id": TYPE},
        "fields": [{"id": "field-1", "name": "Specifications", "type": "text", "textValue": ""}],
    }
    gateway = SimpleNamespace(
        access=SimpleNamespace(identity_scope="user1", group_id="g1"),
        list_groups=AsyncMock(return_value=[{"id": "g1"}]),
        get_current_user=AsyncMock(return_value={"id": "user1"}),
        get_item=AsyncMock(side_effect=lambda _: deepcopy(item)),
        get_capture_profile=AsyncMock(
            return_value={
                "entity_type": {"id": TYPE},
                "template": {"id": TEMPLATE, "fields": item["fields"]},
            }
        ),
        update_item=AsyncMock(side_effect=AssertionError("No automatic inventory mutation")),
    )
    app.dependency_overrides[get_verified_gateway] = lambda: gateway
    app.dependency_overrides[require_auth] = lambda: None
    scenario = "matched"
    wire = []
    api_calls = []

    def respond(request):
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if request.method == "GET":
            model = request.url.path.split("/")[-1]
            assert str(request.url) == f"https://api.openai.com/v1/models/{model}"
            wire.append({"method": "GET", "model": model, "endpoint": str(request.url)})
            return httpx.Response(200, json={"id": model, "object": "model"})
        body = json.loads(request.content)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.method == "POST"
        assert body["max_output_tokens"] == 2400 and body["max_tool_calls"] == 1
        assert body["tools"] == [{"type": "web_search", "search_context_size": "low"}]
        assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is False
        assert body["store"] is False and body["background"] is False and body["stream"] is False
        assert body["include"] == ["web_search_call.action.sources"]
        assert "identity_confirmed" not in body["input"]
        wire.append(
            {
                "method": "POST",
                "model": body["model"],
                "endpoint": str(request.url),
                "scenario": scenario,
                "max_output_tokens": 2400,
                "max_tool_calls": 1,
                "reasoning": body.get("reasoning"),
            }
        )
        data = cited_response(suffix=True, empty=scenario == "no_results")
        data["model"] = body["model"]
        if scenario == "incomplete":
            data.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"}, output=[])
        if scenario == "refused":
            data["output"][1]["content"] = [{"type": "refusal", "refusal": RAW}]
        if scenario == "malformed":
            data["output"][1]["content"][0].update(text=RAW, annotations=[])
        if scenario == "ambiguous":
            data = cited_response(empty=False)
            part = data["output"][1]["content"][0]
            candidate = json.loads(part["text"])["candidates"][0]
            part["text"] = json.dumps({"candidates": [candidate, candidate | {"manufacturer": "Other"}]})
        status = 400 if scenario == "unsupported" else 200
        if status == 400:
            data = {"error": {"message": RAW, "type": "invalid_request_error"}}
        return httpx.Response(status, json=data, headers={"x-request-id": "req_0123456789abcdef"})

    transport = httpx.MockTransport(respond)

    async def intercepted(self, request):
        return await transport.handle_async_request(request)

    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", intercepted):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            try:
                while line := await asyncio.to_thread(sys.stdin.readline):
                    command = json.loads(line)
                    if "scenario" in command:
                        scenario = command["scenario"]
                        result = {"ok": True}
                    elif command.get("inspect"):
                        result = {
                            "wire": wire,
                            "network_attempts": len(attempts),
                            "api_calls": api_calls,
                            "inventory_writes": gateway.update_item.await_count,
                        }
                    else:
                        path = command["path"]
                        body = command.get("body")
                        if isinstance(body, dict) and "identity" in body:
                            assert "identity_confirmed" not in body["identity"]
                        api_calls.append({"method": command["method"], "path": path, "body": body})
                        response = await client.request(
                            command["method"], path, json=body, headers={"X-Companion-Request": "1"}
                        )
                        assert KEY not in response.text and RAW not in response.text
                        result = {
                            "status": response.status_code,
                            "contentType": "application/json",
                            "body": response.text,
                        }
                    OUTPUT.write(json.dumps(result) + "\n")
                    OUTPUT.flush()
            finally:
                if hasattr(app.state, "research_jobs"):
                    await app.state.research_jobs.close()
    assert attempts == []


if __name__ == "__main__":
    asyncio.run(main())
