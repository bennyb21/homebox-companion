"""Real browser/native Homebox acceptance with a synthetic HTTP vision provider."""

from __future__ import annotations

import base64
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from conftest import _find_free_port
from image_harness import start_server
from PIL import Image

from homebox_companion.ai.images import compress_image_for_upload, optimize_image_for_vision

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.live


@pytest.fixture
def vision_wire():
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "body": body})
            content = {"items": [{"name": "Synthetic native part", "quantity": 1, "partNumber": "0007-SYN"}]}
            response = json.dumps(
                {
                    "id": "synthetic-vision",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": json.dumps(content)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", requests
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize(
    "per_photo,quality", [(False, "low"), (True, "high")], ids=["three-views-one-item", "two-photos-two-items"]
)
def test_grouped_native_capture(homebox_test_account, homebox_key_factory, vision_wire, tmp_path, per_photo, quality):
    node = shutil.which("node")
    assert node, "Node is required for browser acceptance"
    account = homebox_test_account
    key = homebox_key_factory()
    artifact_root = Path(os.environ.get("HBC_SMOKE_ARTIFACT_DIR", str(tmp_path)))
    artifacts = artifact_root / ("per-photo" if per_photo else "multi-view")
    artifacts.mkdir(parents=True, exist_ok=True)
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HBC_", "OPENAI_", "ANTHROPIC_"))}
    env.update(
        HBC_HOMEBOX_URL=account.server.base_url,
        HBC_HOMEBOX_API_KEY=key.token,
        HBC_LLM_API_KEY="synthetic-only-no-real-provider",
        HBC_LLM_MODEL="gpt-5.6-luna",
        HBC_LLM_API_BASE=vision_wire[0],
        HBC_DISABLE_UPDATE_CHECK="true",
        HBC_IMAGE_QUALITY=quality,
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "src")]),
    )
    headers = {"Authorization": f"Bearer {account.control_token}"}
    with httpx.Client(base_url=account.api_url + "/", headers=headers, trust_env=False, timeout=20) as control:

        def post(path, data):
            response = control.post(path, json=data)
            response.raise_for_status()
            return response.json()

        types = control.get("entity-types")
        types.raise_for_status()
        location_type = next(row["id"] for row in types.json() if row["isLocation"])
        location = post("entities", {"name": "Group smoke storage", "entityTypeId": location_type})
        template = post(
            "templates",
            {
                "name": "Group text template",
                "description": "Synthetic only",
                "defaultQuantity": 1,
                "fields": [
                    {"name": "Part number", "type": "text", "textValue": ""},
                    {"name": "Condition", "type": "text", "textValue": "Keep default"},
                ],
            },
        )
        native = post(
            "entity-types", {"name": "Group native part", "isLocation": False, "defaultTemplateId": template["id"]}
        )
        with (artifacts / "server.log").open("w") as log:
            process = start_server(Path(__file__).resolve(), port, ROOT / "frontend/build", tmp_path, env, log)
            try:
                deadline = time.monotonic() + 40
                with httpx.Client(trust_env=False, timeout=2) as probe:
                    while time.monotonic() < deadline:
                        assert process.poll() is None, f"Companion exited; see {artifacts}"
                        try:
                            if probe.get(url + "/api/version").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.2)
                    else:
                        pytest.fail("Companion did not become ready")
                result = subprocess.run(
                    [
                        node,
                        str(ROOT / "frontend/node_modules/@playwright/test/cli.js"),
                        "test",
                        "--config=tests/fullstack/playwright.config.ts",
                        "capture-groups.spec.ts",
                    ],
                    cwd=ROOT / "frontend",
                    env={
                        **os.environ,
                        "HBC_SMOKE_URL": url,
                        "HBC_GROUP_SMOKE": "1",
                        "HBC_PER_PHOTO": "1" if per_photo else "0",
                        "HBC_SMOKE_ARTIFACT_DIR": str(artifacts),
                    },
                    timeout=120,
                    check=False,
                )
                assert result.returncode == 0
                count = 2 if per_photo else 3
                expected_items = 2 if per_photo else 1
                requests = vision_wire[1]
                (artifacts / "provider-wire.json").write_text(json.dumps(requests, indent=2))
                assert len(requests) == expected_items, "Back, undo and navigation must not repeat inference"
                actual_vision = []
                for request in requests:
                    assert request["path"] == "/v1/chat/completions"
                    images = [
                        part["image_url"]["url"]
                        for message in request["body"]["messages"]
                        if isinstance(message["content"], list)
                        for part in message["content"]
                        if part["type"] == "image_url"
                    ]
                    assert len(images) == (1 if per_photo else 3)
                    for uri in images:
                        assert uri.startswith("data:image/jpeg;base64,")
                        data = base64.b64decode(uri.split(",", 1)[1])
                        assert Image.open(io.BytesIO(data)).size == (2048, 1024)
                        actual_vision.append(hashlib.sha256(data).hexdigest())
                sources = [(artifacts / f"source-{i}.png").read_bytes() for i in range(count)]
                expected_vision = [
                    hashlib.sha256(optimize_image_for_vision(source)[0]).hexdigest() for source in sources
                ]
                assert sorted(actual_vision) == sorted(expected_vision), (
                    "Every photo reaches the provider at JPEG85, independently of storage quality"
                )
                # Existing contract: detection returns storage-compressed previews;
                # submission prefers those, and the attachment endpoint reapplies storage quality.
                # Model both real stages rather than mistaking the original PNG for upload bytes.
                dimensions, jpeg_quality = (2560, 85) if quality == "high" else (1280, 60)
                upload_payloads = [compress_image_for_upload(source, dimensions, jpeg_quality)[0] for source in sources]
                expected_uploads = [
                    hashlib.sha256(compress_image_for_upload(payload, dimensions, jpeg_quality)[0]).hexdigest()
                    for payload in upload_payloads
                ]
                listing = control.get("entities", params={"isLocation": "false", "parentIds": location["id"]})
                listing.raise_for_status()
                assert len(listing.json()["items"]) == expected_items
                rows, actual_uploads = [], []
                for row in listing.json()["items"]:
                    response = control.get(f"entities/{row['id']}")
                    response.raise_for_status()
                    item = response.json()
                    assert item["entityType"]["id"] == native["id"]
                    assert item["parent"]["id"] == location["id"]
                    assert item["name"].startswith("Group reviewed ")
                    assert {f["name"]: f["textValue"] for f in item["fields"]} == {
                        "Part number": "0007-SYN",
                        "Condition": "Keep default",
                    }
                    assert all(f["id"] for f in item["fields"])
                    assert len(item["attachments"]) == (1 if per_photo else 3)
                    for attachment in item["attachments"]:
                        downloaded = control.get(f"entities/{item['id']}/attachments/{attachment['id']}")
                        downloaded.raise_for_status()
                        digest = hashlib.sha256(downloaded.content).hexdigest()
                        actual_uploads.append(digest)
                        (artifacts / f"stored-{digest}.jpg").write_bytes(downloaded.content)
                    rows.append(item)
                assert sorted(actual_uploads) == sorted(expected_uploads), (
                    "Independent Homebox readback matches every intended stored photo byte-for-byte"
                )
                (artifacts / "readback.json").write_text(
                    json.dumps(
                        {
                            "image": account.server.image,
                            "items": rows,
                            "quality": quality,
                            "provider_requests": len(requests),
                            "vision_sha256": actual_vision,
                            "stored_sha256": actual_uploads,
                            "independent_control_credential": True,
                        },
                        indent=2,
                    )
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    import uvicorn

    from server.app import create_app

    uvicorn.run(create_app(static_directory=sys.argv[2]), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
