"""Supported native capture templates (Homebox text fields only)."""

from typing import Any

from ..core.exceptions import CaptureProfileError
from ..core.persistent_settings import CustomFieldDefinition
from ..tools.vision.models import DetectedItem


def template_text_fields(template: dict[str, Any] | None) -> list[dict[str, Any]]:
    fields = (template or {}).get("fields", [])
    if any(field.get("type") != "text" for field in fields):
        raise CaptureProfileError("Unsupported template: only text fields are supported")
    names = [field["name"] for field in fields]
    if len(set(names)) != len(names):
        raise CaptureProfileError("Ambiguous duplicate template field names")
    return fields


def template_vision_fields(template: dict[str, Any] | None) -> list[CustomFieldDefinition]:
    definitions = [
        CustomFieldDefinition(
            name=field["name"],
            ai_instruction=(
                f"Read the visible value for {field['name']!r} as exact text; preserve leading zeros, "
                "punctuation and case. Return null if not visible; do not invent values or defaults."
            ),
        )
        for field in template_text_fields(template)
    ]
    keys = [field.field_key for field in definitions]
    aliases = [field.prompt_key for field in definitions]
    reserved = set(DetectedItem.model_fields) | {field.alias for field in DetectedItem.model_fields.values()}
    if len(set(keys)) != len(keys) or len(set(aliases)) != len(aliases) or reserved.intersection(keys + aliases):
        raise CaptureProfileError("Template field names collide in the vision schema")
    return definitions
