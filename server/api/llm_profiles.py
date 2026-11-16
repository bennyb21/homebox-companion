"""LLM Profiles API routes.

CRUD operations for LLM model profiles with connection testing.
API keys are never sent to the frontend - only `has_api_key: bool` is exposed.
"""

from collections.abc import Callable
from typing import Literal
from urllib.parse import quote

import httpx
import litellm
from fastapi import APIRouter, Depends, HTTPException
from litellm.exceptions import APIConnectionError, AuthenticationError, NotFoundError
from loguru import logger
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, field_validator

from homebox_companion.core import config
from homebox_companion.core.credential_policy import (
    OPENAI_BASE,
    RESEARCH_REASONING,
    official_openai,
    official_openai_model_id,
    research_eligibility_source,
)
from homebox_companion.core.llm_utils import resolve_profile_key
from homebox_companion.core.persistent_settings import (
    ModelProfile,
    PersistentSettings,
    ProfileStatus,
    clear_settings_cache,
    load_settings,
    mutate_settings,
)
from homebox_companion.research import (
    OpenAIResponsesResearchProvider,
    ProductContext,
    ProductIdentity,
    ResearchPolicy,
    ResearchResult,
)
from homebox_companion.research_diagnostics import Diagnostic, diagnostic, http_error_code, safe_request_id

from ..dependencies import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


# ============================================================================
# Response Models (safe for frontend - no secrets)
# ============================================================================


class ProfileResponse(BaseModel):
    """Profile data safe for frontend display."""

    name: str
    model: str
    has_api_key: bool
    api_base: str | None
    status: str
    credential_source: str
    credential_profile_name: str | None
    research_reasoning_effort: str | None
    research_assigned: bool
    can_share_credential: bool


class ProfileListResponse(BaseModel):
    """List of profiles for frontend."""

    profiles: list[ProfileResponse]
    reasoning_options: dict[str, tuple[str, ...]]
    environment_credential_available: bool


class CredentialRequest(BaseModel):
    @field_validator("model", "api_key", "api_base", check_fields=False)
    @classmethod
    def reject_sdk_indirection(cls, value: str | None) -> str | None:
        if value and value.startswith("os.environ/"):
            raise ValueError("Use the explicit credential source, not SDK environment indirection")
        return value


class ProfileCreateRequest(CredentialRequest):
    """Request to create a new profile."""

    name: str
    model: str
    api_key: str | None = None
    api_base: str | None = None
    status: ProfileStatus = ProfileStatus.OFF
    credential_source: Literal["own", "env", "profile"] = "own"
    credential_profile_name: str | None = None
    research_reasoning_effort: str | None = None


class ProfileUpdateRequest(CredentialRequest):
    """Request to update an existing profile.

    For api_key:
    - None/missing = keep existing key unchanged
    - "sk-xxx" = set new key
    """

    new_name: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    status: ProfileStatus | None = None
    credential_source: Literal["own", "env", "profile"] | None = None
    credential_profile_name: str | None = None
    research_reasoning_effort: str | None = None


class TestConnectionRequest(CredentialRequest):
    """Request to test a profile connection."""

    model_config = ConfigDict(extra="forbid")
    test_kind: Literal["connection", "research"] = "connection"
    identity: ProductIdentity | None = None
    context: ProductContext | None = None

    # Optional override for testing before saving
    model: str | None = None
    api_key: str | None = None
    api_base: str | None = None


class TestConnectionResponse(BaseModel):
    """Response from connection test."""

    success: bool
    message: str
    model_info: dict | None = None
    diagnostic: Diagnostic | None = None
    research_result: ResearchResult | None = None


# ============================================================================
# Helper Functions
# ============================================================================


def _profile_to_response(profile: ModelProfile, settings: PersistentSettings) -> ProfileResponse:
    """Convert internal profile to safe frontend response."""
    return ProfileResponse(
        name=profile.name,
        model=profile.model,
        has_api_key=bool(resolve_profile_key(profile, settings)),
        credential_source=profile.credential_source,
        credential_profile_name=profile.credential_profile_name,
        research_reasoning_effort=profile.research_reasoning_effort,
        research_assigned=settings.research_profile_name == profile.name,
        can_share_credential=profile.credential_source == "own"
        and bool(profile.api_key)
        and official_openai(profile.model, profile.api_base),
        api_base=profile.api_base,
        status=profile.status.value,
    )


