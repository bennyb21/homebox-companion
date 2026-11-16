"""Transport-level upload observation: HTTP 201 is not a receipt."""

import json
from pathlib import Path

import httpx
import pytest

from homebox_companion.homebox.client import HomeboxClient

ENTITY = "430e4d47-2b34-4104-bb84-ea19605a372a"


@pytest.mark.asyncio
async def test_false_201_unchanged_entity_is_not_success():
    calls = []
    fixture = json.loads((Path(__file__).parent / "fixtures/attachment-false-201.json").read_text())

    def handle(request):
        calls.append(request.method)
        body = fixture["response"] if request.method == "POST" else fixture["before"]
        return httpx.Response(201 if request.method == "POST" else 200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = HomeboxClient(base_url="http://native.test/api/v1", client=http)
        with pytest.raises(Exception, match="ATTACHMENT_PERSISTENCE_UNCONFIRMED"):
            await client.upload_attachment("synthetic", ENTITY, b"photo", "photo.jpg")
    assert calls.count("POST") == 1
    assert "DELETE" not in calls


@pytest.mark.asyncio
async def test_route_preserves_attempt_and_hashes_actual_compressed_bytes():
    import hashlib
    import io
    from types import SimpleNamespace

    from fastapi import FastAPI
    from PIL import Image
    from pydantic import SecretStr

    from homebox_companion.homebox.auth import HomeboxAccess, HomeboxAuthKind
    from homebox_companion.homebox.client import HomeboxGateway
    from server.api.items import router
    from server.dependencies import get_gateway

    attempt = "11111111-1111-4111-8111-111111111111"
    attachment = "22222222-2222-4222-8222-222222222222"
    rows, sent = [], []

    def handle(request):
        assert request.headers["X-Tenant"] == "group-a"
        if request.method == "POST":
            from email.parser import BytesParser
            from email.policy import default

            message = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
            )
            parts = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
            sent.append(parts["file"].get_payload(decode=True))
            rows.append(
                {"id": attachment, "title": parts["name"].get_content(), "type": "photo", "mimeType": "image/jpeg"}
            )
        if request.url.path.endswith(attachment):
            return httpx.Response(200, content=sent[0], headers={"content-type": "image/jpeg"})
        return httpx.Response(201 if request.method == "POST" else 200, json={"id": ENTITY, "attachments": rows})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        gateway = HomeboxGateway(
            HomeboxClient(base_url="http://native.test/api/v1", client=http),
            HomeboxAccess(
                credential=SecretStr("synthetic"),
                kind=HomeboxAuthKind.LEGACY,
                identity_scope="synthetic",
                group_id="group-a",
            ),
        )
        app = FastAPI()
        app.include_router(router)
        app.state.settings = SimpleNamespace(
            image_quality_params=(100, 80), max_upload_size_mb=20, max_upload_size_bytes=20 * 1024 * 1024
        )
        app.dependency_overrides[get_gateway] = lambda: gateway
        image = io.BytesIO()
        Image.new("RGB", (200, 200), "red").save(image, "PNG")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://companion.test"
        ) as browser:
            response = await browser.post(
                f"/items/{ENTITY}/attachments",
                files={"file": ("original.png", image.getvalue(), "image/png")},
                data={"attempt_id": attempt, "slot": "2", "original_filename": "retained.png"},
            )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["attempt_id"] == attempt
        assert receipt["slot"] == "2"
        assert receipt["original_filename"] == "retained.png"
        assert receipt["sha256"] == hashlib.sha256(sent[0]).hexdigest()
        assert receipt["byte_length"] == len(sent[0])
        assert sent[0] != image.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "happy",
        "old-same",
        "other-writer",
        "reordered",
        "reused-marker",
        "duplicate-id-before",
        "wrong-entity-before",
        "missing-list",
        "bad-list",
        "preflight-timeout",
        "response-lost",
        "post-commit-error",
        "readback-missing",
        "readback-timeout",
        "duplicate-marker",
        "wrong-type",
        "duplicate-id-after",
        "wrong-entity-after",
        "blob-404",
        "truncated",
        "oversized",
        "wrong-hash",
        "external-path",
        "redirect",
        "wrong-mime",
        "final-missing",
    ],
)
async def test_observation_fault_matrix(fault):
    import hashlib

    from homebox_companion.homebox.attachment_verification import AttachmentVerificationError

    attempt = "11111111-1111-4111-8111-111111111111"
    new_id = "22222222-2222-4222-8222-222222222222"
    old_id = "33333333-3333-4333-8333-333333333333"
    title = f"same__hbc_{attempt}.jpg"
    content = b"actual transmitted bytes"
    old = {"id": old_id, "title": "same.jpg", "type": "photo", "mimeType": "image/jpeg"}
    new = {**old, "id": new_id, "title": title}
    calls, post, gets = [], False, 0

    def handle(request):
        nonlocal post, gets
        calls.append((request.method, str(request.url)))
        assert request.url.host == "native.test"
        assert request.headers["X-Tenant"] == "group-a"
        if request.method == "POST":
            post = True
            assert title.encode() in request.content
            assert b'name="primary"' not in request.content
            if fault == "response-lost":
                raise httpx.ReadTimeout("lost")
            if fault == "post-commit-error":
                return httpx.Response(500)
            if fault == "redirect":
                return httpx.Response(307, headers={"location": "https://external.test"})
        elif request.url.path.endswith(new_id):
            data = content
            if fault == "blob-404":
                return httpx.Response(404)
            if fault == "truncated":
                data = data[:-1]
            if fault == "oversized":
                data += b"x" * 100000
            if fault == "wrong-hash":
                data = b"x" * len(content)
            return httpx.Response(200, content=data, headers={"content-type": "image/jpeg"})
        else:
            gets += 1
        if not post:
            if fault == "preflight-timeout":
                raise httpx.ReadTimeout("not sent")
            if fault == "missing-list":
                return httpx.Response(200, json={"id": ENTITY})
            if fault == "bad-list":
                return httpx.Response(200, json={"id": ENTITY, "attachments": {}})
            rows = [old]
            if fault == "reused-marker":
                rows = [new]
            if fault == "duplicate-id-before":
                rows = [old, old]
            return httpx.Response(
                200, json={"id": old_id if fault == "wrong-entity-before" else ENTITY, "attachments": rows}
            )
        rows = [old, new]
        if fault == "old-same":
            rows = [old]
        if fault == "other-writer":
            rows = [old, {**new, "title": "same.jpg"}]
        if fault == "reordered":
            rows = [new, old, {**old, "id": attempt, "type": "thumbnail"}]
        if fault == "duplicate-marker":
            rows = [new, {**new, "id": attempt}]
        if fault == "duplicate-id-after":
            rows = [old, new, new]
        if fault == "wrong-type":
            rows = [old, {**new, "type": "thumbnail"}]
        if fault == "wrong-mime":
            rows = [old, {**new, "mimeType": "text/uri-list"}]
        if fault == "external-path":
            rows = [old, {**new, "path": "https://external.test/photo"}]
        if request.method == "GET":
            if fault == "readback-timeout":
                raise httpx.ReadTimeout("unconfirmed")
            if fault == "readback-missing" or (fault == "final-missing" and gets == 3):
                rows = [old]
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json={"id": old_id if fault == "wrong-entity-after" else ENTITY, "attachments": rows},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = HomeboxClient(base_url="http://native.test/api/v1", client=http).for_group("group-a")
        if fault in {"happy", "reordered"}:
            receipt = await client.upload_attachment_typed(
                "synthetic", ENTITY, content, "same.jpg", attempt_id=attempt, slot="0"
            )
            assert receipt.attachment_id == new_id
            assert receipt.entity_id == ENTITY
            assert receipt.sha256 == hashlib.sha256(content).hexdigest()
            assert receipt.byte_length == len(content)
        else:
            with pytest.raises(AttachmentVerificationError) as error:
                await client.upload_attachment("synthetic", ENTITY, content, "same.jpg", attempt_id=attempt, slot="0")
            assert error.value.dispatched == post
    assert sum(method == "POST" for method, _ in calls) == int(post)
    assert not any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_legacy_manual_pdf_upload_still_requires_a_real_attachment_receipt():
    from email.parser import BytesParser
    from email.policy import default

    rows = []
    content = b"%PDF-1.4 synthetic contract bytes"
    attachment = "22222222-2222-4222-8222-222222222222"

    def handle(request):
        if request.method == "POST":
            message = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
            )
            fields = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
            assert fields["type"].get_content() == "manual"
            rows.append(
                {
                    "id": attachment,
                    "type": "manual",
                    "mimeType": "application/pdf",
                    "title": fields["name"].get_content(),
                }
            )
        if request.url.path.endswith(attachment):
            return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})
        return httpx.Response(201 if request.method == "POST" else 200, json={"id": ENTITY, "attachments": rows})

    async with HomeboxClient(base_url="http://native.test", transport=httpx.MockTransport(handle)) as client:
        receipt = await client.upload_attachment_typed(
            "synthetic", ENTITY, content, "manual.pdf", "application/pdf", "manual"
        )
    assert receipt.attachment_id == attachment
    assert receipt.entity_id == ENTITY
    assert receipt.title.endswith(".pdf")
