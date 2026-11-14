"""Offline fail-closed audit contracts; fixtures are public npm responses."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/frontend-audit"


def check(tmp_path, report=None, code=1, root=ROOT):
    raw = tmp_path / "audit.json"
    raw.write_text(
        json.dumps(report if report is not None else json.loads((FIXTURES / "patched-reviewed.json").read_text()))
    )
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_frontend_audit.py"),
            "--report",
            str(raw),
            "--npm-exit",
            str(code),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
    )


def test_reviewed_findings_are_explicitly_accepted(tmp_path):
    result = check(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ACCEPTED USER-APPROVED EXCEPTIONS" in result.stdout
    for advisory in ("GHSA-pfhg-q3qv-9q6r", "GHSA-27mw-82g8-phjj", "GHSA-gcqx-w48m-w2h4"):
        assert advisory in result.stdout
    assert "private-usability-pilot" in result.stdout
    assert "@sveltejs/kit@2.70.4:" in result.stdout
    assert "@sveltejs/adapter-static@3.0.11:" in result.stdout
    assert "@sveltejs/vite-plugin-svelte@7.3.1:" in result.stdout
    assert "deepmerge@4.3.1:" in result.stdout


@pytest.mark.parametrize("package,old_version", [("@sveltejs/kit", "2.70.3"), ("@sveltejs/adapter-static", "3.0.10")])
def test_historical_versions_cannot_authorize_patched_graph(tmp_path, package, old_version):
    import shutil

    root = tmp_path / "repo"
    policy = json.loads((ROOT / "docs/frontend-audit-policy.json").read_text())
    for name in policy["reviewed_files"]:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    policy["packages"][package] = old_version
    (root / "docs").mkdir()
    (root / "docs/frontend-audit-policy.json").write_text(json.dumps(policy))
    result = check(tmp_path, root=root)
    assert result.returncode == 1
    assert f"Unreviewed package version: {package}" in result.stderr


def test_historical_report_retains_original_advisory_identities():
    historical = json.loads((FIXTURES / "reviewed.json").read_text())
    patched = json.loads((FIXTURES / "patched-reviewed.json").read_text())

    def identities(report):
        return {a["url"]: a for node in report["vulnerabilities"].values() for a in node["via"] if isinstance(a, dict)}

    assert identities(historical) == identities(patched)
    assert len(identities(patched)) == 3
    # Preserve the original raw response byte-for-byte, not a synthetic new snapshot.
    import hashlib

    assert hashlib.sha256((FIXTURES / "reviewed.json").read_bytes()).hexdigest() == (
        "5c569b91ca6fc57dc8b7f1c9f933f1108daeacb0fbe7708bf5329a22dcafeca9"
    )


def test_transport_failure_cannot_be_accepted(tmp_path):
    report = json.loads((FIXTURES / "patched-reviewed.json").read_text())
    report["error"] = {"code": "ECONNRESET", "summary": "network failure"}
    assert check(tmp_path, report).returncode == 1
    assert check(tmp_path, code=2).returncode == 1


def test_honest_zero_findings(tmp_path):
    report = json.loads((FIXTURES / "patched-reviewed.json").read_text())
    report["vulnerabilities"] = {}
    report["metadata"]["vulnerabilities"] = dict.fromkeys(report["metadata"]["vulnerabilities"], 0)
    result = check(tmp_path, report, code=0)
    assert result.returncode == 0, result.stderr
    assert "ZERO FINDINGS" in result.stdout
    assert "EXCEPTIONS" not in result.stdout
    assert check(tmp_path, report, code=1).returncode == 1
    assert check(tmp_path, code=0).returncode == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "cycle",
        "dangling",
        "empty-via",
        "unknown-node",
        "higher-severity",
        "bad-count",
        "missing-metadata",
        "missing-nodes",
        "bad-version",
        "extra-field",
        "wrong-report-version",
        "bad-dependency-count",
        "bad-effects",
        "duplicate-via",
        "wrong-node-path",
        "empty-nodes",
    ],
)
def test_incomplete_or_unreviewed_graph_is_blocked(tmp_path, mutation):
    report = json.loads((FIXTURES / "patched-reviewed.json").read_text())
    node = report["vulnerabilities"]["deepmerge"]
    if mutation == "cycle":
        node["via"].append("@sveltejs/kit")
    elif mutation == "dangling":
        node["via"].append("missing")
    elif mutation == "empty-via":
        node["via"] = []
    elif mutation == "unknown-node":
        report["vulnerabilities"]["unknown"] = dict(node, name="unknown")
        report["metadata"]["vulnerabilities"]["low"] += 1
        report["metadata"]["vulnerabilities"]["total"] += 1
    elif mutation == "higher-severity":
        node["severity"] = "high"
        report["metadata"]["vulnerabilities"].update(low=3, high=1)
    elif mutation == "bad-count":
        report["metadata"]["vulnerabilities"]["total"] += 1
    elif mutation == "missing-metadata":
        del report["metadata"]
    elif mutation == "missing-nodes":
        del node["nodes"]
    elif mutation == "bad-version":
        node["isDirect"] = "false"
    elif mutation == "extra-field":
        report["unparsed-findings"] = ["unexpected"]
    elif mutation == "wrong-report-version":
        report["auditReportVersion"] = 1
    elif mutation == "bad-dependency-count":
        report["metadata"]["dependencies"]["total"] -= 1
    elif mutation == "bad-effects":
        node["effects"].append("missing")
    elif mutation == "duplicate-via":
        node["via"].append(node["via"][0])
    elif mutation == "wrong-node-path":
        node["nodes"] = ["node_modules/other"]
    elif mutation == "empty-nodes":
        node["nodes"] = []
    result = check(tmp_path, report)
    assert result.returncode == 1, result.stdout
    assert "BLOCKED" in result.stderr


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "https://github.com/advisories/GHSA-new"),
        ("severity", "moderate"),
        ("source", 999),
        ("dependency", "other"),
        ("range", "*"),
        ("cvss", {"score": 10}),
        ("title", "changed"),
    ],
)
def test_advisory_identity_must_match(tmp_path, field, value):
    report = json.loads((FIXTURES / "patched-reviewed.json").read_text())
    report["vulnerabilities"]["deepmerge"]["via"][0][field] = value
    assert check(tmp_path, report).returncode == 1


def test_actual_new_registry_findings_remain_blocking(tmp_path):
    result = check(tmp_path, json.loads((FIXTURES / "new-moderate.json").read_text()))
    assert result.returncode == 1
    assert "Unapproved severity" in result.stderr


@pytest.mark.parametrize(
    "target",
    [
        "frontend/package-lock.json",
        "frontend/package.json",
        "frontend/.npmrc",
        "frontend/svelte.config.js",
        "frontend/vite.config.ts",
        "frontend/src/new.svelte",
        "frontend/src/linked-directory",
        "frontend/src/routes/+layout.ts",
    ],
)
def test_review_context_changes_require_fresh_review(tmp_path, target):
    import shutil

    root = tmp_path / "repo"
    policy = json.loads((ROOT / "docs/frontend-audit-policy.json").read_text())
    for name in [*policy["reviewed_files"], "docs/frontend-audit-policy.json"]:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    path = root / target
    path.parent.mkdir(parents=True, exist_ok=True)
    if target.endswith("linked-directory"):
        external = tmp_path / "external"
        external.mkdir()
        (external / "+page.svelte").write_text("use:enhance; setHeaders")
        path.symlink_to(external, target_is_directory=True)
    else:
        path.write_text(path.read_text() + "\n// changed" if path.exists() else "use:enhance; setHeaders")
    result = check(tmp_path, root=root)
    assert result.returncode == 1, result.stdout
    assert "review" in result.stderr.lower()


def test_duplicate_json_keys_fail_closed(tmp_path):
    raw = tmp_path / "duplicates.json"
    report = (FIXTURES / "patched-reviewed.json").read_text()
    raw.write_text(report.replace('"auditReportVersion": 2,', '"auditReportVersion": 999, "auditReportVersion": 2,'))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_frontend_audit.py"), "--report", str(raw), "--npm-exit", "1"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Duplicate" in result.stderr


@pytest.mark.parametrize(
    "content,code", [("{", 1), ("{}", 0), ("[]", 0), ('{"error":{"code":"EAI_AGAIN"}}', 1), ("", 0)]
)
def test_malformed_raw_response(tmp_path, content, code):
    raw = tmp_path / "raw.json"
    raw.write_text(content)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_frontend_audit.py"), "--report", str(raw), "--npm-exit", str(code)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "BLOCKED" in result.stderr


@pytest.mark.parametrize(
    "fixture,exit_code,expected",
    [("patched-reviewed.json", 1, 0), ("new-moderate.json", 1, 1), ("patched-reviewed.json", 2, 1)],
)
def test_runner_retains_actual_status_and_raw_output(tmp_path, fixture, exit_code, expected):
    import os

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    npm = fake_bin / "npm"
    npm.write_text(f'#!/bin/sh\ncat "{FIXTURES / fixture}"\nprintf "test stderr\\n" >&2\nexit {exit_code}\n')
    npm.chmod(0o755)
    artifacts = tmp_path / "evidence"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/audit-frontend.sh"), str(artifacts)],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{Path(sys.executable).parent}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected, result.stderr
    assert (artifacts / "npm-audit.json").read_bytes() == (FIXTURES / fixture).read_bytes()
    assert (artifacts / "npm-audit.exit").read_text().strip() == str(exit_code)
    assert "test stderr" in (artifacts / "npm-audit.stderr").read_text()
    assert (artifacts / "policy-result.log").is_file()


@pytest.mark.parametrize("setting", ["default", "omit-env", "production-env", "project-omit"])
def test_runner_pins_full_coverage_argv(tmp_path, setting):
    import os
    import shutil

    root = tmp_path / "repo"
    policy = json.loads((ROOT / "docs/frontend-audit-policy.json").read_text())
    for name in {
        *policy["reviewed_files"],
        "frontend/.npmrc",
        "docs/frontend-audit-policy.json",
        "scripts/audit-frontend.sh",
        "scripts/check_frontend_audit.py",
    }:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    env = dict(os.environ)
    if setting == "omit-env":
        env["npm_config_omit"] = "dev"
    elif setting == "production-env":
        env["NODE_ENV"] = "production"
    elif setting == "project-omit":
        with (root / "frontend/.npmrc").open("a") as stream:
            stream.write("omit=dev\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv = tmp_path / "argv"
    npm = fake_bin / "npm"
    # Stub only the network adapter; exercise the actual shell runner and checker.
    npm.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{argv}"\ncat "{FIXTURES / "patched-reviewed.json"}"\nexit 1\n')
    npm.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{Path(sys.executable).parent}:{env['PATH']}"
    artifacts = tmp_path / "evidence"
    result = subprocess.run(
        ["bash", str(root / "scripts/audit-frontend.sh"), str(artifacts)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert argv.read_text().splitlines() == [
        "audit",
        "--package-lock-only",
        "--json",
        "--include=dev",
        "--include=optional",
        "--include=peer",
        "--registry=https://registry.npmjs.org/",
        "--audit-level=low",
    ]
    assert (artifacts / "npm-audit.exit").read_text() == "1\n"
    decision = (artifacts / "policy-result.log").read_text()
    assert "ZERO FINDINGS" not in decision
    if setting == "project-omit":
        assert result.returncode == 1
        assert "Fresh review required: frontend/.npmrc" in decision
    else:
        assert result.returncode == 0, result.stderr
        assert "ACCEPTED USER-APPROVED EXCEPTIONS" in decision


@pytest.mark.parametrize("extra", ["--omit=dev", "--include=prod", "--registry=https://example.invalid/"])
def test_runner_rejects_caller_audit_arguments(tmp_path, extra):
    import os

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    called = tmp_path / "called"
    npm = fake_bin / "npm"
    npm.write_text(f'#!/bin/sh\ntouch "{called}"\nexit 2\n')
    npm.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/audit-frontend.sh"), str(tmp_path / "evidence"), extra],
        env={**os.environ, "PATH": f"{fake_bin}:{Path(sys.executable).parent}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert not called.exists()


def test_zero_findings_still_require_complete_dependency_inventory(tmp_path):
    report = json.loads((FIXTURES / "patched-reviewed.json").read_text())
    report["vulnerabilities"] = {}
    report["metadata"]["vulnerabilities"] = dict.fromkeys(report["metadata"]["vulnerabilities"], 0)
    report["metadata"]["dependencies"]["total"] = 1
    assert check(tmp_path, report, code=0).returncode == 1


def test_advisory_numeric_identity_is_not_coerced(tmp_path):
    report = json.loads((FIXTURES / "patched-reviewed.json").read_text())
    advisory = report["vulnerabilities"]["deepmerge"]["via"][0]
    advisory["source"] = float(advisory["source"])
    assert check(tmp_path, report).returncode == 1


def test_report_version_has_strict_integer_type(tmp_path):
    report = json.loads((FIXTURES / "patched-reviewed.json").read_text())
    report["auditReportVersion"] = 2.0
    assert check(tmp_path, report).returncode == 1


def test_audit_workflow_is_required_for_every_candidate():
    import yaml

    def workflow(name):
        return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)

    audit = workflow("audit.yml")
    assert "paths" not in (audit["on"]["pull_request"] or {})
    assert "workflow_call" in audit["on"]
    steps = audit["jobs"]["audit"]["steps"]
    assert any(s.get("run") == "uv run --no-sync pip-audit --local --skip-editable" for s in steps)
    assert any("scripts/audit-frontend.sh" in s.get("run", "") for s in steps)
    assert any("test_frontend_audit_policy.py" in s.get("run", "") for s in steps)
    assert any(s.get("if") == "always()" and "upload-artifact@" in s.get("uses", "") for s in steps)
    assert all("continue-on-error" not in s for s in steps)
    validate = workflow("validate.yml")
    assert validate["jobs"]["audit"]["uses"] == "./.github/workflows/audit.yml"
    assert "audit" in validate["jobs"]["release-gate"]["needs"]
