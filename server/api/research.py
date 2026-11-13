"""Optional research review. No automatic Homebox writes; proposals expire."""

import hashlib
import json
import time
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from homebox_companion import HomeboxGateway
from homebox_companion.core.persistent_settings import get_settings
from homebox_companion.research import OpenAIResponsesResearchProvider, ProductIdentity, ResearchPolicy
from server.dependencies import get_verified_gateway

router = APIRouter(prefix="/research")
Gateway = Annotated[HomeboxGateway, Depends(get_verified_gateway)]

# Deliberately small server-owned semantic vocabulary, not arbitrary model targets.
NATIVE_FIELDS = {
    "manufacturer": {"manufacturer", "hersteller"},
    "part_number": {"part number", "part number (oem)", "teilenummer"},
    "model_number": {"model number", "modellnummer"},
    "specifications": {"specifications", "technical specifications", "technische daten"},
}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(min_length=1, max_length=100)
    entity_type_id: UUID
    template_id: UUID
    identity: ProductIdentity
    current_values: dict[str, str] = Field(max_length=100)


class Adoption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(min_length=1, max_length=100)
    selected: list[int] = Field(max_length=8)
    current_values: dict[str, str] = Field(max_length=100)


def provider(request: Request):
    injected = getattr(request.app.state, "research_provider", None)
    if injected is not None:
        return injected
    config = get_settings()
    profile = next((p for p in config.llm_profiles if p.name == config.research_profile_name), None)
    return OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=config.research_enabled, profile_name=config.research_profile_name), profile
    )


async def scope(gateway: HomeboxGateway) -> tuple[str, str]:
    group = gateway.access.group_id
    if not group or group not in {g["id"] for g in await gateway.list_groups()}:
        raise HTTPException(404, "Collection unavailable")
    return gateway.access.identity_scope, group


def records(request: Request) -> dict:
    if not hasattr(request.app.state, "research_reviews"):
        request.app.state.research_reviews = {}
    reviews = request.app.state.research_reviews
    for key in list(reviews):
        if reviews[key]["expires"] <= time.monotonic():
            del reviews[key]
    return reviews


def proposals(result, profile, current):
    fields = (profile.get("template") or {}).get("fields", [])
    if any(f.get("type") != "text" for f in fields) or len({f["name"] for f in fields}) != len(fields):
        raise HTTPException(400, "Research requires an unambiguous native TEXT template")
    output = []
    if result.status != "matched":
        return output
    for claim in result.claims:
        matches = [f for f in fields if f["name"].casefold() in NATIVE_FIELDS[claim.field]]
        if len(matches) == 1:
            field = matches[0]
            output.append(
                {
                    "name": field["name"],
                    "field_id": field.get("id"),
                    "current": current.get(field["name"], ""),
                    "value": claim.value,
                    "source_urls": claim.source_urls,
                    "evidence": claim.evidence,
                }
            )
    return output


@router.get("/capabilities")
async def capabilities(request: Request, gateway: Gateway):
    await scope(gateway)
    return {
        "enabled": provider(request).configured,
        "provider": "openai-responses",
        "max_tool_calls": 1,
        "notice": "Optional paid research. Sources require review. Capture/save does not depend on research.",
    }


@router.post("/lookups")
async def lookup(body: Lookup, request: Request, gateway: Gateway):
    owner = await scope(gateway)
    p = provider(request)
    if not p.configured:
        raise HTTPException(503, "Research is disabled or not configured")
    reviews = records(request)
    if len(reviews) >= 100 or sum(r["scope"] == owner for r in reviews.values()) >= 10:
        raise HTTPException(429, "Research review limit reached; retry after expiry")
    profile = await gateway.get_capture_profile(str(body.entity_type_id), str(body.template_id))
    # Validate template before a paid call, even when no result will match.
    from homebox_companion.research import ResearchResult

    proposals(ResearchResult(status="no_results"), profile, body.current_values)
    id_ = str(uuid4())
    reviews[id_] = {"scope": owner, "expires": time.monotonic() + 900, "pending": True}
    try:
        result = await p.research(body.identity)
        mapped = proposals(result, profile, body.current_values)
        reviews[id_] = {
            "scope": owner,
            "expires": time.monotonic() + 900,
            "body": body,
            "profile_hash": fingerprint(profile),
            "proposals": mapped,
        }
        return {"id": id_, "draft_id": body.draft_id, "revision": body.revision, "result": result, "proposals": mapped}
    except BaseException:
        reviews.pop(id_, None)
        raise


@router.post("/lookups/{lookup_id}/apply")
async def adopt(lookup_id: UUID, body: Adoption, request: Request, gateway: Gateway):
    owner = await scope(gateway)
    review = records(request).get(str(lookup_id))
    if not review or review["scope"] != owner or review.get("pending"):
        raise HTTPException(404, "Review unavailable")
    original = review["body"]
    profile = await gateway.get_capture_profile(str(original.entity_type_id), str(original.template_id))
    if (
        body.draft_id != original.draft_id
        or body.revision != original.revision
        or body.current_values != original.current_values
        or fingerprint(profile) != review["profile_hash"]
    ):
        raise HTTPException(409, "Review is stale; compare current values again")
    if any(index < 0 or index >= len(review["proposals"]) for index in body.selected):
        raise HTTPException(400, "Invalid proposal selection")
    return {
        "draft_id": body.draft_id,
        "revision": body.revision,
        "patch": {review["proposals"][i]["name"]: review["proposals"][i]["value"] for i in set(body.selected)},
    }
