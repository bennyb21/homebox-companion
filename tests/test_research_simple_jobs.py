"""Saved-item whole context, including photo bytes and stale-photo protection."""

import asyncio
import io
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from test_research_api import TYPE
from test_research_api import harness as harness


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_readback", [False, True])
async def test_saved_whole_item_photos_bound_to_job_and_manual_adoption(harness, tmp_path, wrong_readback):
    app, gateway = harness
    app.state.research_db_path = tmp_path / "research.sqlite3"
    from homebox_companion.research import Claim

    app.state.research_provider.research.return_value.claims.extend(
        [
            Claim(field="title", value="Proposed title"),
            Claim(field="manufacturer", value="Example Maker"),
            Claim(field="model_number", value="MODEL-002"),
            Claim(field="description", value="Proposed description, not selected"),
        ]
    )
    current = {
        "id": "item1",
        "name": "Spacer",
        "description": "Observed 0112-S90-6-10-032-N-B",
        "entityType": {"id": TYPE},
        "fields": [{"id": "f1", "name": "Specifications", "type": "text", "textValue": ""}],
        "attachments": [{"id": "photo1", "type": "photo", "primary": True}],
        "manufacturer": "Old maker",
        "modelNumber": "MODEL-001",
        "serialNumber": "SERIAL-UNCHANGED",
        "purchasePrice": 42,
        "tags": [],
    }
    image = io.BytesIO()
    Image.new("RGB", (12, 12), "blue").save(image, format="PNG")
    photos = {"photo1": image.getvalue()}
    gateway.get_current_user = AsyncMock(return_value={"id": "user1"})
    gateway.get_item = AsyncMock(side_effect=lambda _: deepcopy(current))
    gateway.get_research_photo = AsyncMock(side_effect=lambda item, id_: photos[id_])

    async def update(_, payload):
        assert "model_number" not in payload
        current.update(payload)
        if wrong_readback:
            current["modelNumber"] = "MODEL-001"

    gateway.update_item = AsyncMock(side_effect=update)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            body = {"item_id": "item1", "idempotency_key": "whole"}
            created = await client.post("/api/research/jobs", json=body)
            assert created.status_code == 202, created.text
            id_ = created.json()["id"]
            for _ in range(100):
                response = await client.get(f"/api/research/jobs/{id_}")
                if response.json()["state"] == "matched":
                    break
                await asyncio.sleep(0.01)
            assert response.json()["state"] == "matched", response.text
            sent = app.state.research_provider.research.call_args.args[0]
            assert sent.title == "Spacer" and len(sent.images) == 1
            assert sent.manufacturer == "Old maker" and sent.model_number == "MODEL-001"
            proposals = response.json()["result"]["proposals"]
            assert proposals[2]["target"] == "manufacturer" and proposals[2]["current"] == "Old maker"
            assert proposals[3]["target"] == "model_number" and proposals[3]["current"] == "MODEL-001"
            assert "purchasePrice" not in sent.model_dump()
            gateway.update_item.assert_not_awaited()
            assert (await client.post("/api/research/jobs", json=body)).json()["id"] == id_
            # Same attachment metadata, replaced bytes: must not apply old advice.
            photos["photo1"] = image.getvalue() + b"changed"
            stale = await client.post(f"/api/research/jobs/{id_}/apply", json={"selected": [0]})
            assert stale.status_code == 409, stale.text
            gateway.update_item.assert_not_awaited()
            photos["photo1"] = image.getvalue()
            applied = await client.post(
                f"/api/research/jobs/{id_}/apply",
                json={
                    "selected": [0, 1, 2, 3],
                    "edits": {
                        "0": "Reviewed steel",
                        "1": "Reviewed title",
                        "2": "Reviewed maker",
                        "3": "MODEL-REVIEWED",
                    },
                },
            )
            if wrong_readback:
                assert applied.status_code == 409, applied.text
                assert (await client.get(f"/api/research/jobs/{id_}")).json()["state"] == "apply_unknown"
                return
            assert applied.status_code == 200, applied.text
            assert current["manufacturer"] == "Reviewed maker"
            assert current["modelNumber"] == "MODEL-REVIEWED"
            assert current["serialNumber"] == "SERIAL-UNCHANGED"
            assert current["description"] == "Observed 0112-S90-6-10-032-N-B"
            assert current["fields"][0]["textValue"] == "Reviewed steel"
            assert current["name"] == "Reviewed title"
            assert current["purchasePrice"] == 42
    finally:
        if hasattr(app.state, "research_jobs"):
            await app.state.research_jobs.close()


@pytest.mark.asyncio
async def test_research_photo_download_is_bounded_and_never_follows_redirects():
    from homebox_companion.homebox.client import HomeboxClient

    assert hasattr(HomeboxClient, "get_research_photo")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://outside.invalid/image"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        gateway = HomeboxClient(base_url="https://inventory.invalid/api/v1", client=client)
        with pytest.raises(ValueError, match="Research photo unavailable"):
            await gateway.get_research_photo("synthetic-secret", "item1", "photo1")
        assert len(requests) == 1
        with pytest.raises(ValueError):
            await gateway.get_research_photo("synthetic-secret", "item1", "../outside")
        assert len(requests) == 1

    def oversized(request):
        return httpx.Response(200, content=b"x" * 6_000_001)

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        gateway = HomeboxClient(base_url="https://inventory.invalid/api/v1", client=client)
        with pytest.raises(ValueError):
            await gateway.get_research_photo("synthetic-secret", "item1", "photo1")
