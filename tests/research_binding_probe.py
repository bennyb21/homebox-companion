"""Fresh-process real client/cache binding with synthetic HTTP; all sockets blocked."""

# ruff: noqa: E402 -- environment isolation must precede SDK/application imports

import os
import sys
from pathlib import Path

# Isolate before importing application/SDK; never consult production defaults.
os.environ.clear()
os.environ.update(HOME=str(Path(sys.argv[1]).parent), LITELLM_LOCAL_MODEL_COST_MAP="True", DO_NOT_TRACK="1")
sys.dont_write_bytecode = True

import asyncio
import json
import socket
from unittest.mock import patch

network_attempts = []


def forbidden(*args, **kwargs):
    network_attempts.append("blocked_socket_or_dns")
    raise AssertionError("No socket or DNS allowed in synthetic acceptance")


socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.getaddrinfo = forbidden

import httpx
import httpx2
from pydantic import SecretStr

from homebox_companion.ai.llm import vision_completion
from homebox_companion.core import config, llm_router
from homebox_companion.core import persistent_settings as ps
from homebox_companion.research import OpenAIResponsesResearchProvider, ProductIdentity, ResearchPolicy


async def main():
    ps.SETTINGS_FILE = Path(sys.argv[1])
    config.settings = config.Settings(_env_file=None)
    ps.save_settings(
        ps.PersistentSettings(
            llm_profiles=[
                ps.ModelProfile(
                    name="capture",
                    model="gpt-6-luna",
                    status=ps.ProfileStatus.PRIMARY,
                    api_key=SecretStr("SYNTHETIC-A"),
                )
            ]
        )
    )
    llm_router.invalidate_router()
    prior_calls = []

    async def intercepted(client, request, **kwargs):
        body = json.loads(request.content)
        prior_calls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer SYNTHETIC-A"
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        cls = httpx2.Response if isinstance(request, httpx2.Request) else httpx.Response
        return cls(
            200,
            request=request,
            json={
                "id": "chatcmpl_synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    if sys.argv[2] == "vision_first":
        # Do NOT replace the SDK factory/cache. Only final HTTP send in both SDK transports.
        with (
            patch.object(httpx.AsyncClient, "send", intercepted),
            patch.object(httpx2.AsyncClient, "send", intercepted),
        ):
            await vision_completion("Identify", "item", ["data:image/png;base64,c3ludGhldGlj"])
        assert len(prior_calls) == 1
    else:
        assert prior_calls == []
    # Conflicting ambient SDK settings must not affect the explicit adapter.
    os.environ["OPENAI_BASE_URL"] = "https://ambient.invalid/v1"
    os.environ["OPENAI_API_BASE"] = "https://ambient.invalid/v1"
    os.environ["OPENAI_API_KEY"] = "SYNTHETIC-AMBIENT"
    cases = []
    for model, key, base in [
        ("gpt-6-luna", "SYNTHETIC-A", None),
        ("gpt-6-luna", "SYNTHETIC-A", "https://api.openai.com/v1"),
        ("gpt-6.1-terra", "SYNTHETIC-A", None),
        ("gpt-6.1-terra", "SYNTHETIC-B", "https://api.openai.com/v1"),
    ]:
        for repetition in range(2):
            calls = []

            def respond(request, calls=calls, model=model, key=key):
                calls.append(request)
                body = json.loads(request.content)
                assert str(request.url) == "https://api.openai.com/v1/responses"
                assert request.method == "POST" and body["model"] == model
                assert request.headers["authorization"] == f"Bearer {key}"
                assert body["max_output_tokens"] == 2400 and body["max_tool_calls"] == 1
                assert body["tools"] == [{"type": "web_search", "search_context_size": "low"}]
                assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is False
                assert body["background"] is False and body["store"] is False
                assert "reasoning" not in body and "identity_confirmed" not in body["input"]
                return httpx.Response(
                    200,
                    headers={"x-request-id": "req_0123456789abcdef"},
                    json={
                        "id": "resp_synthetic",
                        "object": "response",
                        "created_at": 1,
                        "model": model,
                        "status": "completed",
                        "output": [
                            {
                                "type": "web_search_call",
                                "id": "ws_synthetic",
                                "status": "completed",
                                "action": {"type": "search"},
                            },
                            {
                                "type": "message",
                                "id": "msg_synthetic",
                                "role": "assistant",
                                "status": "completed",
                                "content": [{"type": "output_text", "text": '{"candidates":[]}', "annotations": []}],
                            },
                        ],
                    },
                )

            provider = OpenAIResponsesResearchProvider(
                ResearchPolicy(enabled=True, profile_name="research"),
                ps.ModelProfile(name="research", model=model, api_key=SecretStr(key), api_base=base),
                transport=httpx.MockTransport(respond),
            )
            result = await provider.research(
                ProductIdentity(identifier_kind="model_number", identifier_exact="PUBLIC-A")
            )
            assert result.status == "no_results", result.model_dump()
            assert result.diagnostic is not None and result.diagnostic.dispatch_started
            assert result.diagnostic.http_status == 200 and result.diagnostic.request_id == "req_0123456789abcdef"
            assert len(calls) == 1
            cases.append(
                {"model": model, "explicit_base": base is not None, "repetition": repetition, "posts": len(calls)}
            )
    assert network_attempts == []
    print(
        json.dumps(
            {
                "mode": sys.argv[2],
                "vision_posts": len(prior_calls),
                "cases": cases,
                "network": "blocked",
                "network_attempts": len(network_attempts),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
