"""Browser -> served source/image -> HTTP fault proxy -> native Homebox.

Unlike test_attachment_submission, TEST_COMPANION_IMAGE selects the actual image
application and static assets using its default CMD; only settings data is mounted.
"""

from __future__ import annotations

import hashlib
import http.server
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
from image_harness import DOCKER, production_image_command, start_server
from test_capture_groups_fullstack import vision_wire as vision_wire

from homebox_companion.ai.images import compress_image_for_upload

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.live


@pytest.mark.parametrize("mode", ["normal", "false-primary", "false-additional", "lost-primary"])
def test_attachment_served_application(homebox_test_account, homebox_key_factory, vision_wire, tmp_path, mode):
    account = homebox_test_account
    key = homebox_key_factory()
    artifacts = Path(os.environ.get("HBC_SMOKE_ARTIFACT_DIR", str(tmp_path))) / f"attachment-http-{mode}"
    artifacts.mkdir(parents=True, exist_ok=False)
    wire = []
    upload_count = 0
    failure_slot = {"false-primary": 0, "false-additional": 1}.get(mode)

    class Proxy(http.server.BaseHTTPRequestHandler):
        def forward(self):
            nonlocal upload_count
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection"}}
            injected = False
            with httpx.Client(base_url=account.server.base_url, trust_env=False, timeout=20) as native:
                if self.command == "POST" and self.path.endswith("/attachments"):
                    slot = upload_count
                    upload_count += 1
                    if slot == failure_slot:
                        # Explicit replay of the observed unchanged-entity 201 contract,
                        # not an induced database lock and not a fabricated Companion API.
                        read_headers = {
                            k: v for k, v in headers.items() if k.lower() not in {"content-length", "content-type"}
                        }
                        unchanged = native.get(self.path.removesuffix("/attachments"), headers=read_headers)
                        unchanged.raise_for_status()
                        response = httpx.Response(201, json=unchanged.json())
                        injected = True
                    else:
                        response = native.request(self.command, self.path, headers=headers, content=body)
                else:
                    response = native.request(self.command, self.path, headers=headers, content=body)
            wire.append(
                {"method": self.command, "path": self.path, "status": response.status_code, "injected": injected}
            )
            self.send_response(response.status_code)
            for name in ["content-type", "set-cookie"]:
                if name in response.headers:
                    self.send_header(name, response.headers[name])
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = do_PUT = do_DELETE = forward

        def log_message(self, format, *args):
            pass  # No credentials, request bodies or native auth responses in artifacts.

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"
    with httpx.Client(
        base_url=account.api_url + "/",
        headers={"Authorization": f"Bearer {account.control_token}"},
        trust_env=False,
        timeout=20,
    ) as control:
        types = control.get("entity-types")
        types.raise_for_status()
        location_type = next(row["id"] for row in types.json() if row["isLocation"])
        created = control.post("entities", json={"name": "Attachment guard storage", "entityTypeId": location_type})
        created.raise_for_status()
        location = created.json()["id"]
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as proxy:
            thread = threading.Thread(target=proxy.serve_forever, daemon=True)
            thread.start()
            env = {k: v for k, v in os.environ.items() if not k.startswith(("HBC_", "OPENAI_", "ANTHROPIC_"))}
            env.update(
                HBC_HOMEBOX_URL=f"http://127.0.0.1:{proxy.server_port}",
                HBC_HOMEBOX_API_KEY=key.token,
                HBC_LLM_API_KEY="synthetic-only-no-real-provider",
                HBC_LLM_MODEL="gpt-5.6-luna",
                HBC_LLM_API_BASE=vision_wire[0],
                HBC_DISABLE_UPDATE_CHECK="true",
                HBC_IMAGE_QUALITY="low",
                LITELLM_LOCAL_MODEL_COST_MAP="True",
                PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "src")]),
            )
            with (artifacts / "server.log").open("w") as log:
                container_name = None
                if os.environ.get("TEST_COMPANION_IMAGE"):
                    command = production_image_command(port, tmp_path, env)
                    container_name = command[command.index("--name") + 1]
                    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                else:
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
                    node = shutil.which("node")
                    assert node
                    result = subprocess.run(
                        [
                            node,
                            str(ROOT / "frontend/node_modules/@playwright/test/cli.js"),
                            "test",
                            "--config=tests/fullstack/playwright.config.ts",
                            "attachment-guard.spec.ts",
                            f"--output={artifacts / 'playwright'}",
                        ],
                        cwd=ROOT / "frontend",
                        env={
                            **os.environ,
                            "HBC_SMOKE_URL": url,
                            "HBC_ATTACHMENT_CASE": mode,
                            "HBC_ATTACHMENT_TYPE": next(row["id"] for row in types.json() if not row["isLocation"]),
                            "HBC_SMOKE_ARTIFACT_DIR": str(artifacts),
                        },
                        timeout=120,
                        check=False,
                    )
                    assert result.returncode == 0, f"Browser failed; preserved {artifacts}"
                    browser = json.loads((artifacts / "browser.json").read_text())
                    assert len(vision_wire[1]) == 1
                    assert browser["creates"] == 1 and browser["deletes"] == 0
                    assert not any(row["method"] == "DELETE" for row in wire)
                    assert sum(row["method"] == "POST" and row["path"] == "/api/v1/entities" for row in wire) == 1
                    assert upload_count == (2 if mode in {"normal", "false-additional"} else 1)
                    assert sum(row["injected"] for row in wire) == (1 if failure_slot is not None else 0)
                    listing = control.get("entities", params={"isLocation": "false", "parentIds": location})
                    listing.raise_for_status()
                    assert len(listing.json()["items"]) == 1
                    entity = listing.json()["items"][0]["id"]
                    detail = control.get(f"entities/{entity}")
                    detail.raise_for_status()
                    (artifacts / "native-entity.json").write_text(json.dumps(detail.json(), indent=2))
                    attachments = detail.json()["attachments"]
                    assert (
                        len(attachments)
                        == {"normal": 2, "false-primary": 0, "false-additional": 1, "lost-primary": 1}[mode]
                    )
                    expected = compress_image_for_upload((artifacts / "source.png").read_bytes(), 1280, 60)[0]
                    expected = compress_image_for_upload(expected, 1280, 60)[0]
                    receipts = [row["body"] for row in browser["responses"] if row["status"] == 200]
                    assert len(receipts) == len(attachments)
                    for receipt in receipts:
                        assert receipt["verified"] is True and receipt["entity_id"] == entity
                        assert receipt["attachment_id"] in {row["id"] for row in attachments}
                        downloaded = control.get(f"entities/{entity}/attachments/{receipt['attachment_id']}")
                        downloaded.raise_for_status()
                        assert downloaded.content == expected
                        assert hashlib.sha256(downloaded.content).hexdigest() == receipt["sha256"]
                        assert len(downloaded.content) == receipt["byte_length"]
                        (artifacts / f"original-{receipt['slot']}.jpg").write_bytes(downloaded.content)
                    if mode != "normal":
                        draft = json.loads((artifacts / "draft.json").read_text())
                        assert draft["submission"]["createdItemIds"]["0"] == entity
                    if os.environ.get("TEST_COMPANION_IMAGE"):
                        image = subprocess.check_output(
                            [
                                "docker",
                                "--host",
                                "unix:///var/run/docker.sock",
                                "image",
                                "inspect",
                                os.environ["TEST_COMPANION_IMAGE"],
                                "--format",
                                "{{.Id}}",
                            ],
                            text=True,
                            timeout=15,
                        ).strip()
                    else:
                        image = None
                    (artifacts / "boundary.json").write_text(
                        json.dumps(
                            {
                                "companion_image_id": image,
                                "mode": mode,
                                "homebox_image": account.server.image,
                                "provider": "synthetic HTTP; real SDK",
                                "original_sha256": hashlib.sha256(expected).hexdigest(),
                            },
                            indent=2,
                        )
                    )
                finally:
                    if container_name is not None:
                        subprocess.run(DOCKER + ["rm", "--force", container_name], capture_output=True, timeout=20)
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    proxy.shutdown()
                    thread.join(timeout=5)
                    (artifacts / "wire.json").write_text(json.dumps(wire, indent=2))
                    logs = subprocess.run(
                        ["docker", "logs", account.server.name], capture_output=True, text=True, timeout=15
                    )
                    (artifacts / "homebox.log").write_text(logs.stdout + logs.stderr)


if __name__ == "__main__":
    import uvicorn

    from server.app import create_app

    uvicorn.run(create_app(static_directory=sys.argv[2]), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
