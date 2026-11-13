"""RED contract for explicit capture profiles and lossless field enrichment.

P03 checkpoint: these assertions intentionally expose missing behavior, not
an implementation. All identifiers and item data are synthetic. The ASGI tests
exercise the real Companion route with only its Homebox boundary mocked; they
are not a live Homebox or vision-model acceptance test.
"""

from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from homebox_companion import HomeboxClient
from homebox_companion.core.config import Settings
from server.api import items as items_api
from server.app import create_app
from server.dependencies import get_gateway
from server.schemas.items import ItemInput

pytestmark = pytest.mark.unit

TYPE_ID = "00000000-0000-4000-8000-000000000010"
TEMPLATE_ID = "00000000-0000-4000-8000-000000000020"
PART_NUMBER = "0007-SYN-A"
EXISTING_FIELDS = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "name": "Part number",
        "type": "text",
        "textValue": "",
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "name": "Condition",
        "type": "text",
        "textValue": "unknown",
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "name": "Operator note",
        "type": "text",
        "textValue": "Keep this",
    },
]


@pytest.mark.parametrize("field,expected", [("entity_type_id", TYPE_ID), ("template_id", TEMPLATE_ID)])
def test_explicit_profile_references_survive_request_validation(field, expected):
    request = ItemInput.model_validate(
        {"name": "Synthetic part", "entity_type_id": TYPE_ID, "template_id": TEMPLATE_ID}
    )
    assert request.model_dump().get(field) == expected, f"Explicit {field} must not be silently discarded"


@pytest.fixture
def gateway(monkeypatch):
    gateway = AsyncMock(spec=HomeboxClient)
    current = {
        "id": "00000000-0000-4000-8000-000000000030",
        "name": "Synthetic part",
        "parent": {"id": "synthetic-location"},
        "tags": [],
        "quantity": 1,
        "fields": deepcopy(EXISTING_FIELDS),
    }
    gateway.create_item.return_value = deepcopy(current)
    gateway.get_item.return_value = deepcopy(current)
    # Reflect the actual submitted update instead of returning desired fields.
    gateway.update_item.side_effect = lambda item_id, payload: {**deepcopy(current), **deepcopy(payload)}
    gateway.ensure_asset_ids.return_value = 0
    monkeypatch.setattr(items_api, "get_valid_tag_ids", AsyncMock(return_value=set()))
    return gateway


async def submit(gateway, *, custom_fields=None):
    app = create_app(Settings(disable_update_check=True))
    app.dependency_overrides[get_gateway] = lambda: gateway
    item = {"name": "Synthetic part", "manufacturer": "Synthetic manufacturer"}
    if custom_fields is not None:
        item["custom_fields"] = custom_fields
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/items", json={"items": [item], "location_id": "synthetic-location"})
    assert response.status_code == 200, response.text
    gateway.create_item.assert_awaited_once()
    gateway.get_item.assert_awaited_once()
    gateway.update_item.assert_awaited_once()
    gateway.delete_item.assert_not_awaited()
    assert response.json()["errors"] == []
    return response.json()["created"][0]


@pytest.mark.asyncio
async def test_explicit_manual_empty_value_clears_default_without_losing_siblings(gateway):
    item = await submit(gateway, custom_fields={"Condition": ""})
    fields = {field["name"]: field for field in item["fields"]}
    assert fields["Condition"]["textValue"] == ""
    assert fields["Operator note"]["textValue"] == "Keep this"


@pytest.mark.asyncio
async def test_control_scalar_enrichment_preserves_existing_fields(gateway):
    item = await submit(gateway)
    assert item["fields"] == EXISTING_FIELDS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_field", EXISTING_FIELDS, ids=["part-number-id", "template-default", "extra-user-field"]
)
async def test_custom_enrichment_preserves_existing_field_structure(gateway, expected_field):
    item = await submit(gateway, custom_fields={"Part number": PART_NUMBER})
    fields = {field["name"]: field for field in item["fields"]}
    # Existing number extraction already works; identity and sibling preservation do not.
    assert fields["Part number"]["textValue"] == PART_NUMBER
    expected = deepcopy(expected_field)
    if expected["name"] == "Part number":
        expected["textValue"] = PART_NUMBER
    actual = fields.get(expected["name"])
    assert actual is not None, f"Existing field {expected['name']} must survive enrichment"
    assert {key: actual.get(key) for key in expected} == expected
