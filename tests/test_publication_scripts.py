"""Execute real delivery shells with synthetic, offline CLI boundaries."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "1" * 40
ID = "sha256:" + "b" * 64
IMAGE = "ghcr.io/example/companion"
DIGEST = IMAGE + "@sha256:" + "a" * 64
ARCHIVE = b"synthetic docker archive"
MOCK = r"""#!/usr/bin/env python3
import json, os, pathlib, signal, subprocess, sys
root = pathlib.Path(os.environ['MOCK_ROOT'])
s = json.loads((root/'state.json').read_text())
a = sys.argv[1:]; tool = pathlib.Path(sys.argv[0]).name
with (root/'calls.jsonl').open('a') as f:
    f.write(json.dumps([tool, a, os.environ.get('DOCKER_CONFIG')])+'\n')
def save(): (root/'state.json').write_text(json.dumps(s))
def fail(point):
    if s.get('fail') == 'term' and point == 'channel':
        os.kill(os.getppid(), signal.SIGTERM); sys.exit(1)
    if s.get('fail') == point:
        s.pop('fail'); save(); sys.exit(1)
if tool == 'jq':
    if '--arg' in a and 'digest' in a and s.get('fail') == 'checkpoint-write':
        print('{'); fail('checkpoint-write')
    sys.exit(subprocess.call([os.environ['REAL_JQ']] + a))
elif tool == 'gh':
    if a[0] == 'api':
        fail('api')
        if '/artifacts' in a[1]:
            print(json.dumps([{'artifacts': s.get('artifacts', [])}]))
        else: print(json.dumps(s['run']))
    elif a[:2] == ['run', 'download']:
        name = a[a.index('--name')+1]
        fail('download-' + name)
        if name == 'release-image':
            pathlib.Path('release-image.tar').write_bytes(b'synthetic docker archive')
            if not s.get('missing_identity'):
                pathlib.Path('tested-identity.json').write_text(json.dumps(s['identity']))
        elif name == 'release-manifest':
            pathlib.Path('release-manifest.json').write_text(json.dumps(s['manifest']))
        else:
            dest = pathlib.Path(a[a.index('--dir')+1]); dest.mkdir(parents=True, exist_ok=True)
            (dest/'publication-state.json').write_text(json.dumps(s['checkpoint']))
    else: sys.exit(90)
elif tool == 'curl':
    fail('transport')
    if '/token?' in a[-1]: print('{"token":"synthetic-token"}')
    else: print(s.get('status', '200' if s.get('exists') else '404'))
elif tool == 'docker':
    if a[0] == 'save': pathlib.Path(a[a.index('-o')+1]).write_bytes(b'synthetic docker archive')
    elif a[0] == 'login':
        sys.stdin.read(); s['logged_in'] = True; save(); fail('login')
    elif a[0] == 'logout': s['logged_in'] = False; save()
    elif a[0] == 'pull':
        if not s.get('public', True) and not s.get('logged_in'): sys.exit(1)
        fail('pull-channel' if a[1].endswith('garage-test') else 'pull-version')
    elif a[0] == 'push':
        if a[1].endswith(':0.1.0'):
            fail('before-version'); s['exists'] = True; save(); fail('after-version')
        else: fail('channel')
    elif a[:2] == ['image', 'inspect']:
        fmt = a[-1]; remote = a[2].startswith('ghcr.io/')
        if 'RepoDigests' in fmt:
            fail('digest')
            print(json.dumps([s.get('channel', s['digest']) if a[2].endswith('garage-test') else s['digest']]))
        elif 'revision' in fmt: print(s.get('remote_sha', s['sha']) if remote else s['sha'])
        elif 'version' in fmt: print(s.get('remote_version', '0.1.0') if remote else '0.1.0')
        else: print(s.get('remote_id', s['id']) if remote else s['id'])
    elif a[0] not in ('tag', 'load'): sys.exit(91)
