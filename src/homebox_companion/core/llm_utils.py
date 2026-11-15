"""LLM credential resolution utilities.

Provides a single source of truth for resolving LLM credentials from:
1. PRIMARY profile from persistent settings
2. Environment variable defaults

This centralizes the resolution logic that was previously duplicated in
ai/llm.py and chat/llm_client.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from . import config
from .credential_policy import official_openai
from .persistent_settings import ModelProfile, PersistentSettings, get_primary_profile, get_settings


@dataclass
class LLMCredentials:
    """Resolved LLM credentials ready for use.

    Attributes:
        model: The model identifier (e.g., 'gpt-5.6-luna', 'claude-3-opus')
        api_key: The API key for authentication
        api_base: Optional custom API base URL
        profile_name: Name of the profile used, or None if using env defaults
    """

    model: str
    api_key: str | None
    api_base: str | None
    profile_name: str | None = None


def resolve_profile_key(profile: ModelProfile, settings: PersistentSettings | None = None) -> str | None:
    """Resolve explicit sources only; never send a shared key to custom endpoints."""
    if profile.credential_source == "own":
        return profile.api_key.get_secret_value() if profile.api_key else None
    if not official_openai(profile.model, profile.api_base):
        return None
    if profile.credential_source == "env":
        env = config.settings
        if official_openai(env.effective_llm_model, env.llm_api_base):
            return env.effective_llm_api_key or None
        return None
    snapshot = settings if settings is not None else get_settings()
    peer = next((p for p in snapshot.llm_profiles if p.name == profile.credential_profile_name), None)
    if (
        peer
        and peer.name != profile.name
        and peer.credential_source == "own"
        and official_openai(peer.model, peer.api_base)
    ):
        return peer.api_key.get_secret_value() if peer.api_key else None
    return None


def resolve_llm_credentials() -> LLMCredentials:
    """Resolve LLM credentials using the unified priority order.

    Resolution priority:
    1. PRIMARY profile from persistent settings
    2. Environment variable defaults

    Returns:
        LLMCredentials with resolved values
    """
    profile_name: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_base: str | None = None

    # Check for PRIMARY profile first
    primary = get_primary_profile()
    if primary:
        profile_name = primary.name
        model = primary.model
        api_key = resolve_profile_key(primary)
        api_base = primary.api_base
        logger.debug(f"Using PRIMARY profile '{primary.name}' with model: {model}")
    else:
        logger.debug("No PRIMARY profile, using env defaults")

    # Environment is a complete alternative, never mixed into a profile.
    if primary is None:
        model = config.settings.effective_llm_model
        api_key = config.settings.effective_llm_api_key
        api_base = config.settings.llm_api_base

    return LLMCredentials(
        model=model or "",
        api_key=api_key,
        api_base=api_base,
        profile_name=profile_name,
    )
