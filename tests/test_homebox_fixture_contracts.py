"""Unit contracts for the live Homebox fixture infrastructure."""

from __future__ import annotations

import inspect
import subprocess

import conftest
import httpx
import pytest
from conftest import HOMEBOX_IMAGES, _register_with_retry, _wait_for_demo_seed


class _RegistrationClient:
    def __init__(self, statuses: list[tuple[int, str | None]]) -> None:
        self._statuses = iter(statuses)
        self.payloads: list[dict[str, str]] = []

    def post(self, url: str, *, json: dict[str, str]) -> httpx.Response:
        self.payloads.append(json)
        status, retry_after = next(self._statuses)
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        return httpx.Response(status, headers=headers, request=httpx.Request("POST", url))


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


def test_supported_homebox_images_are_digest_pinned() -> None:
    prefix = "ghcr.io/sysadminsmedia/homebox@sha256:"
    assert set(HOMEBOX_IMAGES) == {"0.27.0", "0.26.2", "0.27.1"}
    assert HOMEBOX_IMAGES["0.27.1"] == (
        "ghcr.io/sysadminsmedia/homebox:0.27.1-rootless@sha256:"
        "0d90e0ea77f582e774e0345892e2daac285c58b612dc380670a86f0648482978"
    )
    assert HOMEBOX_IMAGES["0.27.0"] == prefix + "d49f12caf25ce3fa7f44102bb74953f3dff2dfdad38d87bd9057f3f611e797bb"
    assert HOMEBOX_IMAGES["0.26.2"] == prefix + "b1ad7e3c63f732a5f6daa466e8116be4f545b3b120383a64dcb62beb00a660cc"


@pytest.mark.parametrize("version", ["0.26.2", "0.27.0", "0.27.1"])
def test_isolated_storage_survives_recreation_until_fixture_teardown(
    monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    commands: list[list[str]] = []
    ports = iter(["127.0.0.1:41001", "127.0.0.1:41002"])

    def docker(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        stdout = next(ports) if command[:2] == ["docker", "port"] else "ok"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(conftest.subprocess, "run", docker)
    monkeypatch.setattr(conftest, "_require_docker", lambda: None)
    monkeypatch.setattr(conftest, "_wait_for_status", lambda server: None)
    monkeypatch.setattr(conftest, "_assert_homebox_version", lambda url, expected: None)
    fixture = inspect.unwrap(conftest.isolated_homebox_server)(version, HOMEBOX_IMAGES[version])
    server = next(fixture)
    try:
        assert server.volume is not None
        assert server.volume.startswith("homebox-isolated-data-")
        old_url = server.base_url
        server.restart()
        assert server.base_url != old_url
        runs = [command for command in commands if command[:2] == ["docker", "run"]]
        assert len(runs) == 2
        for command in runs:
            assert command[command.index("-v") + 1] == f"{server.volume}:/data"
            assert "--tmpfs" not in command
            assert "--user" not in command  # Keep the pinned image's rootless identity and volume copy-up.
            assert command[-1] == HOMEBOX_IMAGES[version]
            assert "127.0.0.1::7745" in command
        assert ["docker", "rm", "--force", server.name] in commands
        assert not any(command[:3] == ["docker", "volume", "rm"] for command in commands)
    finally:
        fixture.close()
    assert commands[-2:] == [
        ["docker", "rm", "--force", "--volumes", server.name],
        ["docker", "volume", "rm", "--force", server.volume],
    ]


def test_registration_retries_only_429_with_same_payload_and_retry_after() -> None:
    client = _RegistrationClient([(429, "3"), (429, "0.5"), (204, None)])
    clock = _FakeClock()
    payload = {"name": "Test", "email": "test@example.invalid", "password": "secret"}

    response = _register_with_retry(
        client, "https://homebox.test/register", payload, sleep=clock.sleep, monotonic=clock.monotonic
    )

    assert response.status_code == 204
    assert clock.delays == [3.0, 0.5]
    assert client.payloads == [payload, payload, payload]
    assert all(sent is payload for sent in client.payloads)


def test_registration_does_not_retry_other_failures() -> None:
    client = _RegistrationClient([(503, "10")])
    clock = _FakeClock()

    response = _register_with_retry(
        client, "https://homebox.test/register", {}, sleep=clock.sleep, monotonic=clock.monotonic
    )

    assert response.status_code == 503
    assert clock.delays == []
    assert len(client.payloads) == 1


def test_registration_retry_is_bounded() -> None:
    client = _RegistrationClient([(429, "1")] * 4)
    clock = _FakeClock()

    response = _register_with_retry(
        client, "https://homebox.test/register", {}, sleep=clock.sleep, monotonic=clock.monotonic
    )

    assert response.status_code == 429
    assert clock.delays == [1.0, 1.0, 1.0]
    assert len(client.payloads) == 4


def test_registration_retry_wait_budget_and_invalid_delay_are_bounded() -> None:
    clock = _FakeClock()
    client = _RegistrationClient([(429, "nan"), (429, "121"), (204, None)])

    response = _register_with_retry(
        client,
        "https://homebox.test/register",
        {},
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        max_wait=180,
    )

    assert response.status_code == 429
    assert clock.delays == [60.0]
    assert len(client.payloads) == 2


def test_demo_seed_gate_waits_for_completion_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter(
        [
            subprocess.CompletedProcess([], 0, "starting", ""),
            subprocess.CompletedProcess([], 0, "true running 0", ""),
            subprocess.CompletedProcess([], 0, "Demo setup complete", ""),
        ]
    )
    clock = _FakeClock()
    monkeypatch.setattr("conftest.subprocess.run", lambda *args, **kwargs: next(calls))

    _wait_for_demo_seed("homebox-test", sleep=clock.sleep, monotonic=clock.monotonic)

    assert clock.delays == [0.5]


def test_demo_seed_gate_fails_promptly_when_container_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter(
        [
            subprocess.CompletedProcess([], 0, "partial seed log", ""),
            subprocess.CompletedProcess([], 0, "false exited 1", ""),
        ]
    )
    monkeypatch.setattr("conftest.subprocess.run", lambda *args, **kwargs: next(calls))

    with pytest.raises(pytest.fail.Exception, match="exited before demo setup completed"):
        _wait_for_demo_seed("homebox-test", sleep=lambda _: None)
