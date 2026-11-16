"""Focused simplified contract; real public response, no paid calls."""

import json
from pathlib import Path

import httpx
import pytest

from homebox_companion.research import ProductIdentity, parse_response

FIXTURES = Path(__file__).parent / "fixtures" / "research"


def test_actual_whole_item_response_keeps_usable_fields():
    result = parse_response(
        json.loads((FIXTURES / "public-whole-item.json").read_text()),
        ProductIdentity(identifier_kind="model_number", identifier_exact="0112-S90-6-10-032-N-B"),
    )
    assert result.status == "matched"
    fields = {c.field: c.value for c in result.claims}
    assert fields["manufacturer"] == "Eibach"
    assert "10 mm" in fields["specifications"]
    assert "0112-" in result.ambiguity
    assert result.sources


def test_missing_bad_citations_and_unknown_fields_do_not_drop_suggestions():
    response = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "fields": {
                                    "manufacturer": "Maker",
                                    "future_field": 42,
                                    "model_number": [],
                                    "specifications": "Serial marking observed: AB-1",
                                }
                            }
                        ),
                        "annotations": [{"type": "url_citation", "url": "javascript:alert(1)"}],
                    }
                ],
            }
        ],
    }
    result = parse_response(response)
    assert {c.field for c in result.claims} == {"manufacturer", "specifications"}
    assert result.sources == []
    assert all(not c.source_urls for c in result.claims)


def test_previous_real_responses_are_usable_without_exact_echo_or_url_equality():
    for name in ("public-markdown-citation.json", "public-control-markdown-citation.json"):
        data = json.loads((FIXTURES / name).read_text())
        result = parse_response(data.get("response", data))
        assert result.status == "matched", (name, result)
        assert result.claims


@pytest.mark.asyncio
async def test_photo_and_literal_context_at_actual_sdk_wire(monkeypatch, tmp_path):
    import base64
    import hashlib
    import io
    import socket

    from PIL import Image
    from pydantic import SecretStr

    import homebox_companion.research as research
    from homebox_companion.ai.images import optimize_image_for_vision
    from homebox_companion.core import field_preferences
    from homebox_companion.core.persistent_settings import ModelProfile

    def blocked(*args, **kwargs):
        pytest.fail("Offline wire test attempted a network connection")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    assert hasattr(research, "ProductContext")
    image = io.BytesIO()
    Image.new("RGB", (12, 12), "blue").save(image, format="PNG")
    raw = image.getvalue()
    uri = "data:image/png;base64," + base64.b64encode(raw).decode()
    context = research.ProductContext(
        title="Spacer",
        model_number="0112-S90-6-10-032-N-B",
        technical_fields={"Material": "Aluminum", "Account": "private"},
        images=[uri, uri],
    )
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "model": "gpt-4.1-mini",
                **json.loads((FIXTURES / "public-whole-item.json").read_text()),
            },
        )

    preferences = tmp_path / "field_preferences.json"
    preferences.write_text(json.dumps({"output_language": "German"}))
    monkeypatch.setattr(field_preferences, "PREFERENCES_FILE", preferences)
    provider = research.OpenAIResponsesResearchProvider(
        research.ResearchPolicy(enabled=True, profile_name="test"),
        ModelProfile(name="test", model="gpt-4.1-mini", api_key=SecretStr("synthetic")),
        transport=httpx.MockTransport(respond),
    )
    result = await provider.research(context)
    assert result.status == "matched"
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    instructions = body["instructions"]
    assert "German" in instructions and "ambiguity" in instructions
    assert "all text values" in instructions and "proper names" in instructions
    assert "manufacturer" in instructions and "Germany/EU" in instructions
    assert "foreign" in instructions and "marketplace" in instructions
    assert "photo caption" in instructions and "unseen condition" in instructions
    assert "Spurplatten" in instructions and "fitment" in instructions
    assert "after the JSON object, not inside field values" in instructions
    content = body["input"][0]["content"]
    assert "0112-S90-6-10-032-N-B" in content[0]["text"]
    assert "private" not in content[0]["text"]
    assert len(content) == 3
    assert content[1]["type"] == content[2]["type"] == "input_image"
    sent = base64.b64decode(content[1]["image_url"].split(",")[1])
    assert hashlib.sha256(sent).digest() == hashlib.sha256(optimize_image_for_vision(raw)[0]).digest()
    assert body["max_tool_calls"] == 1 and body["max_output_tokens"] == 2400


@pytest.mark.parametrize(
    "image", ["https://outside.invalid/photo", "data:image/png;base64,not_base64", "data:image/png;base64,dGV4dA=="]
)
def test_context_rejects_remote_or_invalid_image_data(image):
    from pydantic import ValidationError

    from homebox_companion.research import ProductContext

    with pytest.raises(ValidationError):
        ProductContext(images=[image])
