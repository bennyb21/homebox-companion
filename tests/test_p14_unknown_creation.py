"""Actual backend response must block production client replay after lost writes."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from test_research_api import TYPE
from test_research_api import harness as harness

from homebox_companion.core.exceptions import CaptureProfileError, HomeboxAPIError
from server.dependencies import get_gateway


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("accepted POST response lost"),
        httpx.ReadError("connection lost"),
        ValueError("invalid success JSON"),
    ],
)
async def test_accepted_post_read_timeout_cannot_be_recreated_by_client(harness, failure):
    app, gateway = harness
    gateway.list_tags = AsyncMock(return_value=[])
    gateway.create_item = AsyncMock(side_effect=failure)
    app.dependency_overrides[get_gateway] = lambda: gateway
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/items", json={"items": [{"name": "Native", "quantity": 1, "entity_type_id": TYPE}]}
        )
    assert response.status_code == 207
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node, "Node required for backend-to-production-client regression"
    run = subprocess.run(
        [node, str(root / "frontend/tests/p14-submission-probe.js")],
        input=json.dumps(response.json()),
        text=True,
        capture_output=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert response.json()["outcomes"] == [{"index": 0, "status": "unknown_write"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,expected",
    [
        (HomeboxAPIError("rejected", context={"status_code": 422}), "rejected"),
        (HomeboxAPIError("remote failure", context={"status_code": 503}), "unknown_write"),
        (CaptureProfileError("stale template"), "rejected"),
        (httpx.ConnectError("no connection established"), "rejected"),
    ],
)
async def test_creation_certainty_distinguishes_rejection_from_unknown(harness, failure, expected):
    app, gateway = harness
    gateway.list_tags = AsyncMock(return_value=[])
    gateway.create_item = AsyncMock(side_effect=failure)
    app.dependency_overrides[get_gateway] = lambda: gateway
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/items", json={"items": [{"name": "Native", "quantity": 1, "entity_type_id": TYPE}]}
        )
    assert response.json()["outcomes"] == [{"index": 0, "status": expected}]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"id": 12}, [], None])
async def test_invalid_success_payload_is_unknown(harness, payload):
    app, gateway = harness
    gateway.list_tags = AsyncMock(return_value=[])
    gateway.create_item = AsyncMock(return_value=payload)
    app.dependency_overrides[get_gateway] = lambda: gateway
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/items", json={"items": [{"name": "Native", "quantity": 1}]})
    assert response.json()["outcomes"] == [{"index": 0, "status": "unknown_write"}]
