"""Offline credential sharing boundary: only official OpenAI endpoints."""

import re

OPENAI_BASE = "https://api.openai.com/v1"


def official_openai(model: str, api_base: str | None) -> bool:
    return bool(
        api_base in (None, "", OPENAI_BASE)
        and re.fullmatch(r"(?:openai/)?(?:gpt-[A-Za-z0-9._-]+|o[134](?:-[A-Za-z0-9._-]+)?)", model)
    )


# Exact first-party model specification, not a union across reasoning models.
# https://developers.openai.com/api/docs/models/gpt-6-luna
RESEARCH_REASONING = {"gpt-6-luna": ("none", "low", "medium", "high", "xhigh", "max")}
