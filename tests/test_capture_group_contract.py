"""Single-item capture never silently expands provider output into extra drafts."""

from unittest.mock import AsyncMock

import pytest

from homebox_companion.tools.vision import detector


@pytest.mark.asyncio
async def test_single_item_rejects_multiple_provider_objects_without_retry(monkeypatch):
    provider = AsyncMock(return_value={"items": [{"name": "A", "quantity": 1}, {"name": "B", "quantity": 1}]})
    monkeypatch.setattr(detector, "vision_completion", provider)
    with pytest.raises(ValueError, match="exactly one item"):
        await detector._detect_items_from_data_uris(["data:image/jpeg;base64,synthetic"], single_item=True)
    assert provider.await_count == 1


@pytest.mark.asyncio
async def test_legacy_multiple_object_mode_remains_explicit(monkeypatch):
    provider = AsyncMock(return_value={"items": [{"name": "A", "quantity": 1}, {"name": "B", "quantity": 1}]})
    monkeypatch.setattr(detector, "vision_completion", provider)
    items = await detector._detect_items_from_data_uris(["data:image/jpeg;base64,synthetic"], single_item=False)
    assert [item.name for item in items] == ["A", "B"]
    assert provider.await_count == 1
