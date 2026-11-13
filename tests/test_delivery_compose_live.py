"""Opt-in local registry/Compose upgrade and stopped-writer restore drill.

Requires TEST_IMAGE_A and TEST_IMAGE_B: two explicitly identified real builds.
Only loopback registry publication is performed. No daemon configuration changes.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from conftest import HomeboxDockerServer, _find_free_port, _wait_for_status
from image_harness import DOCKER
from test_fullstack_smoke import chat_provider  # noqa: F401
from test_fullstack_smoke import test_reviewed_photo_reaches_homebox as capture_smoke
from test_research_fullstack import test_research_browser_readback_and_restart as research_smoke

pytestmark = pytest.mark.live


def docker(*args):
    env = {k: v for k, v in os.environ.items() if k not in ("DOCKER_HOST", "DOCKER_CONTEXT")}
    return subprocess.check_output(DOCKER + list(args), env=env, text=True, stderr=subprocess.STDOUT).strip()


@pytest.fixture(scope="session")
def isolated_homebox_server(homebox_image):
    suffix = uuid.uuid4().hex[:10]
    volume = f"hbc-delivery-homebox-{suffix}"
    image = os.environ["TEST_IMAGE_A"]
    docker("volume", "create", volume)
    docker(
        "run",
        "--rm",
        "--user",
        "0",
        "-v",
        f"{volume}:/data",
        image,
        "sh",
        "-c",
        "chown 65532:65532 /data && chmod 700 /data",
    )
    server = HomeboxDockerServer(
        name=f"hbc-delivery-homebox-{suffix}",
        image=homebox_image,
        volume=volume,
        host_port=str(_find_free_port()),
        environment={
            "HBOX_MODE": "production",
            "HBOX_DEMO": "false",
            "HBOX_OPTIONS_ALLOW_REGISTRATION": "true",
            "HBOX_OPTIONS_ALLOW_LOCAL_LOGIN": "true",
            "HBOX_OPTIONS_ALLOW_ANALYTICS": "false",
            "HBOX_AUTH_RATE_LIMIT_ENABLED": "false",
            "HBOX_AUTH_API_KEY_PEPPER": "synthetic-delivery-pepper-not-for-production-123456",
        },
    )
    try:
        server.start()
        _wait_for_status(server)
        yield server
    finally:
        server.remove()


def test_compose_pull_upgrade_restore(homebox_test_account, homebox_key_factory, chat_provider, tmp_path, monkeypatch):  # noqa: F811
    a, b = os.environ["TEST_IMAGE_A"], os.environ["TEST_IMAGE_B"]
    assert docker("image", "inspect", a, "--format", "{{.Id}}") != docker("image", "inspect", b, "--format", "{{.Id}}")
    evidence = Path(os.environ["HBC_DELIVERY_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HBC_SMOKE_ARTIFACT_DIR", str(evidence))
    monkeypatch.setenv("TEST_COMPANION_IMAGE", a)
    capture_smoke(homebox_test_account, homebox_key_factory, chat_provider, tmp_path, "auto")
    research_smoke(homebox_test_account, homebox_key_factory, tmp_path)
    native = json.loads((evidence / "native-readback.json").read_text())
    research = json.loads((evidence / "research-readback.json").read_text())
    account = homebox_test_account
    key = homebox_key_factory()
    suffix = uuid.uuid4().hex[:10]
    project = f"hbc-delivery-{suffix}"
    registry = f"{project}-registry"
    reg_port, port = _find_free_port(), _find_free_port()
    repo = f"localhost:{reg_port}/companion"
    registry_data = tmp_path / "registry"
    registry_data.mkdir()
    compose_file = tmp_path / "compose.yaml"
    results: dict = {
        "source_images": {"a": a, "b": b},
        "stages": [],
        "registry": repo,
        "homebox_image": account.server.image,
        "storage": "bind mount + named Homebox volume (not tmpfs)",
    }
    control = httpx.Client(
        base_url=account.api_url + "/",
        headers={"Authorization": f"Bearer {account.control_token}"},
        trust_env=False,
        timeout=15,
    )
    settings_before = (tmp_path / "data/settings.yaml").read_bytes()

    def compose(*args):
        return docker("compose", "-p", project, "-f", str(compose_file), *args)

    def configure(image):
        compose_file.write_text(
            yaml.safe_dump(
                {
                    "services": {
                        "companion": {
                            "image": image,
                            "network_mode": "host",
                            "user": "1000:1000",
                            "volumes": [f"{tmp_path / 'data'}:/app/data"],
                            "environment": {
                                "HBC_SERVER_HOST": "127.0.0.1",
                                "HBC_SERVER_PORT": str(port),
                                "HBC_HOMEBOX_URL": account.server.base_url,
                                "HBC_HOMEBOX_API_KEY": key.token,
                                "HBC_DISABLE_UPDATE_CHECK": "true",
                                "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                            },
                        }
                    }
                }
            )
        )
        compose_file.chmod(0o600)

    def verify(stage, expected):
        for _ in range(200):
            try:
                version = httpx.get(f"http://127.0.0.1:{port}/api/version", trust_env=False, timeout=1)
                if version.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise AssertionError(compose("logs"))
        cid = compose("ps", "-q", "companion")
        identity = docker("inspect", cid, "--format", "{{.Image}}")
        assert identity == docker("image", "inspect", expected, "--format", "{{.Id}}")
        assert (tmp_path / "data/settings.yaml").read_bytes() == settings_before
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            assert client.get("/").status_code == 200
            job = client.get(f"/api/research/jobs/{research['restart_job']['id']}")
            job.raise_for_status()
            assert job.json()["state"] == "applied"
        item = control.get(f"entities/{native['item']['id']}")
        item.raise_for_status()
        assert item.json() == native["item"]
        photo = control.get(f"entities/{native['item']['id']}/attachments/{native['item']['attachments'][0]['id']}")
        photo.raise_for_status()
        assert hashlib.sha256(photo.content).hexdigest() == native["photo_sha256"]
        results["stages"].append(
            {
                "stage": stage,
                "container": cid,
                "image_id": identity,
                "version": version.json(),
                "native_item_equal": True,
                "photo_sha256": native["photo_sha256"],
                "job": job.json()["state"],
                "settings_sha256": hashlib.sha256(settings_before).hexdigest(),
            }
        )

    try:
        docker(
            "run",
            "-d",
            "--name",
            registry,
            "-p",
            f"127.0.0.1:{reg_port}:5000",
            "-v",
            f"{registry_data}:/var/lib/registry",
            "registry:3@sha256:82f6ff4a7f982960c8aa51617fea3aabc485df6e55cce80d22deb1de36f1bc3c",
        )
        for image, tag in [(a, "a"), (b, "b")]:
            docker("tag", image, f"{repo}:{tag}")
            output = docker("push", f"{repo}:{tag}")
            (evidence / f"push-{tag}.log").write_text(output)
            digests = json.loads(docker("image", "inspect", f"{repo}:{tag}", "--format", "{{json .RepoDigests}}"))
            results[tag] = next(d for d in digests if d.startswith(repo + "@"))
        configure(results["a"])
        (evidence / "pull-a.log").write_text(compose("pull"))
        compose("up", "-d")
        verify("baseline-a", a)
        # Consistent filesystem backups: stop both writers before copying SQLite and attachments.
        compose("stop")
        docker("stop", account.server.name)
        backup = tmp_path / "backup"
        shutil.copytree(tmp_path / "data", backup / "companion")
        (backup / "homebox").mkdir()
        docker(
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{account.server.volume}:/source:ro",
            "-v",
            f"{backup / 'homebox'}:/backup",
            a,
            "sh",
            "-c",
            "cp -a /source/. /backup/",
        )
        docker("start", account.server.name)
        account.server.rediscover_port()
        control.base_url = account.api_url + "/"
        configure(results["a"])
        _wait_for_status(account.server)
        configure(results["b"])
        (evidence / "pull-b.log").write_text(compose("pull"))
        compose("up", "-d")
        verify("upgrade-b", b)
        configure(results["a"])
        (evidence / "pull-rollback.log").write_text(compose("pull"))
        compose("up", "-d")
        verify("rollback-a", a)
        compose("stop")
        docker("stop", account.server.name)
        # Prove restore is used, not merely that an untouched volume survives.
        (tmp_path / "data/settings.yaml").write_text("synthetic_restore_probe: true\n")
        assert (tmp_path / "data/settings.yaml").read_bytes() != settings_before
        shutil.rmtree(tmp_path / "data")
        shutil.copytree(backup / "companion", tmp_path / "data")
        docker(
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{account.server.volume}:/target",
            "-v",
            f"{backup / 'homebox'}:/backup:ro",
            a,
            "/app/.venv/bin/python",
            "-c",
            "import shutil,pathlib; p=pathlib.Path('/target'); "
            "[(shutil.rmtree(x) if x.is_dir() else x.unlink()) for x in p.iterdir()]; "
            "shutil.copytree('/backup','/target',dirs_exist_ok=True)",
        )
        # Restore copied files' service ownership (test host and container users may differ).
        docker(
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{tmp_path / 'data'}:/target",
            "-v",
            f"{account.server.volume}:/homebox",
            a,
            "sh",
            "-c",
            "chown -R 1000:1000 /target && chown -R 65532:65532 /homebox",
        )
        docker("start", account.server.name)
        account.server.rediscover_port()
        control.base_url = account.api_url + "/"
        configure(results["a"])
        _wait_for_status(account.server)
        compose("up", "-d", "--force-recreate")
        verify("backup-restored-a", a)
        assert len({s["container"] for s in results["stages"]}) == 4
        results["backup_restore"] = "both writers stopped; full data copied; Homebox volume emptied and restored"
        (evidence / "upgrade-proof.json").write_text(json.dumps(results, indent=2))
    finally:
        control.close()
        if compose_file.exists():
            compose("down")
        docker("rm", "-f", registry)
