"""Configuration API routes."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from homebox_companion.core.llm_utils import resolve_profile_key
from homebox_companion.core.persistent_settings import ProfileStatus, get_settings

router = APIRouter()


class ConfigResponse(BaseModel):
    """Safe configuration information for the frontend."""

    is_demo_mode: bool
    # Explicit demo mode from HBC_DEMO_MODE env var only (not URL detection).
    # Used for security-sensitive features like disabling chat.
    demo_mode_explicit: bool
    homebox_url: str
    llm_model: str
    llm_model_source: str
    llm_profile_name: str | None
    llm_credential_source: str
    llm_has_api_key: bool
    fallback_model: str | None
    research_model: str | None
    research_enabled: bool
    update_check_enabled: bool
    image_quality: str
    log_level: str
    capture_max_images: int
    capture_max_file_size_mb: int
    print_enabled: bool
    auth_mode: str
    ai_request_timeout_seconds: int


@router.get("/config", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    """Return safe configuration information.

    This endpoint exposes non-sensitive configuration
    for display in the Settings page.
    """
    app_settings = request.app.state.settings
    snapshot = get_settings()
    primary = next((p for p in snapshot.llm_profiles if p.status == ProfileStatus.PRIMARY), None)
    fallback = next((p for p in snapshot.llm_profiles if p.status == ProfileStatus.FALLBACK), None)
    research = next((p for p in snapshot.llm_profiles if p.name == snapshot.research_profile_name), None)
    return ConfigResponse(
        is_demo_mode=app_settings.is_demo_mode,
        demo_mode_explicit=app_settings.demo_mode,
        homebox_url=app_settings.effective_link_base_url,
        llm_model=primary.model if primary else app_settings.effective_llm_model,
        llm_model_source="profile" if primary else "environment",
        llm_profile_name=primary.name if primary else None,
        llm_credential_source=primary.credential_source if primary else "env",
        llm_has_api_key=bool(resolve_profile_key(primary, snapshot) if primary else app_settings.effective_llm_api_key),
        fallback_model=fallback.model if fallback else None,
        research_model=research.model if research else None,
        research_enabled=snapshot.research_enabled,
        update_check_enabled=not app_settings.disable_update_check,
        image_quality=app_settings.image_quality.value,
        log_level=app_settings.log_level,
        capture_max_images=app_settings.capture_max_images,
        capture_max_file_size_mb=app_settings.capture_max_file_size_mb,
        print_enabled=app_settings.print_enabled,
        auth_mode=app_settings.auth_mode,
        ai_request_timeout_seconds=app_settings.ai_request_timeout_seconds,
    )
