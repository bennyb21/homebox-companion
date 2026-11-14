"""Read-only native capture profiles; no application-side schema cache."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from homebox_companion import HomeboxGateway

from ..dependencies import get_gateway

router = APIRouter()


@router.get("/capture-profiles")
async def list_capture_profiles(
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)], response: Response
) -> list[dict[str, Any]]:
    """List item types and their native default-template references."""
    response.headers["Cache-Control"] = "no-store"
    return [entry for entry in await gateway.list_entity_types() if entry.get("isLocation") is False]


@router.get("/capture-profiles/{entity_type_id}")
async def get_capture_profile(
    entity_type_id: UUID,
    gateway: Annotated[HomeboxGateway, Depends(get_gateway)],
    response: Response,
    template_id: UUID | None = None,
) -> dict[str, Any]:
    """Resolve only a current, collection-visible type and its default schema."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return await gateway.get_capture_profile(
            str(entity_type_id), str(template_id) if template_id is not None else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
