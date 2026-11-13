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
            data={"entity_type_id": TYPE, "template_id": TEMPLATE},
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
