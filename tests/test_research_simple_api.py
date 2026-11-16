"""Actual API with captured public provider output; no inventory mutations."""

import base64
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from test_research_api import BODY
from test_research_api import harness as harness

from homebox_companion.research import Claim, ResearchResult, parse_response


@pytest.mark.asyncio
async def test_whole_item_context_manual_edit_selection_discard(harness):
    app, gateway = harness
    gateway.update_item = AsyncMock()
    actual = json.loads((Path(__file__).parent / "fixtures/research/public-whole-item.json").read_text())
    app.state.research_provider.research.return_value = parse_response(actual)
    photo = io.BytesIO()
    Image.new("RGB", (12, 12), "blue").save(photo, format="PNG")
    context = {
        "title": "Spacer",
        "model_number": "0112-S90-6-10-032-N-B",
        "images": ["data:image/png;base64," + base64.b64encode(photo.getvalue()).decode()],
        "technical_fields": {"Material": "Aluminum", "Account": "private"},
    }
    body = {k: v for k, v in BODY.items() if k != "identity"} | {"context": context}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        await client.get("/api/research/capabilities")
        app.state.research_provider.research.assert_not_awaited()
        response = await client.post("/api/research/lookups", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        sent = app.state.research_provider.research.call_args.args[0]
        assert sent.model_number == context["model_number"] and len(sent.images) == 1
        assert sent.technical_fields == {"Material": "Aluminum"}
        assert result["result"]["ambiguity"]
        assert any(p.get("target") == "name" for p in result["proposals"])
        index = next(i for i, p in enumerate(result["proposals"]) if p["name"] == "Specifications")
        adopt = {
            "draft_id": BODY["draft_id"],
            "revision": BODY["revision"],
            "current_values": BODY["current_values"],
            "selected": [],
            "edits": {},
        }
        url = f"/api/research/lookups/{result['id']}/apply"
        discarded = await client.post(url, json=adopt)
        assert discarded.json()["patch"] == {}
        selected = await client.post(
            url, json=adopt | {"selected": [index], "edits": {str(index): "Manually corrected specification"}}
        )
        assert selected.json()["patch"] == {"Specifications": "Manually corrected specification"}
        stale = await client.post(url, json=adopt | {"current_values": {}})
        assert stale.status_code == 409
    gateway.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_identity_proposals_edit_select_without_duplicate_custom_fields(harness):
    app, gateway = harness
    gateway.update_item = AsyncMock()
    gateway.get_capture_profile.return_value["template"]["fields"].extend(
        {"id": name, "name": name, "type": "text"} for name in ("Hersteller", "Modellnummer", "Part number")
    )
    app.state.research_provider.research.return_value = ResearchResult(
        status="matched",
        claims=[
            Claim(field="manufacturer", value="Example Maker"),
            Claim(field="model_number", value="MODEL-002"),
            Claim(field="part_number", value="PART-003"),
        ],
    )
    body = {k: v for k, v in BODY.items() if k != "identity"} | {
        "context": {"manufacturer": "Existing maker", "model_number": "MODEL-001"}
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/research/lookups", json=body)
        assert response.status_code == 200, response.text
        review = response.json()
        native = {p.get("target"): (i, p) for i, p in enumerate(review["proposals"]) if p.get("target")}
        assert set(native) == {"manufacturer", "model_number"}
        assert native["manufacturer"][1]["current"] == "Existing maker"
        assert native["model_number"][1]["current"] == "MODEL-001"
        assert [p["name"] for p in review["proposals"] if not p.get("target")] == ["Part number"]
        index = native["manufacturer"][0]
        adoption = {k: body[k] for k in ("draft_id", "revision", "current_values")} | {
            "selected": [index],
            "edits": {str(index): "Reviewed maker"},
        }
        url = f"/api/research/lookups/{review['id']}/apply"
        adopted = await client.post(url, json=adoption)
        assert adopted.json()["item_patch"] == {"manufacturer": "Reviewed maker"}
        assert adopted.json()["patch"] == {}
        assert (await client.post(url, json=adoption | {"revision": "changed"})).status_code == 409
        # Legacy identity-only clients still receive their template fields.
        legacy = await client.post("/api/research/lookups", json=BODY)
        assert {p["name"] for p in legacy.json()["proposals"]} == {"Hersteller", "Modellnummer", "Part number"}
    gateway.update_item.assert_not_awaited()
