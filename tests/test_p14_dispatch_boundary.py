"""Real Homebox transport -> gateway -> ASGI -> production checkpoint workflow."""

import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from test_research_api import TYPE
from test_research_api import harness as harness

from homebox_companion.homebox.auth import HomeboxAccess, HomeboxAuthKind
from homebox_companion.homebox.client import HomeboxClient, HomeboxGateway
from server.dependencies import get_gateway

TEMPLATE = "00000000-0000-4000-8000-000000000020"


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["explicit", "template", "default"])
async def test_preflight_timeout_retry_and_checkpoint(harness, profile):
    await exercise(harness, profile, "get_timeout", "rejected")


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["explicit", "template"])
@pytest.mark.parametrize(
    "failure,expected",
    [
        ("get_network", "rejected"),
        ("get_503", "rejected"),
        ("get_invalid", "rejected"),
        ("post_timeout", "unknown_write"),
        ("post_network", "unknown_write"),
        ("post_write_timeout", "unknown_write"),
        ("post_503", "unknown_write"),
        ("post_invalid", "unknown_write"),
        ("post_no_id", "unknown_write"),
        ("post_422", "rejected"),
        ("post_403", "rejected"),
        ("post_429", "rejected"),
    ],
)
async def test_real_dispatch_certainty(harness, profile, failure, expected):
    await exercise(harness, profile, failure, expected)


async def exercise(harness, profile, failure, expected):
    app, _ = harness
    requests = []
    attempts = 0
    post_attempts = 0

    def transport(request):
        nonlocal attempts, post_attempts
        path = request.url.path
        requests.append((request.method, path))
        if path == "/tags":
            return httpx.Response(200, json=[])
        if request.method == "GET":
            target = f"/templates/{TEMPLATE}" if profile == "template" else "/entity-types"
            if path == target:
                attempts += 1
                if attempts < 3:
                    if failure == "get_timeout":
                        raise httpx.ReadTimeout("synthetic failure", request=request)
                    if failure == "get_network":
                        raise httpx.ReadError("synthetic failure", request=request)
                    if failure == "get_503":
                        return httpx.Response(503, json={"error": "synthetic failure"})
                    if failure == "get_invalid":
                        return httpx.Response(200, content=b"invalid JSON")
            if path == "/entity-types":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": TYPE,
                            "name": "Item",
                            "isLocation": False,
                            "defaultTemplateId": TEMPLATE if profile == "template" else None,
                        }
                    ],
                )
            if path == "/templates":
                return httpx.Response(200, json=[{"id": TEMPLATE}])
            if path == f"/templates/{TEMPLATE}":
                return httpx.Response(200, json={"id": TEMPLATE, "fields": []})
            if path == "/entities":
                return httpx.Response(200, json={"items": [], "total": 0})
        if path == "/actions/ensure-asset-ids":
            return httpx.Response(200, json={"completed": 0})
        if request.method == "POST":
            post_attempts += 1
            if post_attempts < 3:
                if failure == "post_timeout":
                    # Simulate acceptance followed by loss of the response.
                    raise httpx.ReadTimeout("synthetic failure", request=request)
                if failure == "post_network":
                    raise httpx.ReadError("synthetic failure", request=request)
                if failure == "post_write_timeout":
                    raise httpx.WriteTimeout("synthetic failure", request=request)
                if failure in {"post_503", "post_422", "post_403", "post_429"}:
                    return httpx.Response(int(failure.removeprefix("post_")), json={"error": "synthetic failure"})
                if failure == "post_invalid":
                    return httpx.Response(200, content=b"invalid JSON")
                if failure == "post_no_id":
                    return httpx.Response(200, json={"name": "Native"})
            assert path == (f"/templates/{TEMPLATE}/create-item" if profile == "template" else "/entities")
            return httpx.Response(200, json={"id": "synthetic-created", "name": "Native"})
        raise AssertionError(f"Unexpected request {request.method} {path}")

    async with HomeboxClient(base_url="http://synthetic", transport=httpx.MockTransport(transport)) as upstream:
        gateway = HomeboxGateway(upstream, HomeboxAccess(SecretStr("synthetic"), HomeboxAuthKind.LEGACY, "test"))
        app.dependency_overrides[get_gateway] = lambda: gateway
        root = Path(__file__).resolve().parents[1]
        node = shutil.which("node")
        assert node
        process = await asyncio.create_subprocess_exec(
            node,
            str(root / "frontend/tests/p14-dispatch-probe.js"),
            expected,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin and process.stdout and process.stderr
        responses = []
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as api:
                async with asyncio.timeout(20):
                    while line := await process.stdout.readline():
                        assert json.loads(line) == {"create": True}
                        item = {"name": "Native", "quantity": 1}
                        if profile != "default":
                            item["entity_type_id"] = TYPE
                        response = await api.post("/api/items", json={"items": [item]})
                        responses.append(response.json())
                        if failure.startswith("get_") and len(responses) < 3:
                            assert post_attempts == 0
                            assert response.json()["outcomes"] == [{"index": 0, "status": "rejected"}]
                        process.stdin.write((response.text + "\n").encode())
                        await process.stdin.drain()
                    await process.wait()
            assert process.returncode == 0, (await process.stderr.read()).decode()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        expected_post = f"/templates/{TEMPLATE}/create-item" if profile == "template" else "/entities"
        assert [path for method, path in requests if method == "POST" and path != "/actions/ensure-asset-ids"] == [
            expected_post
        ] * post_attempts
        assert responses[0]["outcomes"] == [{"index": 0, "status": expected}]
        if expected == "rejected":
            assert len(responses) == 3
            assert post_attempts == (1 if failure.startswith("get_") else 3)
            assert responses[-1]["created"][0]["id"] == "synthetic-created"
            assert attempts == 3
        else:
            assert len(responses) == 1
            assert post_attempts == 1
            assert responses[0]["created"] == []
