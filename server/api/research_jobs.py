"""Scoped saved-item research jobs and explicitly confirmed native field patches."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from homebox_companion.core import persistent_settings
from homebox_companion.homebox.relationships import item_update_payload
from homebox_companion.research import ProductIdentity, ResearchResult
from server.api.research import Gateway, fingerprint, proposals, provider, scope
from server.services.research_jobs import ResearchJobs

router = APIRouter(prefix="/research/jobs")


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    identity: ProductIdentity
    idempotency_key: str = Field(min_length=1, max_length=100)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected: list[int] = Field(min_length=1, max_length=8)


def service(request):
    if not hasattr(request.app.state, "research_jobs"):
        path = getattr(
            request.app.state, "research_db_path", persistent_settings.SETTINGS_FILE.parent / "research.sqlite3"
        )
        try:
            request.app.state.research_jobs = ResearchJobs(path)
        except RuntimeError:
            raise HTTPException(503, "Research worker unavailable; use a single application worker") from None
    return request.app.state.research_jobs


def job_scope(request, gateway):
    return fingerprint([request.app.state.settings.api_url, gateway.access.identity_scope, gateway.access.group_id])


def values(item):
    return {f["name"]: f.get("textValue", "") or "" for f in item.get("fields", [])}


def policy_hash(provider):
    profile = getattr(provider, "profile", None)
    return fingerprint(
        {
            "schema": 1,
            "tool_calls": 1,
            "output_tokens": 2400,
            "provider": "openai-responses",
            "model": getattr(profile, "model", None),
            "profile": getattr(profile, "name", None),
            "endpoint": "https://api.openai.com/v1",
        }
    )


async def item_profile(gateway, item_id):
    item = await gateway.get_item(item_id)
    if item.get("id") != item_id:
        raise HTTPException(404, "Item unavailable")
    type_id = (item.get("entityType") or {}).get("id") or item.get("entityTypeId")
    if not type_id:
        raise HTTPException(400, "Item has no native type")
    profile = await gateway.get_capture_profile(type_id)
    proposals(ResearchResult(status="no_results"), profile, values(item))
    if not profile.get("template"):
        raise HTTPException(400, "A native TEXT template is required")
    return item, profile


def public(row):
    return {k: row[k] for k in ("id", "item", "state", "result", "created", "expires")}


async def owned(id_, request, gateway):
    await scope(gateway)
    row = service(request).db.get(str(id_), job_scope(request, gateway))
    if row is None:
        raise HTTPException(404, "Job unavailable")
    # Current item rights, not just possession of the job ID, authorize every read/write.
    item = await gateway.get_item(row["item"])
    if item.get("id") != row["item"]:
        raise HTTPException(404, "Item unavailable")
    return row


@router.post("", status_code=202)
async def enqueue(body: JobInput, request: Request, gateway: Gateway):
    await scope(gateway)
    p = provider(request)
    if not p.configured:
        raise HTTPException(503, "Research disabled or unconfigured")
    item, profile = await item_profile(gateway, body.item_id)
    payload = {
        "identity": body.identity.model_dump(),
        "item_hash": fingerprint(item),
        "profile_hash": fingerprint(profile),
        "policy_hash": policy_hash(p),
    }
    jobs = service(request)
    try:
        row = jobs.db.enqueue(job_scope(request, gateway), body.item_id, body.idempotency_key, payload)
    except ValueError as exc:
        raise HTTPException(429 if "Queue" in str(exc) else 409, str(exc)) from None
    jobs.bind(row, gateway, lambda: provider(request))
    return public(row)


@router.get("")
async def list_jobs(request: Request, gateway: Gateway):
    await scope(gateway)
    rows = service(request).db.list(job_scope(request, gateway))
    output = []
    for row in rows:
        try:
            await owned(row["id"], request, gateway)
        except Exception:
            continue
        output.append(public(row))
    return output


@router.get("/{id_}")
async def get_job(id_: UUID, request: Request, gateway: Gateway):
    return public(await owned(id_, request, gateway))


@router.post("/{id_}/cancel")
async def cancel(id_: UUID, request: Request, gateway: Gateway):
    jobs = service(request)
    async with jobs.apply_lock:
        row = await owned(id_, request, gateway)
        if row["state"] not in {"queued", "running", "dispatching", "needs_auth", "matched"}:
            raise HTTPException(409, "Terminal jobs cannot be cancelled")
        jobs.db.cancel(row["id"], row["scope"])
    return public(jobs.db.get(row["id"], row["scope"]))


@router.post("/{id_}/resume")
async def resume(id_: UUID, request: Request, gateway: Gateway):
    row = await owned(id_, request, gateway)
    jobs = service(request)
    if not jobs.db.resume(row["id"], row["scope"]):
        raise HTTPException(409, "Only needs_auth can resume; unknown outcomes require a new explicit paid request")
    jobs.bind(jobs.db.get(row["id"], row["scope"]), gateway, lambda: provider(request))
    return public(jobs.db.get(row["id"], row["scope"]))


@router.post("/{id_}/apply")
async def apply(id_: UUID, body: Selection, request: Request, gateway: Gateway):
    jobs = service(request)
    async with jobs.apply_lock:
        row = await owned(id_, request, gateway)
        if row["state"] != "matched" or not row["result"]:
            raise HTTPException(409, "Job is not reviewable")
        item, profile = await item_profile(gateway, row["item"])
        if fingerprint(item) != row["payload"]["item_hash"] or fingerprint(profile) != row["payload"]["profile_hash"]:
            raise HTTPException(409, "Item/template changed; no fields written")
        proposed = row["result"]["proposals"]
        if any(i < 0 or i >= len(proposed) for i in body.selected):
            raise HTTPException(400, "Invalid selection")
        fields = [dict(f) for f in item.get("fields", [])]
        for i in set(body.selected):
            matches = [f for f in fields if f["name"] == proposed[i]["name"] and f.get("type") == "text"]
            if len(matches) != 1:
                raise HTTPException(409, "Native field identity changed")
            matches[0]["textValue"] = proposed[i]["value"]
        if not jobs.db.claim_apply(row["id"], row["scope"]):
            raise HTTPException(409, "Already applied or cancelled")
        try:
            await gateway.update_item(row["item"], {**item_update_payload(item), "fields": fields})
            readback = await gateway.get_item(row["item"])
            if any(values(readback).get(proposed[i]["name"]) != proposed[i]["value"] for i in body.selected):
                raise RuntimeError("Readback mismatch")
            jobs.db.finish(row["id"], "applied", row["result"])
            return {"state": "applied", "item_id": row["item"], "verified_fields": values(readback)}
        except BaseException:
            jobs.db.finish(row["id"], "apply_unknown", row["result"])
            raise HTTPException(409, "Write outcome unknown; inspect Homebox before any retry") from None
