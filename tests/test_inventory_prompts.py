"""Inventory guidance applies across capture modes, without changing saved preferences."""

import pytest

from homebox_companion.core.field_preferences import get_defaults
from homebox_companion.tools.vision.prompts import (
    build_analysis_system_prompt,
    build_detection_system_prompt,
    build_discriminatory_system_prompt,
    build_multi_image_system_prompt,
)


@pytest.mark.parametrize(
    "preferences",
    [
        {},
        get_defaults().get_effective_customizations(),
        {
            "description": (
                "Product features and specifications - what IS this item. Max 1000 chars, NEVER mention quantity"
            ),
            "manufacturer": "Only when brand/logo is VISIBLE. Include recognizable brands only.",
        },
    ],
)
@pytest.mark.parametrize(
    "builder",
    [
        build_detection_system_prompt,
        build_multi_image_system_prompt,
        build_discriminatory_system_prompt,
        build_analysis_system_prompt,
    ],
)
def test_capture_describes_product_not_photo_even_with_saved_preferences(builder, preferences):
    args = ("Synthetic product", "Observed packaging") if builder is build_analysis_system_prompt else ()
    prompt = builder(*args, field_preferences=preferences, output_language="German")
    assert "searchable records for an inventory app" in prompt
    assert "find the item again, distinguish similar variants" in prompt
    assert "information-dense technical description" in prompt
    assert "specifications as named values with units" in prompt
    assert "clearly labelled technical values on packaging are product evidence" in prompt
    assert "Do not assign meanings or units to unexplained numbers" in prompt
    assert "Keep the title concise" in prompt
    assert "not a photo caption" in prompt
    assert "readable package label can identify the product" in prompt
    assert "dedicated identifier fields" in prompt
    assert "Do not infer unseen condition, quantity, contents or specifications" in prompt
    assert "unknown facts unknown" in prompt
    assert "Spurplatten/Spurverbreiterung" in prompt
    assert "generic verify-fitment" in prompt
    assert "all text values" in prompt and "custom/technical fields" in prompt
    assert "proper names" in prompt and "literal identifiers" in prompt
    assert "German" in prompt
    assert "condition/attributes only" not in prompt