else: sys.exit(92)
"""


@pytest.fixture
def cli(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("gh", "docker", "curl", "jq"):
        path = bindir / tool
        path.write_text(MOCK)
        path.chmod(0o700)
    identity = {
        "sha": SHA,
        "version": "0.1.0",
        "image_id": ID,
        "run_id": "123",
        "repository": "example/companion",
        "archive_sha256": hashlib.sha256(ARCHIVE).hexdigest(),
    }
    state = {
        "sha": SHA,
        "id": ID,
        "digest": DIGEST,
        "identity": identity,
        "run": {
            "conclusion": "success",
            "status": "completed",
            "event": "workflow_dispatch",
            "path": ".github/workflows/docker-publish.yml",
            "head_sha": SHA,
            "head_repository": {"full_name": "example/companion"},
        },
        "manifest": {**identity, "digest": DIGEST},
    }
    caller_config = tmp_path / "caller-config"
    caller_config.mkdir()
    (caller_config / "config.json").write_text("synthetic caller sentinel")
    real_jq = shutil.which("jq")
    assert real_jq is not None
    env = {
        **os.environ,
        "PATH": str(bindir) + ":" + os.environ["PATH"],
        "MOCK_ROOT": str(tmp_path),
        "REAL_JQ": real_jq,
        "DOCKER_CONFIG": str(caller_config),
        "RUN_ID": "123",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": SHA,
        "REPOSITORY": "example/companion",
        "GITHUB_REPOSITORY": "example/companion",
        "GH_TOKEN": "synthetic",
        "GITHUB_ACTOR": "synthetic",
        "CANDIDATE_RUN": "123",
        "TMPDIR": str(tmp_path),
        "TEST_COMPANION_IMAGE": "homebox-companion:storage-test",
    }

    def run(script="publish-candidate.sh", overrides=None):
        (tmp_path / "state.json").write_text(json.dumps(state))
        (tmp_path / "calls.jsonl").write_text("")
        work = tmp_path / f"attempt-{len(list(tmp_path.glob('attempt-*')))}"
        work.mkdir()
        (work / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / script)],
            cwd=work,
            env={**env, **(overrides or {})},
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert (caller_config / "config.json").read_text() == "synthetic caller sentinel"
        state.update(json.loads((tmp_path / "state.json").read_text()))
        calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
        return result, calls, work

    return state, run


@pytest.mark.parametrize("overrides", [{"RUN_ID": "124"}, {"REPOSITORY": "attacker/repo"}])
def test_cannot_select_an_external_run_or_repository(cli, overrides):
    _, run = cli
    result, calls, _ = run(overrides=overrides)
    assert result.returncode != 0
    assert calls == []


def test_seal_records_tested_archive_before_upload(cli):
    state, run = cli
    result, _, work = run("seal-tested-image.sh")
    assert result.returncode == 0, result.stderr
    assert json.loads((work / "tested-identity.json").read_text()) == state["identity"]


def pushes(calls):
    return [args[1] for tool, args, _ in calls if tool == "docker" and args[0] == "push"]


def test_interrupted_checkpoint_write_is_not_uploaded(cli):
    state, run = cli
    state["fail"] = "checkpoint-write"
    result, calls, work = run()
    assert result.returncode != 0
    assert pushes(calls) == [IMAGE + ":0.1.0"]
    assert not (work / "publication-state.json").exists()
    state.pop("fail", None)
    result, calls, _ = run()
    assert result.returncode == 0, result.stderr
    assert pushes(calls) == [IMAGE + ":garage-test"]


def test_private_first_push_resumes_same_version(cli):
    state, run = cli
    state["public"] = False
    first, calls, _ = run()
    assert first.returncode != 0
    assert pushes(calls) == [IMAGE + ":0.1.0"]
    state["public"] = True
    result, calls, work = run()
    assert result.returncode == 0, result.stderr
    assert pushes(calls) == [IMAGE + ":garage-test"]
    assert json.loads((work / "release-manifest.json").read_text())["digest"] == DIGEST


@pytest.mark.parametrize(
    "point", ["before-version", "after-version", "digest", "pull-version", "channel", "pull-channel", None]
)
def test_interrupted_publication_resumes_without_version_overwrite(cli, point):
    state, run = cli
    if point:
        state["fail"] = point
    first, _, work = run()
    assert (first.returncode == 0) == (point is None)
    existed = state.get("exists", False)
    checkpoint = work / "publication-state.json"
    if checkpoint.exists():
        state["artifacts"] = [{"name": "publication-state-1", "expired": False}]
        state["checkpoint"] = json.loads(checkpoint.read_text())
    state.pop("fail", None)
    result, calls, work = run()
    assert result.returncode == 0, result.stderr
    assert pushes(calls) == ([] if existed else [IMAGE + ":0.1.0"]) + [IMAGE + ":garage-test"]
    assert (work / "release-manifest.json").exists()
    # A new runner with no local manifest models failed/interrupted artifact upload.


@pytest.mark.parametrize(
    "bad",
    [
        "missing_identity",
        "archive",
        "identity-sha",
        "identity-run",
        "identity-repo",
        "identity-id",
        "identity-version",
        "remote_id",
        "remote_sha",
        "remote_version",
        "401",
        "403",
        "500",
        "transport",
        "api",
        "checkpoint-digest",
        "checkpoint-sha",
        "expired",
        "disappeared",
        "download-release-image",
        "download-publication-state-1",
    ],
)
def test_publication_conflicts_fail_before_any_push(cli, bad):
    state, run = cli
    state["exists"] = True
    if bad == "missing_identity":
        state[bad] = True
    elif bad.startswith("identity-") or bad == "archive":
        field = {
            "archive": "archive_sha256",
            "identity-id": "image_id",
            "identity-run": "run_id",
            "identity-repo": "repository",
        }.get(bad, bad.removeprefix("identity-"))
        state["identity"][field] = "invalid"
    elif bad.startswith("remote_"):
        state[bad] = "invalid"
    elif bad.isdigit():
        state["status"] = bad
    elif bad in ("transport", "api", "download-release-image", "download-publication-state-1"):
        state["fail"] = bad
        if bad == "download-publication-state-1":
            state["artifacts"] = [{"name": "publication-state-1", "expired": False}]
    else:
        state["artifacts"] = [{"name": "publication-state-1", "expired": bad == "expired"}]
        state["checkpoint"] = {**state["identity"], "digest": DIGEST}
        if bad == "checkpoint-digest":
            state["checkpoint"]["digest"] = IMAGE + "@sha256:" + "c" * 64
        elif bad == "checkpoint-sha":
            state["checkpoint"]["sha"] = "0" * 40
        elif bad == "disappeared":
            state["exists"] = False
    result, calls, work = run()
    assert result.returncode != 0
    assert not pushes(calls)
    assert not (work / "release-manifest.json").exists()


@pytest.mark.parametrize("script", ["publish-candidate.sh", "promote-candidate.sh"])
@pytest.mark.parametrize("failure", [None, "login", "channel", "term"])
def test_owned_docker_credentials_cleaned_on_success_and_failure(cli, script, failure):
    state, run = cli
    if failure:
        state["fail"] = failure
    result, calls, _ = run(script)
    assert (result.returncode == 0) == (failure is None)
    configs = {config for tool, args, config in calls if tool == "docker" and args[0] == "login"}
    assert configs and None not in configs
    assert all(not Path(config).exists() for config in configs)
    assert calls[-1][0:2] == ["docker", ["logout", "ghcr.io"]]


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "failed-run",
        "skipped-run",
        "wrong-repository",
        "pull-request",
        "wrong-workflow",
        "manifest-sha",
        "manifest-run",
        "foreign-digest",
        "wrong-image",
        "wrong-label",
        "stale-channel",
        "private",
    ],
)
def test_original_promotion_scenarios(cli, case):
    state, run = cli
    if case == "failed-run":
        state["run"]["conclusion"] = "failure"
    if case == "skipped-run":
        state["run"]["conclusion"] = "skipped"
    if case == "wrong-repository":
        state["run"]["head_repository"]["full_name"] = "attacker/repo"
    if case == "pull-request":
        state["run"]["event"] = "pull_request"
    if case == "wrong-workflow":
        state["run"]["path"] = "other.yml"
    if case == "manifest-sha":
        state["manifest"]["sha"] = "0" * 40
    if case == "manifest-run":
        state["manifest"]["run_id"] = "124"
    if case == "foreign-digest":
        state["manifest"]["digest"] = "ghcr.io/attacker/repo@sha256:" + "a" * 64
    if case == "wrong-image":
        state["remote_id"] = "sha256:" + "c" * 64
    if case == "wrong-label":
        state["remote_sha"] = "0" * 40
    if case == "stale-channel":
        state["channel"] = IMAGE + "@sha256:" + "d" * 64
    if case == "private":
        state["public"] = False
    result, calls, _ = run("promote-candidate.sh")
    assert (result.returncode == 0) == (case == "valid"), result.stderr
    assert bool(pushes(calls)) == (case == "valid")
