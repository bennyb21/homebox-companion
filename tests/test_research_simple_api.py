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

from homebox_companion.research import parse_response


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
