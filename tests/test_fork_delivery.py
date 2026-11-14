"""Fork release identity contracts; no registry credentials needed."""

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from homebox_companion.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_fork_identity_and_safe_update_defaults(monkeypatch):
    monkeypatch.delenv("HBC_DISABLE_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("HBC_GITHUB_REPO", raising=False)
    settings = Settings(_env_file=None)
    assert settings.disable_update_check is True
    assert settings.github_repo == "bennyb21/homebox-companion"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["version"] == "0.1.0"
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert next(p["version"] for p in lock["package"] if p["name"] == project["name"]) == project["version"]
    assert "LICENSE" not in (ROOT / ".dockerignore").read_text().splitlines()
    assert "COPY LICENSE" in (ROOT / "Dockerfile").read_text()


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("required_job", ["production-container", "audit"])
@pytest.mark.parametrize("bad", [None, "failure", "cancelled", "skipped", "missing"])
def test_actual_release_gate_fails_closed(bad, required_job):
    gate = workflow("validate.yml")["jobs"]["release-gate"]
    assert gate["if"] == "always()"
    needs = {name: {"result": "success"} for name in gate["needs"]}
    if bad == "missing":
        needs.pop(required_job)
    elif bad:
        needs[required_job]["result"] = bad
    result = subprocess.run(
        ["bash", "-eu", "-c", gate["steps"][0]["run"]],
        env={**os.environ, "RESULTS": json.dumps(needs)},
        capture_output=True,
    )
    assert (result.returncode == 0) == (bad is None)


def test_publication_requires_same_run_and_manual_protected_promotion():
    publish = workflow("docker-publish.yml")
    assert set(publish["on"]) == {"workflow_dispatch"}
    assert publish["jobs"]["validate"]["uses"] == "./.github/workflows/validate.yml"
    job = publish["jobs"]["publish"]
    assert job["needs"] == "validate"
    assert job["if"] == "needs.validate.result == 'success'"
    assert job["environment"] == "garage-test"
    assert job["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    script = (ROOT / "scripts/publish-candidate.sh").read_text()
    assert 'gh run download "$RUN_ID"' in script
    assert "docker build" not in script
    assert 'case "$STATUS" in' in script
    steps = workflow("validate.yml")["jobs"]["production-container"]["steps"]
    preserve = next(step for step in steps if step.get("name", "").startswith("Preserve the tested"))
    assert "scripts/seal-tested-image.sh" in preserve["run"]
    upload = steps[steps.index(preserve) + 1]
    assert "tested-identity.json" in upload["with"]["path"]
    assert upload["with"].get("overwrite", "false") == "false"
    checkpoint = next(
        step for step in job["steps"] if step.get("with", {}).get("name", "").startswith("publication-state-")
    )
    assert "always()" in checkpoint["if"]
    assert "github.run_attempt" in checkpoint["with"]["name"]
    assert "docker logout ghcr.io" in script
    stable = workflow("promote.yml")
    assert set(stable["on"]) == {"workflow_dispatch"}
    assert stable["jobs"]["promote"]["environment"] == "garage-stable"
    assert "packages" not in workflow("validate.yml")["permissions"]


def test_audit_evidence_is_attempt_qualified_but_tested_image_is_immutable():
    audit_steps = workflow("audit.yml")["jobs"]["audit"]["steps"]
    upload = next(s for s in audit_steps if "upload-artifact@" in s.get("uses", ""))
    assert upload["with"]["name"] == "frontend-audit-${{ github.job }}-${{ github.run_attempt }}"
    assert upload["with"].get("overwrite", "false") == "false"
    assert upload["if"] == "always()"
    image_steps = workflow("validate.yml")["jobs"]["production-container"]["steps"]
    image = next(s for s in image_steps if s.get("with", {}).get("name") == "release-image")
    assert image["with"].get("overwrite", "false") == "false"
    assert (
        'gh run download "$RUN_ID" --repo "$REPOSITORY" --name release-image'
        in (ROOT / "scripts/publish-candidate.sh").read_text()
    )


@pytest.mark.live
def test_runtime_image_identity_and_license():
    image = os.environ["TEST_COMPANION_IMAGE"]
    docker = ["docker", "--host", "unix:///var/run/docker.sock"]
    env = {k: v for k, v in os.environ.items() if k not in ("DOCKER_HOST", "DOCKER_CONTEXT")}
    metadata = json.loads(subprocess.check_output(docker + ["image", "inspect", image], env=env))[0]
    labels = metadata["Config"]["Labels"]
    assert labels["org.opencontainers.image.source"] == "https://github.com/bennyb21/homebox-companion"
    assert labels["org.opencontainers.image.version"] == "0.1.0"
    revision = labels["org.opencontainers.image.revision"]
    assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
    script = """
import os, pathlib, importlib.metadata
from homebox_companion.core.config import Settings
assert os.getuid() == os.getgid() == 1000
assert importlib.metadata.version("homebox-companion") == "0.1.0"
assert "GNU GENERAL PUBLIC LICENSE" in pathlib.Path("/app/LICENSE").read_text()
assert Settings(_env_file=None).disable_update_check
assert not pathlib.Path("/app/tests").exists()
assert not pathlib.Path("/image-entrypoint.py").exists()
print("runtime identity, license, no test overlay: verified")
"""
    subprocess.run(
        docker + ["run", "--rm", "--network", "none", image, "/app/.venv/bin/python", "-c", script], env=env, check=True
    )
