"""Real ASGI research review; only Homebox/provider boundaries are synthetic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from homebox_companion.core.config import Settings
from homebox_companion.research import Claim, ResearchResult, Source
from server.app import create_app
from server.dependencies import get_verified_gateway

TYPE = "00000000-0000-4000-8000-000000000010"
TEMPLATE = "00000000-0000-4000-8000-000000000020"
BODY = {
    "draft_id": "draft-1",
    "revision": "rev-1",
    "entity_type_id": TYPE,
    "template_id": TEMPLATE,
    "identity": {"identifier_kind": "part_number", "identifier_exact": "AB-123", "identity_confirmed": True},
    "current_values": {"Specifications": "", "Condition": "keep"},
}


@pytest.fixture
def harness():
    app = create_app(Settings(disable_update_check=True))
    gateway = SimpleNamespace(
        access=SimpleNamespace(identity_scope="user1", group_id="group1"),
        list_groups=AsyncMock(return_value=[{"id": "group1"}]),
        get_capture_profile=AsyncMock(
            return_value={
                "entity_type": {"id": TYPE},
                "template": {"id": TEMPLATE, "fields": [{"id": "field-1", "name": "Specifications", "type": "text"}]},
            }
        ),
    )
    app.dependency_overrides[get_verified_gateway] = lambda: gateway
    app.state.research_provider = SimpleNamespace(
        configured=True,
        research=AsyncMock(
            return_value=ResearchResult(
                status="matched",
                sources=[Source(url="https://example.com/spec", title="Synthetic")],
                claims=[Claim(field="specifications", value="Steel", source_urls=["https://example.com/spec"])],
            )
        ),
    )
    return app, gateway


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "nontext", "duplicate", "foreign"])
async def test_rejected_lookup_never_calls_provider(harness, mode):
    app, gateway = harness
    expected = 400
    if mode == "disabled":
        app.state.research_provider.configured = False
        expected = 503
    if mode == "nontext":
        gateway.get_capture_profile.return_value["template"]["fields"][0]["type"] = "number"
    if mode == "duplicate":
        gateway.get_capture_profile.return_value["template"]["fields"] *= 2
    if mode == "foreign":
        gateway.access.group_id = "not-member"
        expected = 404
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        result = await client.post("/api/research/lookups", json=BODY)
    assert result.status_code == expected
    app.state.research_provider.research.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_explicit_adoption_and_fresh_template(harness):
    app, gateway = harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        lookup = await client.post("/api/research/lookups", json=BODY)
        assert lookup.status_code == 200, lookup.text
        data = lookup.json()
        assert data["proposals"][0]["current"] == ""
        assert data["proposals"][0]["name"] == "Specifications"
        assert "Condition" not in str(data["proposals"])
        assert app.state.research_provider.research.call_args.args[0].manufacturer is None
        apply_body = {
            "selected": [0],
            "current_values": BODY["current_values"],
            "draft_id": "draft-1",
            "revision": "rev-1",
        }
        adopted = await client.post(f"/api/research/lookups/{data['id']}/apply", json=apply_body)
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()["patch"] == {"Specifications": "Steel"}
        gateway.get_capture_profile.return_value["template"]["fields"][0]["type"] = "number"
        stale = await client.post(f"/api/research/lookups/{data['id']}/apply", json=apply_body)
        assert stale.status_code == 409


@pytest.mark.asyncio
async def test_scope_and_user_edits_are_protected(harness):
    app, gateway = harness
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/research/lookups", json=BODY)
        assert response.status_code == 200, response.text
        url = f"/api/research/lookups/{response.json()['id']}/apply"
        body = {
            "selected": [0],
            "current_values": {"Specifications": "new manual", "Condition": "keep"},
            "draft_id": "draft-1",
            "revision": "rev-1",
        }
        assert (await client.post(url, json=body)).status_code == 409
        gateway.access.identity_scope = "user2"
        assert (await client.post(url, json=body)).status_code == 404
        gateway.access.group_id = "foreign"
        assert (await client.post("/api/research/lookups", json=BODY)).status_code == 404