def _select_research(settings: PersistentSettings, name: str | None) -> None:
    for profile in settings.llm_profiles:
        if profile.status == ProfileStatus.RESEARCH and profile.name != name:
            profile.status = ProfileStatus.OFF
    settings.research_profile_name = name


def _find_profile(settings: PersistentSettings, name: str) -> tuple[int, ModelProfile]:
    """Find profile by name, raise 404 if not found."""
    for i, p in enumerate(settings.llm_profiles):
        if p.name == name:
            return i, p
    raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")


def _mutate_profiles(mutate: Callable[[PersistentSettings], None]) -> PersistentSettings:
    """Preserve the public validation error while committing one transaction."""
    try:

        def checked(settings: PersistentSettings) -> None:
            existing_env = {p.name for p in settings.llm_profiles if p.credential_source == "env"}
            mutate(settings)
            if settings.research_enabled:
                selected = next((p for p in settings.llm_profiles if p.name == settings.research_profile_name), None)
                if selected is None or research_profile_reason(selected, settings) is not None:
                    raise HTTPException(
                        400, "Disable research or choose an eligible profile before changing its model or credential"
                    )
            for profile in settings.llm_profiles:
                if (
                    profile.credential_source == "env"
                    and profile.name not in existing_env
                    and not official_openai(config.settings.effective_llm_model, config.settings.llm_api_base)
                ):
                    raise HTTPException(
                        400,
                        "Environment credential is incompatible; choose an own key "
                        "or an official OpenAI source profile",
                    )

        return mutate_settings(checked)
    except ValidationError as exc:
        # Only validator-owned messages, never Pydantic input/context (contains secrets).
        messages = [
            e["msg"].removeprefix("Value error, ") for e in exc.errors(include_input=False, include_context=False)
        ]
        raise HTTPException(status_code=400, detail="; ".join(messages)) from None


# ============================================================================
# Endpoints
# ============================================================================


class ResearchSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    profile_name: str | None = None


def research_profile_reason(profile: ModelProfile, settings: PersistentSettings | None = None) -> str | None:
    """Offline eligibility only; never verifies billing, access or live quality."""
    if not OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=True, profile_name=profile.name), profile, settings=settings
    ).configured:
        return "Use an existing key, an unprefixed OpenAI model name and no custom API base."
    if research_eligibility_source(profile.model) == "unverified":
        return (
            "This exact model's web search support is unverified in official metadata and the installed catalog. "
            "A connection test checks model access only; it does not prove web search support."
        )
    return None


def _research_settings_response(settings: PersistentSettings) -> dict:
    return {
        "enabled": settings.research_enabled,
        "profile_name": settings.research_profile_name,
        "profiles": [
            {
                "name": p.name,
                "model": p.model,
                "eligible": reason is None,
                "reason": reason,
                "eligibility_source": research_eligibility_source(p.model),
            }
            for p in settings.llm_profiles
            for reason in [research_profile_reason(p, settings)]
        ],
    }


@router.get("/settings/research")
async def get_research_settings() -> dict:
    return _research_settings_response(load_settings())


@router.put("/settings/research")
async def update_research_settings(request: ResearchSettingsRequest) -> dict:
    def mutate(settings: PersistentSettings) -> None:
        name = request.profile_name
        if request.enabled:
            eligible = [p for p in settings.llm_profiles if research_profile_reason(p, settings) is None]
            if name is None and len(eligible) == 1:
                name = eligible[0].name
            if name is None or name not in {p.name for p in eligible}:
                raise HTTPException(400, "Select one eligible existing OpenAI research profile")
        settings.research_enabled = request.enabled
        _select_research(settings, name)

    return _research_settings_response(_mutate_profiles(mutate))


