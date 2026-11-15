"""Observed attachment persistence, not atomic delivery or future durability."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel


class AttachmentReceipt(BaseModel):
    verified: Literal[True] = True
    entity_id: str
    attachment_id: str
    attempt_id: str
    slot: str
    original_filename: str
    title: str
    mime_type: str
    byte_length: int
    sha256: str


class AttachmentVerificationError(RuntimeError):
    def __init__(self, *, dispatched: bool) -> None:
        self.dispatched = dispatched
        self.code = "ATTACHMENT_PERSISTENCE_UNCONFIRMED" if dispatched else "ATTACHMENT_NOT_DISPATCHED"
        super().__init__(self.code)


def uuid_value(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid UUID")
    return value


def attachment_rows(raw: Any, entity_id: str) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("id") != entity_id or "attachments" not in raw:
        raise ValueError("Wrong entity or missing attachment list")
    rows = raw["attachments"]
    if rows is None:  # Native empty-list representation.
        return []
    if not isinstance(rows, list):
        raise ValueError("Invalid attachment list")
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid attachment row")
        identity = uuid_value(row.get("id"))
        if identity in ids or not all(isinstance(row.get(k), str) for k in ("title", "type", "mimeType")):
            raise ValueError("Duplicate ID or malformed attachment")
        ids.add(identity)
    return rows


def correlated_title(filename: str, attempt_id: str, mime_type: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", filename.rsplit(".", 1)[0])[:64] or "photo"
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(mime_type)
    if extension is None:
        # Preserve non-photo library/MCP uploads (manuals, warranties, etc.).
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
        if not re.fullmatch(r"[a-z0-9]{1,8}", extension):
            extension = "bin"
    if not re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", mime_type) or mime_type == "text/uri-list":
        raise ValueError("Unsupported attachment MIME")
    return f"{stem}__hbc_{attempt_id}.{extension}"


async def upload_verified(
    http: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    entity_id: str,
    content: bytes,
    filename: str,
    mime_type: str,
    attachment_type: str,
    attempt_id: str | None,
    slot: str,
) -> AttachmentReceipt:
    dispatched = False
    try:
        uuid_value(entity_id)
        attempt_id = uuid_value(attempt_id) if attempt_id is not None else str(uuid4())
        if not re.fullmatch(r"[a-z]{1,32}", attachment_type) or not content or not slot or len(slot) > 128:
            raise ValueError("Invalid photo attempt")
        title = correlated_title(filename, attempt_id, mime_type)
        url = f"{base_url}/entities/{entity_id}"
        # Freeze credential/group headers once; never follow server-supplied URLs.
        headers = {**headers, "Cache-Control": "no-cache"}

        async def detail() -> list[dict[str, Any]]:
            response = await http.get(url, headers=headers, follow_redirects=False)
            response.raise_for_status()
            return attachment_rows(response.json(), entity_id)

        before = await detail()
        marker = f"__hbc_{attempt_id}."
        if any(marker in row["title"] for row in before):
            raise ValueError("Attempt marker already exists")
        before_ids = {row["id"] for row in before}
        dispatched = True
        response = await http.post(
            f"{url}/attachments",
            headers=headers,
            files={"file": (title, content, mime_type)},
            data={"type": attachment_type, "name": title},
            follow_redirects=False,
        )
        response.raise_for_status()

        def candidate(rows: list[dict[str, Any]]) -> str:
            matches = [row for row in rows if marker in row["title"]]
            if len(matches) != 1:
                raise ValueError("No unique attempt attachment")
            row = matches[0]
            if isinstance(row.get("path"), str) and (":" in row["path"] or row["path"].startswith("//")):
                raise ValueError("External attachment path")
            if (
                row["title"] != title
                or row["type"] != attachment_type
                or row["mimeType"] != mime_type
                or row["id"] in before_ids
            ):
                raise ValueError("Attachment is not a new matching photo")
            return row["id"]

        attachment_id = candidate(attachment_rows(response.json(), entity_id))
        if candidate(await detail()) != attachment_id:
            raise ValueError("Independent membership mismatch")
        digest = hashlib.sha256()
        size = 0
        async with http.stream(
            "GET", f"{url}/attachments/{attachment_id}", headers=headers, follow_redirects=False
        ) as blob:
            blob.raise_for_status()
            if blob.headers.get("content-type", "").split(";", 1)[0] != mime_type:
                raise ValueError("Original MIME mismatch")
            if int(blob.headers.get("content-length", "0")) > len(content) + 1024:
                raise ValueError("Oversized original")
            async for chunk in blob.aiter_bytes(chunk_size=65536):
                size += len(chunk)
                if size > len(content) + 1024:
                    raise ValueError("Oversized original")
                digest.update(chunk)
        expected_hash = hashlib.sha256(content).hexdigest()
        if size != len(content) or digest.hexdigest() != expected_hash:
            raise ValueError("Original bytes mismatch")
        if candidate(await detail()) != attachment_id:
            raise ValueError("Attachment no longer observed")
        return AttachmentReceipt(
            entity_id=entity_id,
            attachment_id=attachment_id,
            attempt_id=attempt_id,
            slot=slot,
            original_filename=filename,
            title=title,
            mime_type=mime_type,
            byte_length=size,
            sha256=expected_hash,
        )
    except Exception as exc:
        raise AttachmentVerificationError(dispatched=dispatched) from exc
