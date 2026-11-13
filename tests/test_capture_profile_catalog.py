"""Native profile reads: real ASGI/gateway, synthetic HTTP boundary only."""

import httpx
import pytest

from homebox_companion import HomeboxClient, HomeboxGateway
from homebox_companion.core.config import Settings
from homebox_companion.core.exceptions import CaptureProfileError
from homebox_companion.homebox.auth import LegacySessionProvider
from server.app import create_app
from server.dependencies import get_gateway

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]
TYPE = "00000000-0000-4000-8000-000000000010"
TEMPLATE = "00000000-0000-4000-8000-000000000020"
LOCATION = "00000000-0000-4000-8000-000000000030"


async def test_catalog_uses_native_default_and_preserves_typed_schema():
    calls = []

    def upstream(request):
        calls.append(request.url.path)
        data = {
            "/entity-types": [
                {"id": TYPE, "name": "Part", "isLocation": False, "defaultTemplateId": TEMPLATE},
                {"id": LOCATION, "name": "Shelf", "isLocation": True},
            ],
            "/templates": [{"id": TEMPLATE, "name": "Parts"}],
            f"/templates/{TEMPLATE}": {
                "id": TEMPLATE,
                "name": "Parts",
                "defaultQuantity": 0,
                "fields": [{"name": "Checked", "type": "boolean", "booleanValue": False}],
            },
        }
        return httpx.Response(200, json=data[request.url.path])

    async with HomeboxClient(base_url="http://native", transport=httpx.MockTransport(upstream)) as native:
        gateway = HomeboxGateway(native, LegacySessionProvider().resolve("Bearer synthetic", "collection-a"))
        app = create_app(Settings(disable_update_check=True))
        app.dependency_overrides[get_gateway] = lambda: gateway
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/api/capture-profiles")
            assert response.status_code == 200
            assert [x["id"] for x in response.json()] == [TYPE]
            response = await client.get(f"/api/capture-profiles/{TYPE}")
            assert response.status_code == 200
            profile = response.json()
            assert profile["template"]["id"] == TEMPLATE
            assert profile["template"]["defaultQuantity"] == 0
            assert profile["template"]["fields"][0]["booleanValue"] is False
            assert f"/templates/{TEMPLATE}" in calls


@pytest.mark.parametrize("selection", [LOCATION, "00000000-0000-4000-8000-000000000099", "not-a-uuid"])
async def test_invalid_type_is_rejected(selection):
    def upstream(request):
        return httpx.Response(200, json=[{"id": LOCATION, "name": "Shelf", "isLocation": True}])

    async with HomeboxClient(base_url="http://native", transport=httpx.MockTransport(upstream)) as native:
        app = create_app(Settings(disable_update_check=True))
        app.dependency_overrides[get_gateway] = lambda: HomeboxGateway(
            native, LegacySessionProvider().resolve("Bearer synthetic")
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.get(f"/api/capture-profiles/{selection}")
            assert response.status_code == (422 if selection == "not-a-uuid" else 400)


async def test_selection_revalidates_user_collection_and_changed_defaults():
    observed = []
    current_template = TEMPLATE

    def upstream(request):
        observed.append((request.headers["Authorization"], request.headers.get("X-Tenant")))
        if request.url.path == "/entity-types":
            if request.headers["Authorization"] != "Bearer alice" or request.headers.get("X-Tenant") != "a":
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "id": TYPE,
                        "name": "Part",
                        "isLocation": False,
                        "defaultTemplateId": current_template,
                    }
                ],
            )
        if request.url.path == "/templates":
            return httpx.Response(200, json=[{"id": TEMPLATE, "name": "Parts"}])
        return httpx.Response(200, json={"id": TEMPLATE, "fields": []})

    async with HomeboxClient(base_url="http://native", transport=httpx.MockTransport(upstream)) as native:
        alice = native.for_group("a", cache_scope="alice")
        assert hasattr(alice, "get_capture_profile"), "Native profile resolver is missing"
        assert (await alice.get_capture_profile("alice", TYPE))["template"]["id"] == TEMPLATE
        for token, group in [("bob", "a"), ("alice", "b")]:
            with pytest.raises(CaptureProfileError, match="item type"):
                await native.for_group(group, cache_scope=token).get_capture_profile(token, TYPE)
        current_template = None
        assert (await alice.get_capture_profile("alice", TYPE))["template"] is None
        with pytest.raises(CaptureProfileError, match="template"):
            await alice.get_capture_profile("alice", TYPE, TEMPLATE)
        assert ("Bearer bob", "a") in observed
        assert ("Bearer alice", "b") in observed


async def test_missing_template_is_not_silently_replaced():
    def upstream(request):
        if request.url.path == "/entity-types":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": TYPE,
                        "isLocation": False,
                        "defaultTemplateId": TEMPLATE,
                    }
                ],
            )
        return httpx.Response(200, json=[])

    async with HomeboxClient(base_url="http://native", transport=httpx.MockTransport(upstream)) as native:
        assert hasattr(native, "get_capture_profile"), "Native profile resolver is missing"
        with pytest.raises(CaptureProfileError, match="template"):
            await native.get_capture_profile("synthetic", TYPE)
