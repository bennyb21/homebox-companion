"""Sourced coarse assignment is explicit, native TEXT-only and scope-bound."""

import json

import httpx
import pytest
from test_research_api import BODY
from test_research_api import harness as harness
from test_research_evidence import response

from homebox_companion.research import ProductIdentity, parse_response


def family_response(value="Example Series W123 vehicle family"):
    data = response()
    part = data["output"][2]["content"][0]
    payload = json.loads(part["text"])
    payload["candidates"][0]["identifier_exact"] = BODY["identity"]["identifier_exact"]
    claim = payload["candidates"][0]["claims"][0]
    claim.update(field="vehicle_family", value=value)
    part["text"] = text = json.dumps(payload)
    # Separate targeted identity and claim spans, not the entire JSON document.
    base = part["annotations"][0]
    start = text.index('"manufacturer"')
    end = text.index(', "identifier_kind"')
    claim_start = text.index(value)
    part["annotations"] = [
        base | {"start_index": start, "end_index": end},
        base | {"start_index": claim_start, "end_index": claim_start + len(value)},
    ]
    return data


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["Example Series W123 vehicle family", "Fits Example Series W123 vehicle family"])
async def test_family_research_maps_and_requires_explicit_scoped_adoption(harness, value):
    app, gateway = harness
    result = parse_response(family_response(value), ProductIdentity.model_validate(BODY["identity"]))
    assert result.status == "matched"
    app.state.research_provider.research.return_value = result
    gateway.get_capture_profile.return_value["template"]["fields"] = [
        {"id": "vehicle", "name": "Fahrzeugzuordnung", "type": "text"}
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        lookup = await client.post("/api/research/lookups", json=BODY)
        assert lookup.status_code == 200
        review = lookup.json()
        assert review["proposals"][0]["name"] == "Fahrzeugzuordnung"
        adoption = {k: BODY[k] for k in ("draft_id", "revision", "current_values")}
        url = f"/api/research/lookups/{review['id']}/apply"
        assert (await client.post(url, json=adoption | {"selected": []})).json()["patch"] == {}
        assert (await client.post(url, json=adoption | {"selected": [0]})).json()["patch"] == {
            "Fahrzeugzuordnung": value
        }
        gateway.access.identity_scope = "other"
        assert (await client.post(url, json=adoption | {"selected": [0]})).status_code == 404


@pytest.mark.parametrize("value", ["Guaranteed fits W123", "VIN W123", "Serial 123", "Montagefreigabe W123"])
def test_family_does_not_authorize_specific_or_guaranteed_fitment(value):
    assert parse_response(family_response(value), ProductIdentity.model_validate(BODY["identity"])).status == "failed"


def test_family_requires_claim_source_binding():
    data = family_response()
    data["output"][2]["content"][0]["annotations"].pop()
    assert parse_response(data, ProductIdentity.model_validate(BODY["identity"])).status == "failed"
