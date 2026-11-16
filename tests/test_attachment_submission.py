"""Production submission -> ASGI -> native Homebox, plus deterministic false-201 injection."""

import asyncio
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from pydantic import SecretStr

from homebox_companion.homebox.auth import HomeboxAccess, HomeboxAuthKind
from homebox_companion.homebox.client import HomeboxClient, HomeboxGateway
from server.api.items import router
from server.dependencies import get_gateway

ROOT = Path(__file__).resolve().parents[1]


def photo():
    output = io.BytesIO()
    Image.new("RGB", (320, 240), (125, 25, 60)).save(output, "JPEG")
    return output.getvalue()


async def submission_bridge(client, token, group, type_id, expected=None):
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(image_quality_params=(1280, 80), max_upload_size_bytes=2000000)
    gateway = HomeboxGateway(client, HomeboxAccess(SecretStr(token), HomeboxAuthKind.LEGACY, "test", group))
    app.dependency_overrides[get_gateway] = lambda: gateway
    node = shutil.which("node")
    assert node
    process = await asyncio.create_subprocess_exec(
        node,
        str(ROOT / "frontend/tests/attachment-submission-probe.js"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(
        (
            json.dumps({"photo": base64.b64encode(photo()).decode(), "type": type_id, "expected": expected}) + "\n"
        ).encode()
    )
    await process.stdin.drain()
    evidence = {"responses": []}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://companion.test") as api:
            async with asyncio.timeout(90):
                while line := await process.stdout.readline():
                    event = json.loads(line)
                    if "done" in event:
                        evidence.update(event["done"])
                        continue
                    if "create" in event:
                        response = await api.post("/items", json=event["create"])
                    else:
                        upload = event["upload"]
                        options = upload["options"]
                        response = await api.post(
                            f"/items/{upload['entity']}/attachments",
                            files={"file": (upload["filename"], base64.b64decode(upload["content"]), "image/jpeg")},
                            data={
                                "attempt_id": options["attemptId"],
                                "slot": options["slot"],
                                "original_filename": options["originalFilename"],
                            },
                        )
                    evidence["responses"].append({"status": response.status_code, "body": response.json()})
                    process.stdin.write(
                        (json.dumps({"status": response.status_code, "body": response.json()}) + "\n").encode()
                    )
                    await process.stdin.drain()
                await process.wait()
        assert process.returncode == 0, (await process.stderr.read()).decode()[-3000:]
        return evidence
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_false_201_asgi_to_production_submission():
    entity = "430e4d47-2b34-4104-bb84-ea19605a372a"
    type_id = "00000000-0000-4000-8000-000000000010"
    detail = json.loads((ROOT / "tests/fixtures/attachment-false-201.json").read_text())["response"]
    posts = []

    def handle(request):
        path = request.url.path
        assert request.headers.get("X-Tenant") == "synthetic-group"
        if request.method == "POST":
            posts.append(path)
        assert request.method != "DELETE"
        if path.endswith("/entity-types"):
            return httpx.Response(200, json=[{"id": type_id, "isLocation": False, "name": "Item"}])
        if path.endswith("/tags"):
            return httpx.Response(200, json=[])
        if path.endswith("/actions/ensure-asset-ids"):
            return httpx.Response(200, json={"completed": 0})
        return httpx.Response(201 if request.method == "POST" else 200, json=detail)

    async with HomeboxClient(base_url="http://native.test", transport=httpx.MockTransport(handle)) as native:
        result = await submission_bridge(native, "synthetic", "synthetic-group", type_id, "partial_success")
    assert posts.count(f"/entities/{entity}/attachments") == 1
    assert result["snapshot"]["createdItemIds"] == {"0": entity}
    assert result["snapshot"]["photoAttempts"]["0"][0]["state"] == "unconfirmed"
    assert result["snapshot"]["photoAttempts"]["0"][1]["state"] == "not_sent"
    assert result["responses"][-1]["body"]["detail"]["code"] == "ATTACHMENT_PERSISTENCE_UNCONFIRMED"


@pytest.mark.live
@pytest.mark.asyncio
async def test_native_guard_receipts_and_false_201(homebox_test_account, tmp_path):
    account = homebox_test_account
    artifacts = Path(os.environ.get("HBC_SMOKE_ARTIFACT_DIR", str(tmp_path))) / "attachment-guard"
    artifacts.mkdir(parents=True, exist_ok=False)
    try:
        async with httpx.AsyncClient(
            base_url=account.api_url, headers={"Authorization": f"Bearer {account.control_token}"}, trust_env=False
        ) as control:
            groups_response = await control.get("/groups/all")
            groups_response.raise_for_status()
            group = groups_response.json()[0]["id"]
            control.headers["X-Tenant"] = group
            types = (await control.get("/entity-types")).json()
            type_id = next(row["id"] for row in types if not row["isLocation"])
            # Each native write is dispatched once. Fault cases return the same detail
            # with 201, precisely the confirmed upstream failure contract, without
            # pretending that an actual native DB lock occurred in this test.
            for failure_slot in [None, 0, 1]:
                wire = []
                count = 0

                class Wire(httpx.AsyncHTTPTransport):
                    async def handle_async_request(self, request, *, failure_slot=failure_slot, wire=wire):
                        nonlocal count
                        assert request.headers["X-Tenant"] == group
                        if request.method == "POST" and request.url.path.endswith("/attachments"):
                            slot = count
                            count += 1
                            if slot == failure_slot:
                                unchanged = await control.get(
                                    request.url.path.removeprefix("/api/v1").removesuffix("/attachments")
                                )
                                wire.append(
                                    {
                                        "method": "POST",
                                        "path": request.url.path,
                                        "status": 201,
                                        "injected": True,
                                        "body": unchanged.json(),
                                    }
                                )
                                return httpx.Response(201, json=unchanged.json())
                        response = await super().handle_async_request(request)
                        wire.append(
                            {"method": request.method, "path": request.url.path, "status": response.status_code}
                        )
                        return response

                async with HomeboxClient(base_url=account.api_url, transport=Wire()) as native:
                    result = await submission_bridge(
                        native,
                        account.control_token,
                        group,
                        type_id,
                        None if failure_slot is None else "partial_success",
                    )
                result["wire"] = wire
                (artifacts / f"case-{failure_slot}.json").write_text(json.dumps(result, indent=2))
                assert not any(row["method"] == "DELETE" for row in wire)
                entity = result["snapshot"]["createdItemIds"]["0"]
                detail_response = await control.get(f"/entities/{entity}")
                detail_response.raise_for_status()
                detail = detail_response.json()
                (artifacts / f"entity-{failure_slot}.json").write_text(json.dumps(detail, indent=2))
                attempts = result["snapshot"]["photoAttempts"]["0"]
                for attempt in attempts:
                    if attempt["state"] != "verified":
                        continue
                    receipt = attempt["receipt"]
                    assert receipt["attachment_id"] in {row["id"] for row in detail["attachments"]}
                    downloaded = await control.get(f"/entities/{entity}/attachments/{receipt['attachment_id']}")
                    downloaded.raise_for_status()
                    assert hashlib.sha256(downloaded.content).hexdigest() == receipt["sha256"]
                    assert len(downloaded.content) == receipt["byte_length"]
                    (artifacts / f"original-{failure_slot}-{attempt['slot']}.jpg").write_bytes(downloaded.content)
                if failure_slot is None:
                    # An upstream intermittent failure must stay visible, not be retried to green.
                    assert result["snapshot"]["itemStatuses"]["0"] == "success", (
                        "Native uncertainty retained; inspect case-None evidence"
                    )
                    assert len({attempt["receipt"]["attachment_id"] for attempt in attempts}) == 2
                    assert len({attempt["receipt"]["title"] for attempt in attempts}) == 2
                else:
                    assert count == failure_slot + 1
                    assert attempts[failure_slot]["state"] == "unconfirmed"
    finally:
        logs = subprocess.run(["docker", "logs", account.server.name], capture_output=True, text=True, timeout=15)
        (artifacts / "homebox.log").write_text(logs.stdout + logs.stderr)
