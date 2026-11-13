"""Synthetic native HTTP-boundary contract; no live server."""

import json

import httpx
import pytest

from homebox_companion import HomeboxClient
from homebox_companion.homebox.models import ItemCreate

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]
TYPE = "00000000-0000-4000-8000-000000000010"
TEMPLATE = "00000000-0000-4000-8000-000000000020"


@pytest.mark.parametrize(
    "case", ["text", "number", "boolean", "time", "unknown", "stale", "scope", "missing", "orphan"]
)
async def test_chosen_profile_preflight_before_mutation(case):
    writes = []

    def upstream(request):
        if request.method != "GET":
            writes.append((request.url.path, json.loads(request.content)))
            return httpx.Response(201, json={"id": "synthetic-created"})
        if request.url.path == "/entity-types":
            return httpx.Response(
                200, json=[] if case == "scope" else [{"id": TYPE, "isLocation": False, "defaultTemplateId": TEMPLATE}]
            )
        if request.url.path == "/templates":
            return httpx.Response(200, json=[] if case == "missing" else [{"id": TEMPLATE}])
        return httpx.Response(
            200,
            json={
                "id": TEMPLATE,
                "fields": [
                    {
                        "name": "Part number",
                        "type": case if case in {"number", "boolean", "time", "unknown"} else "text",
                        "textValue": "0007-SYN-A",
                    }
                ],
            },
        )

    data = {"name": "Synthetic part", "entity_type_id": TYPE, "template_id": TEMPLATE}
    if case == "stale":
        data["template_id"] = "00000000-0000-4000-8000-000000000099"
    if case == "orphan":
        del data["entity_type_id"]
    async with HomeboxClient(base_url="http://native", transport=httpx.MockTransport(upstream)) as client:
        if case == "text":
            await client.create_item("synthetic", ItemCreate.model_validate(data))
            assert writes[0][0] == f"/templates/{TEMPLATE}/create-item"
            assert writes[0][1]["entityTypeId"] == TYPE
            assert "templateId" not in writes[0][1]
        else:
            with pytest.raises(Exception, match="[Tt]emplate|[Tt]ype|text"):
                await client.create_item("synthetic", ItemCreate.model_validate(data))
            assert writes == []
