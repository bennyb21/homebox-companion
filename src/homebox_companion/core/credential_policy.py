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
RESEARCH_REASONING = {
    "gpt-6-luna": ("none", "low", "medium", "high", "xhigh", "max"),
    # https://developers.openai.com/api/docs/models/gpt-6.1-terra
    "gpt-6.1-terra": ("none", "low", "medium", "high", "xhigh", "max"),
}


def research_eligibility_source(model: str) -> str:
    """Offline metadata provenance, not account access or successful generation."""
    if model in RESEARCH_REASONING:
        return "official_metadata"
    import litellm

    try:
        if litellm.supports_web_search(model, custom_llm_provider="openai"):
            return "runtime_catalog"
    except Exception:
        pass
    return "unverified"
