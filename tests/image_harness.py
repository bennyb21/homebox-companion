"""Opt-in Linux image runner. Only provider stubs are mounted, never application source.

The production image has neither this entrypoint nor a fake-provider switch.
The host network reaches the isolated loopback Homebox/provider fixtures only.
"""

import ast
import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


def image_command(test_file, port, work, env):
    image = os.environ["TEST_COMPANION_IMAGE"]
    source = Path(test_file).read_text()
    body = textwrap.dedent(source.split('if __name__ == "__main__":\n', 1)[1])
    body = body.replace(
        "with pytest.MonkeyPatch.context() as monkeypatch:",
        "with patch.object(detector, 'vision_completion', fixed_completion), "
        "patch.object(corrector, 'vision_completion', fixed_completion):",
    )
    body = "\n".join(line for line in body.splitlines() if "monkeypatch.setattr" not in line)
    body = body.replace("from test_research_evidence import response", "")
    fixture = (ROOT / "tests/test_research_evidence.py").read_text()
    response = next(n for n in ast.parse(fixture).body if isinstance(n, ast.FunctionDef) and n.name == "response")
    script = "import os, sys, json\nfrom pathlib import Path\nfrom unittest.mock import patch\nimport httpx\n"
    response_source = ast.get_source_segment(fixture, response)
    assert response_source is not None
    script += response_source + "\n" + body
    script = script.replace('Path("dispatches.txt")', 'Path("data/dispatches.txt")')
    overlay = work / "image-entrypoint.py"
    overlay.write_text(script)
    data = work / "data"
    data.mkdir(exist_ok=True)
    data.chmod(0o777)
    # pytest temp parents are private; Docker mounts the leaf directly.
    work.chmod(0o777)
    command = DOCKER + [
        "run",
        "--rm",
        "--network",
        "host",
        "--workdir",
        "/app",
        "--mount",
        f"type=bind,src={data},dst=/app/data",
        "--mount",
        f"type=bind,src={overlay},dst=/image-entrypoint.py,readonly",
    ]
    for key, value in env.items():
        if key.startswith("HBC_") or key == "LITELLM_LOCAL_MODEL_COST_MAP":
            command += ["-e", f"{key}={value}"]
    command += [image, "/app/.venv/bin/python", "/image-entrypoint.py", str(port), "/app/server/static"]
    return command


def start_server(test_file, port, build, work, env, log):
    import sys

    command = [sys.executable, str(test_file), str(port), str(build)]
    if os.environ.get("TEST_COMPANION_IMAGE"):
        command = image_command(test_file, port, work, env)
        env = {k: v for k, v in env.items() if k not in ("DOCKER_CONTEXT", "DOCKER_HOST")}
    return subprocess.Popen(command, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
