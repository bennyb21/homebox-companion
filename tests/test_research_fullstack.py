"""Real browser/API/isolated Homebox and actual Companion process restart."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from conftest import _find_free_port

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.live


def test_research_browser_readback_and_restart(homebox_test_account, homebox_key_factory, tmp_path):
    node = shutil.which("node")
    assert node is not None
    account = homebox_test_account
    key = homebox_key_factory()
    artifact = Path(os.environ.get("HBC_SMOKE_ARTIFACT_DIR", tmp_path))
    artifact.mkdir(parents=True, exist_ok=True)
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HBC_", "OPENAI_", "ANTHROPIC_"))}
    env.update(
        HBC_HOMEBOX_URL=account.server.base_url,
        HBC_HOMEBOX_API_KEY=key.token,
        HBC_DISABLE_UPDATE_CHECK="true",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "src")]),
    )
    with httpx.Client(
        base_url=account.api_url + "/", headers={"Authorization": f"Bearer {account.control_token}"}, trust_env=False
    ) as control:
        types = control.get("entity-types").json()
        location_type = next(row["id"] for row in types if row["isLocation"])
        location = control.post("entities", json={"name": "Research storage", "entityTypeId": location_type})
        location.raise_for_status()
        template = control.post(
            "templates",
            json={
                "name": "Research text",
                "fields": [
                    {"name": "Specifications", "type": "text", "textValue": ""},
                    {"name": "Condition", "type": "text", "textValue": "manual"},
                ],
            },
        )
        template.raise_for_status()
        native = control.post(
            "entity-types",
            json={"name": "Research part", "isLocation": False, "defaultTemplateId": template.json()["id"]},
        )
        native.raise_for_status()
        item = control.post(
            f"templates/{template.json()['id']}/create-item",
            json={
                "name": "Synthetic research part",
                "quantity": 1,
                "parentId": location.json()["id"],
                "description": "",
                "entityTypeId": native.json()["id"],
            },
        )
        assert item.is_success, item.text
        id_ = item.json()["id"]
        before = control.get(f"entities/{id_}").json()
        process = None
        log = (artifact / "research-server.log").open("w")

        def start():
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), str(port), str(ROOT / "frontend/build")],
                cwd=tmp_path,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            for _ in range(150):
                assert process.poll() is None
                try:
                    if httpx.get(url + "/api/version", timeout=1, trust_env=False).status_code == 200:
                        return process
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            process.kill()
            process.wait()
            raise AssertionError("Server did not start")

        try:
            process = start()
            browser_env = {**os.environ, "HBC_SMOKE_URL": url, "HBC_RESEARCH_SMOKE": "1", "HBC_RESEARCH_ITEM": id_}
            result = subprocess.run(
                [
                    node,
                    str(ROOT / "frontend/node_modules/@playwright/test/cli.js"),
                    "test",
                    "research.spec.ts",
                    "--config=tests/fullstack/playwright.config.ts",
                ],
                cwd=ROOT / "frontend",
                env=browser_env,
                timeout=120,
            )
            assert result.returncode == 0
            readback = control.get(f"entities/{id_}")
            readback.raise_for_status()
            fields = {f["name"]: f for f in readback.json()["fields"]}
            assert fields["Specifications"]["textValue"] == "Steel, 12 mm"
            assert fields["Condition"]["textValue"] == "manual"
            assert {f["id"] for f in before["fields"]} == {f["id"] for f in readback.json()["fields"]}
            with httpx.Client(base_url=url, headers={"X-Companion-Request": "1"}, trust_env=False) as client:
                jobs = client.get("/api/research/jobs")
                jobs.raise_for_status()
                job_id = jobs.json()[0]["id"]
            process.terminate()
            process.wait(timeout=10)
            process = start()
            with httpx.Client(base_url=url, headers={"X-Companion-Request": "1"}, trust_env=False) as client:
                resumed = client.get(f"/api/research/jobs/{job_id}")
                resumed.raise_for_status()
                assert resumed.json()["state"] == "applied"
            assert (tmp_path / "dispatches.txt").read_text() == "POST\n"
            (artifact / "research-readback.json").write_text(
                json.dumps(
                    {
                        "item": readback.json(),
                        "restart_job": resumed.json(),
                        "dispatches": 1,
                        "independent_control_credential": True,
                    },
                    indent=2,
                )
            )
            assert (tmp_path / "data/research.sqlite3").is_file()
        finally:
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            log.close()


if __name__ == "__main__":
    import uvicorn
    from pydantic import SecretStr
    from test_research_evidence import response

    from homebox_companion.core.persistent_settings import ModelProfile
    from homebox_companion.research import OpenAIResponsesResearchProvider, ResearchPolicy
    from server.app import create_app

    def respond(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        with Path("dispatches.txt").open("a") as out:
            out.write("POST\n")
        return httpx.Response(200, json=response() | {"object": "response", "created_at": 1, "model": "gpt-4.1-mini"})

    app = create_app(static_directory=sys.argv[2])
    app.state.research_provider = OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=True, profile_name="synthetic"),
        ModelProfile(name="synthetic", model="gpt-4.1-mini", api_key=SecretStr("synthetic-only")),
        transport=httpx.MockTransport(respond),
    )
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
