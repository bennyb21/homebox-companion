"""Profile-aware detection, synthetic ASGI/model boundary only."""

import io
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from homebox_companion.core.config import Settings
from homebox_companion.tools.vision.models import get_items_adapter
from server.api.tools import vision
from server.app import create_app
from server.dependencies import VisionContext, get_vision_context, require_llm_configured

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.mark.parametrize("choice", ["type-a", None, "unknown"])
async def test_automatic_types_use_separate_native_schemas(monkeypatch, choice):
    gateway = AsyncMock()
    gateway.list_entity_types.return_value = [
        {"id": "type-a", "name": "Synthetic A", "isLocation": False},
        {"id": "type-b", "name": "Synthetic B", "isLocation": False},
    ]

    async def profile(type_id, template_id=None):
        return {
            "entity_type": {"id": type_id},
            "template": {
                "id": "template-" + type_id,
                "fields": [{"name": type_id, "type": "text", "textValue": "default"}],
            },
        }

    gateway.get_capture_profile.side_effect = profile
    ctx = VisionContext(gateway, [], None, None, None, [])
    calls = []

    async def detect(**kwargs):
        definitions = kwargs["custom_fields"]
        calls.append([field.name for field in definitions])
        if len(calls) == 1:
            assert "Synthetic A" in definitions[0].ai_instruction
            return get_items_adapter(definitions).validate_python(
                [
                    {"name": "Object A", definitions[0].prompt_key: choice},
                    {"name": "Object B", definitions[0].prompt_key: "type-b"},
                ]
            )
        assert kwargs["single_item"] is True
        return get_items_adapter(definitions).validate_python(
            [{"name": "Extracted", definitions[0].prompt_key: "0007"}]
        )

    monkeypatch.setattr(vision, "detect_items_from_bytes", detect)
    app = create_app(Settings(disable_update_check=True))
    app.dependency_overrides[get_vision_context] = lambda: ctx
    app.dependency_overrides[require_llm_configured] = lambda: "synthetic"
    image = io.BytesIO()
    Image.new("RGB", (20, 20)).save(image, format="PNG")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/tools/vision/detect",
            files={"image": ("test.png", image.getvalue(), "image/png")},
            data={"auto_profile": "true"},
            headers={"Authorization": "Bearer synthetic"},
        )
    if choice != "type-a":
        assert response.status_code == 400
        assert "explicit item type" in response.text
        assert len(calls) == 1
        gateway.get_capture_profile.assert_not_awaited()
        return
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["entity_type_id"] for item in items] == ["type-a", "type-b"]
    assert [item["custom_fields"] for item in items] == [{"type-a": "0007"}, {"type-b": "0007"}]
    assert calls == [["Capture type choice"], ["type-a"], ["type-b"]]


TYPE = "00000000-0000-4000-8000-000000000010"
TEMPLATE = "00000000-0000-4000-8000-000000000020"


@pytest.mark.parametrize("field_type", ["text", "number"])
async def test_native_template_drives_detection_and_defaults(monkeypatch, field_type):
    gateway = AsyncMock()
    gateway.get_capture_profile.return_value = {
        "entity_type": {"id": TYPE, "name": "Synthetic part"},
        "template": {
            "id": TEMPLATE,
            "fields": [
                {"name": "Part number", "type": field_type, "textValue": ""},
                {"name": "Condition", "type": "text", "textValue": "unknown"},
            ],
        },
    }
    ctx = VisionContext(gateway, [], None, None, None, [])

    async def detect(**kwargs):
        definitions = kwargs["custom_fields"]
        assert [field.name for field in definitions] == ["Part number", "Condition"]
        assert "leading zeros" in definitions[0].ai_instruction
        return get_items_adapter(definitions).validate_python([{"name": "Synthetic part", "partNumber": "0007-SYN-A"}])

    detector = AsyncMock(side_effect=detect)
    monkeypatch.setattr(vision, "detect_items_from_bytes", detector)
    app = create_app(Settings(disable_update_check=True))
    app.dependency_overrides[get_vision_context] = lambda: ctx
    app.dependency_overrides[require_llm_configured] = lambda: "synthetic"
    image = io.BytesIO()
    Image.new("RGB", (20, 20)).save(image, format="PNG")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/tools/vision/detect",
            files={"image": ("test.png", image.getvalue(), "image/png")},
            headers={"Authorization": "Bearer synthetic"},
            data={"entity_type_id": TYPE, "template_id": TEMPLATE, "auto_profile": "true"},
        )
    if field_type == "number":
        assert response.status_code == 400
        assert "text" in response.text
        detector.assert_not_awaited()
    else:
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["entity_type_id"] == TYPE
        assert item["template_id"] == TEMPLATE
        assert item["custom_fields"] == {"Part number": "0007-SYN-A", "Condition": "unknown"}
        gateway.get_capture_profile.assert_awaited_once_with(TYPE, TEMPLATE)