@router.get("/llm/profiles", response_model=ProfileListResponse)
async def list_profiles() -> ProfileListResponse:
    """List all LLM profiles (API keys masked)."""
    clear_settings_cache()
    settings = load_settings()

    profiles = [_profile_to_response(p, settings) for p in settings.llm_profiles]
    return ProfileListResponse(
        profiles=profiles,
        reasoning_options=RESEARCH_REASONING,
        environment_credential_available=bool(config.settings.effective_llm_api_key)
        and official_openai(config.settings.effective_llm_model, config.settings.llm_api_base),
    )


@router.post("/llm/profiles", response_model=ProfileResponse, status_code=201)
async def create_profile(request: ProfileCreateRequest) -> ProfileResponse:
    """Create a new LLM profile."""

    def mutate(settings: PersistentSettings) -> None:
        # Check for duplicate name
        for p in settings.llm_profiles:
            if p.name == request.name:
                raise HTTPException(status_code=409, detail=f"Profile '{request.name}' already exists")

        # If this is the first profile, make it active
        status = request.status
        if not settings.llm_profiles and status != ProfileStatus.RESEARCH:
            status = ProfileStatus.PRIMARY
            logger.info("First profile created, setting as primary")

        new_profile = ModelProfile(
            name=request.name,
            model=request.model,
            api_key=SecretStr(request.api_key) if request.api_key else None,
            api_base=request.api_base,
            status=status,
            credential_source=request.credential_source,
            credential_profile_name=request.credential_profile_name,
            research_reasoning_effort=request.research_reasoning_effort,
        )

        if status in (ProfileStatus.PRIMARY, ProfileStatus.FALLBACK):
            for profile in settings.llm_profiles:
                if profile.status == status:
                    profile.status = ProfileStatus.OFF

        settings.llm_profiles.append(new_profile)
        if status == ProfileStatus.RESEARCH:
            _select_research(settings, new_profile.name)

    settings = _mutate_profiles(mutate)
    logger.info("LLM profile mutation saved: create_profile")
    return _profile_to_response(_find_profile(settings, request.name)[1], settings)


@router.put("/llm/profiles/{name}", response_model=ProfileResponse)
async def update_profile(name: str, request: ProfileUpdateRequest) -> ProfileResponse:
    """Update an existing LLM profile."""

    def mutate(settings: PersistentSettings) -> None:
        _, profile = _find_profile(settings, name)

        # Handle renaming
        if request.new_name is not None and request.new_name != name:
            # Check for duplicate name
            for p in settings.llm_profiles:
                if p.name == request.new_name:
                    raise HTTPException(status_code=409, detail=f"Profile '{request.new_name}' already exists")
            if settings.research_profile_name == name:
                settings.research_profile_name = request.new_name
            for p in settings.llm_profiles:
                if p.credential_profile_name == name:
                    p.credential_profile_name = request.new_name
            profile.name = request.new_name
            logger.info(f"Renamed LLM profile: {name} -> {request.new_name}")

        # Update fields if provided
        if request.model is not None:
            profile.model = request.model

        if "api_base" in request.model_fields_set:
            profile.api_base = request.api_base or None

        # Handle api_key specially
        if request.api_key is not None:
            if request.api_key == "":
                profile.api_key = None  # Clear the key
            else:
                profile.api_key = SecretStr(request.api_key)

        if request.credential_source is not None:
            profile.credential_source = request.credential_source
        if "credential_profile_name" in request.model_fields_set:
            profile.credential_profile_name = request.credential_profile_name
        if "research_reasoning_effort" in request.model_fields_set:
            profile.research_reasoning_effort = request.research_reasoning_effort

        if request.status is not None:
            new_status = request.status
            if profile.status == ProfileStatus.PRIMARY and new_status == ProfileStatus.OFF:
                raise HTTPException(400, "Choose another Primary before switching this profile Off")
            if new_status == ProfileStatus.RESEARCH:
                if profile.status in (ProfileStatus.PRIMARY, ProfileStatus.FALLBACK):
                    raise HTTPException(
                        400,
                        "Keep capture configured: use the research selector to also assign "
                        "this Primary/Fallback profile, "
                        "or create a dedicated Research profile",
                    )
                _select_research(settings, profile.name)
            elif profile.status == ProfileStatus.RESEARCH:
                _select_research(settings, None)
                settings.research_enabled = False

            # If setting to active, deactivate others
            if new_status == ProfileStatus.PRIMARY:
                for p in settings.llm_profiles:
                    if p.status == ProfileStatus.PRIMARY:
                        p.status = ProfileStatus.OFF

            # If setting to fallback, remove other fallbacks
            if new_status == ProfileStatus.FALLBACK:
                for p in settings.llm_profiles:
                    if p.status == ProfileStatus.FALLBACK:
                        p.status = ProfileStatus.OFF

            profile.status = new_status

    settings = _mutate_profiles(mutate)
    logger.info("LLM profile mutation saved: update_profile")
    return _profile_to_response(
        _find_profile(settings, request.new_name if request.new_name is not None else name)[1], settings
    )


@router.delete("/llm/profiles/{name}", status_code=204)
async def delete_profile(name: str) -> None:
    """Delete an LLM profile."""

    def mutate(settings: PersistentSettings) -> None:
        idx, profile = _find_profile(settings, name)
        was_active = profile.status == ProfileStatus.PRIMARY
        if any(p.credential_profile_name == name for p in settings.llm_profiles):
            raise HTTPException(
                400, "Another profile references this credential; change that reference before deleting"
            )
        if settings.research_profile_name == name:
            settings.research_profile_name = None
            settings.research_enabled = False

        # Remove the profile by index
        del settings.llm_profiles[idx]

        # If deleted the active profile, activate the first remaining one
        if was_active and settings.llm_profiles:
            replacement = next((p for p in settings.llm_profiles if p.status != ProfileStatus.RESEARCH), None)
            if replacement is None:
                raise HTTPException(
                    400, "Assign a new Primary before deleting; Research is never promoted automatically"
                )
            replacement.status = ProfileStatus.PRIMARY

    _mutate_profiles(mutate)
    logger.info("LLM profile mutation saved: delete_profile")


@router.post("/llm/profiles/{name}/activate", response_model=ProfileResponse)
async def activate_profile(name: str) -> ProfileResponse:
    """Set a profile as the active one."""

    def mutate(settings: PersistentSettings) -> None:
        _, profile = _find_profile(settings, name)

        # Deactivate current primary
        for p in settings.llm_profiles:
            if p.status == ProfileStatus.PRIMARY:
                p.status = ProfileStatus.OFF

        # Activate the target profile (already in the list, mutated in-place)
        profile.status = ProfileStatus.PRIMARY

    settings = _mutate_profiles(mutate)
    logger.info("LLM profile mutation saved: activate_profile")
    return _profile_to_response(_find_profile(settings, name)[1], settings)


async def _test_openai_model_access(model: str, api_key: str, provider_model: str) -> TestConnectionResponse:
    """One explicit read-only request, fixed destination, no SDK catalog inference."""
    status = None
    request_id = None
    try:
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, transport=httpx.AsyncHTTPTransport(retries=0), timeout=15
        ) as client:
            response = await client.get(
                f"{OPENAI_BASE}/models/{quote(provider_model, safe='')}", headers={"Authorization": f"Bearer {api_key}"}
            )
        status = response.status_code
        request_id = safe_request_id(response.headers.get("x-request-id"))
        if status != 200:
            code = http_error_code(status)
        elif response.json().get("id") != provider_model or response.json().get("object") != "model":
            code = "response_invalid"
        else:
            code = "connection_verified"
    except httpx.TimeoutException:
        code = "timeout"
    except httpx.HTTPError:
        code = "transport_error"
    except ValueError, AttributeError:
        code = "response_invalid"
    detail = diagnostic(
        code, "response" if status else "dispatch", http_status=status, request_id=request_id, dispatch_started=True
    )
    logger.info("Profile test diagnostic: {}", detail.model_dump_json(exclude_none=True))
    return TestConnectionResponse(
        success=code == "connection_verified",
        message=detail.message or code,
        model_info={"model": model, "provider": "openai", "test_kind": "connection"},
        diagnostic=detail,
    )


@router.post("/llm/profiles/{name}/test", response_model=TestConnectionResponse)
async def test_profile_connection(name: str, request: TestConnectionRequest | None = None) -> TestConnectionResponse:
    """Test connection to an LLM profile.

    Optionally override settings for testing before saving.
    """

    # A model-level validation error echoes the complete input, including an
    # optional key override. Keep this cross-field error fixed and input-free.
    if request and request.test_kind == "research" and (request.identity is None) == (request.context is None):
        raise HTTPException(422, "Research testing requires product context or a legacy identity, not both")

    clear_settings_cache()
    settings = load_settings()

    _, profile = _find_profile(settings, name)

    # Overrides cannot re-route a stored credential to a different destination/provider.
    model = request.model if request and request.model else profile.model
    api_base = request.api_base if request and request.api_base else profile.api_base
    if request and not request.api_key and (model != profile.model or api_base != profile.api_base):
        same_openai_provider = official_openai(model, None) and official_openai(profile.model, None)
        same_destination = api_base == profile.api_base
        if not (same_openai_provider and same_destination) and not (
            official_openai(model, api_base) and official_openai(profile.model, profile.api_base)
        ):
            raise HTTPException(400, "Save and review destination changes before testing with stored credentials")
    api_key = request.api_key if request and request.api_key else resolve_profile_key(profile, settings)
    if request and request.test_kind == "research":
        selected = profile.model_copy(deep=True)
        selected.model = model
        selected.api_base = api_base
        if request.api_key:
            selected.credential_source = "own"
            selected.credential_profile_name = None
            selected.api_key = SecretStr(request.api_key)
        context = request.context or request.identity
        assert context is not None
        result = await OpenAIResponsesResearchProvider(
            ResearchPolicy(enabled=True, profile_name=name), selected, settings=settings
        ).research(context)
        return TestConnectionResponse(
            success=result.status in {"matched", "no_results"},
            message=result.diagnostic.message
            if result.diagnostic and result.diagnostic.message
            else "Research did not produce a validated result.",
            model_info={"model": model, "provider": "openai", "test_kind": "research"},
            diagnostic=result.diagnostic,
            research_result=result,
        )
    if not api_key and official_openai(model, api_base):
        detail = diagnostic("credential_missing", "configuration", dispatch_started=False)
        return TestConnectionResponse(success=False, message=detail.message or detail.code, diagnostic=detail)
    api_key = api_key or "hbc-no-configured-key"
    # Match inference: an omitted official base must not inherit an SDK gateway.
    if (provider_model := official_openai_model_id(model, api_base)) is not None:
        return await _test_openai_model_access(model, api_key, provider_model)

    try:
        # Simple completion test
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "Say 'connection successful' in exactly two words."}],
            api_key=api_key,
            api_base=api_base,
            max_tokens=10,
            timeout=15,
        )

        model_info = {
            "model": response.model,
            "provider": getattr(response, "_hidden_params", {}).get("custom_llm_provider", "unknown"),
        }

        return TestConnectionResponse(
            success=True,
            message="Legacy completion test succeeded. Research web search and citation parsing were not tested.",
            model_info=model_info,
        )

    except AuthenticationError:
        logger.warning(f"Authentication failed testing profile {name}")
        return TestConnectionResponse(
            success=False,
            message="Authentication failed. Check your API key.",
        )

    except NotFoundError:
        logger.warning(f"Model not found testing profile {name}")
        return TestConnectionResponse(
            success=False,
            message=f"Model '{model}' not found. Check the model name.",
        )

    except APIConnectionError:
        logger.warning(f"Connection error testing profile {name}")
        return TestConnectionResponse(
            success=False,
            message=f"Could not connect to API. Check api_base URL: {api_base or 'default'}",
        )

    except Exception as e:
        logger.error(f"Error testing profile {name}: {type(e).__name__}")
        return TestConnectionResponse(
            success=False,
            message="Connection test failed. Check the provider configuration.",
        )
