"""Offline model configuration acceptance; synthetic credentials only."""

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr

from homebox_companion.core import config
from homebox_companion.core import persistent_settings as ps
from homebox_companion.core.llm_utils import resolve_llm_credentials
from server.api import llm_profiles
from server.dependencies import require_auth


@pytest.fixture
def disk(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "SETTINGS_FILE", tmp_path / "settings.yaml")
    monkeypatch.setattr(
        config, "settings", config.Settings(_env_file=None, llm_model="gpt-4.1", llm_api_key="ENV-secret")
    )
    ps.clear_settings_cache()
    ps.save_settings(
        ps.PersistentSettings(
            llm_profiles=[
                ps.ModelProfile(
                    name="capture", model="gpt-4.1", api_key=SecretStr("OWN-secret"), status=ps.ProfileStatus.PRIMARY
                )
            ]
        )
    )
    yield tmp_path / "settings.yaml"
    ps.clear_settings_cache()


@pytest_asyncio.fixture
async def client(disk):
    app = FastAPI()
    app.include_router(llm_profiles.router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("ambient_base", ["OPENAI_BASE_URL", "OPENAI_API_BASE"])
@pytest.mark.parametrize(
    ("source", "saved_base"),
    [
        ("profile", None),
        ("env", None),
        ("profile", "https://api.openai.com/v1"),
        ("env", "https://api.openai.com/v1"),
        ("own", "https://custom-owned.invalid/v1"),
    ],
)
async def test_connection_credential_destination_on_actual_sdk_wire(
    client, disk, monkeypatch, ambient_base, source, saved_base
):
    """The manually requested test must honor the same destination boundary as inference."""
    import json
    import socket

    import openai
    from litellm.llms.openai.openai import OpenAIChatCompletion

    calls = []
    sdk_clients = []

    def forbid_network(*args, **kwargs):
        raise AssertionError("Real network forbidden in credential destination regression")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid_network)
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ambient_base, "https://stale-gateway.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-AMBIENT")

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "connection successful"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def sdk(_self, **kwargs):
        actual = openai.AsyncOpenAI(
            api_key=kwargs["api_key"],
            base_url=kwargs["api_base"],
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        sdk_clients.append(actual)
        return actual

    monkeypatch.setattr(OpenAIChatCompletion, "_get_openai_client", sdk)
    created = await client.post(
        "/api/llm/profiles",
        json={
            "name": "test-target",
            "model": "gpt-6-luna",
            "status": "off",
            "credential_source": source,
            "credential_profile_name": "capture" if source == "profile" else None,
            "api_key": "SYNTHETIC-CUSTOM" if source == "own" else None,
            "api_base": saved_base,
        },
    )
    assert created.status_code == 201
    assert calls == []  # Saving never issues a capability probe.
    try:
        response = await client.post("/api/llm/profiles/test-target/test", json={})
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert len(calls) == 1
        expected_base = saved_base or "https://api.openai.com/v1"
        assert str(calls[0].url) == f"{expected_base}/chat/completions"
        key = {"profile": "OWN-secret", "env": "ENV-secret", "own": "SYNTHETIC-CUSTOM"}[source]
        assert calls[0].headers["authorization"] == f"Bearer {key}"
        assert json.loads(calls[0].content)["model"] == "gpt-6-luna"
        for secret in (key, "SYNTHETIC-AMBIENT"):
            assert secret not in response.text
            assert secret not in created.text
    finally:
        for actual in sdk_clients:
            await actual.close()


@pytest.mark.asyncio
async def test_dedicated_research_reuses_reference_without_demoting_primary(client, disk):
    r = await client.post(
        "/api/llm/profiles",
        json={
            "name": "research",
            "model": "gpt-6-luna",
            "status": "research",
            "credential_source": "profile",
            "credential_profile_name": "capture",
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["has_api_key"] is True
    assert data["credential_source"] == "profile"
    assert data["research_assigned"] is True
    settings = ps.load_settings()
    assert settings.research_profile_name == "research"
    assert settings.llm_profiles[0].status == ps.ProfileStatus.PRIMARY
    assert settings.llm_profiles[1].api_key is None
    assert disk.read_text().count("OWN-secret") == 1
    assert "OWN-secret" not in r.text
    assert resolve_llm_credentials().model == "gpt-4.1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"credential_profile_name": "missing"},
        {"credential_profile_name": "research"},
        {"model": "anthropic/claude-sonnet-4"},
        {"api_base": "https://evil.invalid/v1"},
        {"api_base": "https://api.openai.com/v1/"},
        {"credential_source": "env", "credential_profile_name": "capture"},
        {"research_reasoning_effort": "minimal"},
    ],
)
async def test_invalid_reference_is_atomic(client, disk, changes):
    before = disk.read_bytes()
    payload = {
        "name": "research",
        "model": "gpt-6-luna",
        "status": "research",
        "credential_source": "profile",
        "credential_profile_name": "capture",
        **changes,
    }
    r = await client.post("/api/llm/profiles", json=payload)
    assert r.status_code == 400, r.text
    assert disk.read_bytes() == before
    assert "secret" not in r.text


@pytest.mark.asyncio
async def test_reference_rename_delete_and_research_selection_lifecycle(client, disk):
    assert (
        await client.post(
            "/api/llm/profiles",
            json={
                "name": "research",
                "model": "gpt-6-luna",
                "status": "research",
                "credential_source": "profile",
                "credential_profile_name": "capture",
            },
        )
    ).status_code == 201
    assert (await client.delete("/api/llm/profiles/capture")).status_code == 400
    assert (await client.put("/api/llm/profiles/capture", json={"new_name": "renamed"})).status_code == 200
    assert ps.load_settings().llm_profiles[1].credential_profile_name == "renamed"
    # Switching the selector preserves capture role and retires only dedicated Research.
    r = await client.put("/api/settings/research", json={"enabled": True, "profile_name": "renamed"})
    assert r.status_code == 200, r.text
    settings = ps.load_settings()
    assert settings.llm_profiles[0].status == ps.ProfileStatus.PRIMARY
    assert settings.llm_profiles[1].status == ps.ProfileStatus.OFF
    assert (await client.put("/api/llm/profiles/renamed", json={"status": "research"})).status_code == 400
    assert (await client.delete("/api/llm/profiles/research")).status_code == 204


@pytest.mark.asyncio
async def test_update_key_reference_and_reasoning_survive_reload(client, disk):
    await client.post("/api/llm/profiles", json={"name": "research", "model": "gpt-6-luna", "status": "research"})
    r = await client.put(
        "/api/llm/profiles/research",
        json={
            "credential_source": "profile",
            "credential_profile_name": "capture",
            "research_reasoning_effort": "high",
        },
    )
    assert r.status_code == 200, r.text
    ps.clear_settings_cache()
    p = ps.load_settings().llm_profiles[1]
    assert p.credential_source == "profile"
    assert p.research_reasoning_effort == "high"
    assert (await client.put("/api/llm/profiles/research", json={"new_name": "renamed"})).status_code == 200
    assert ps.load_settings().research_profile_name == "renamed"
    assert (await client.delete("/api/llm/profiles/renamed")).status_code == 204
    assert ps.load_settings().research_profile_name is None


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", [None, "none", "low", "medium", "high", "xhigh", "max"])
async def test_research_reference_reasoning_on_actual_sdk_wire(client, disk, effort):
    import json

    from starlette.requests import Request

    from homebox_companion.research import ProductIdentity
    from server.api.research import provider as get_research_provider

    r = await client.post(
        "/api/llm/profiles",
        json={
            "name": "research",
            "model": "gpt-6-luna",
            "status": "research",
            "credential_source": "profile",
            "credential_profile_name": "capture",
            "research_reasoning_effort": effort,
        },
    )
    assert r.status_code == 201, r.text
    r = await client.put("/api/settings/research", json={"enabled": True, "profile_name": "research"})
    assert r.status_code == 200, r.text
    ps.clear_settings_cache()
    provider = get_research_provider(Request({"type": "http", "app": FastAPI()}))
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "synthetic", "type": "server_error"}})

    provider.transport = httpx.MockTransport(respond)
    result = await provider.research(
        ProductIdentity(identifier_kind="part_number", identifier_exact="AB-123", identity_confirmed=True)
    )
    assert result.status == "unknown_outcome"
    assert len(calls) == 1
    assert str(calls[0].url) == "https://api.openai.com/v1/responses"
    assert calls[0].headers["authorization"] == "Bearer OWN-secret"
    body = json.loads(calls[0].content)
    assert body["model"] == "gpt-6-luna"
    if effort is None:
        assert "reasoning" not in body
    else:
        assert body["reasoning"] == {"effort": effort}
    assert body["max_output_tokens"] == 2400
    assert body["max_tool_calls"] == 1


@pytest.mark.asyncio
async def test_effective_display_and_actual_vision_chat_wire_refresh_and_restart(client, disk, monkeypatch):
    import json

    from starlette.requests import Request

    from homebox_companion.ai.llm import vision_completion
    from homebox_companion.chat.llm_client import LLMClient
    from homebox_companion.core import llm_router
    from server.api.config import get_config

    app = FastAPI()
    app.state.settings = config.settings
    calls = []

    async def send(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chat_synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": json.loads(request.content)["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    # SDK now also supports httpx2; inject a real SDK with a mock HTTP transport
    # rather than patching one HTTP implementation's default transport.
    import openai
    from litellm.llms.openai.openai import OpenAIChatCompletion

    def sdk(_self, **kwargs):
        return openai.AsyncOpenAI(
            api_key=kwargs["api_key"],
            base_url=kwargs["api_base"],
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(send)),
        )

    monkeypatch.setattr(OpenAIChatCompletion, "_get_openai_client", sdk)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "inspect_item",
                "description": "Inspect",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    for model in ["gpt-6-luna", "gpt-4.1-mini"]:
        assert (await client.put("/api/llm/profiles/capture", json={"model": model})).status_code == 200
        display = (await get_config(Request({"type": "http", "app": app}))).model_dump()
        assert display["llm_model"] == model
        assert display["llm_model_source"] == "profile"
        assert display["llm_profile_name"] == "capture"
        for restart in [False, True]:
            if restart:
                ps.clear_settings_cache()
                llm_router.invalidate_router()
            await vision_completion("Identify", "item", ["data:image/png;base64,c3ludGhldGlj"])
            await LLMClient().complete([{"role": "user", "content": "Inspect"}], tools)
            bodies = [json.loads(r.content) for r in calls[-2:]]
            assert [b["model"] for b in bodies] == [model, model]
            assert all(r.headers["authorization"] == "Bearer OWN-secret" for r in calls[-2:])
            assert all(str(r.url) == "https://api.openai.com/v1/chat/completions" for r in calls[-2:])
            assert bodies[0]["messages"][1]["content"][1]["type"] == "image_url"
            if model == "gpt-6-luna":
                assert bodies[1]["reasoning_effort"] == "none"
            assert "reasoning" not in bodies[1]
    assert len(calls) == 8


@pytest.mark.asyncio
async def test_research_only_first_profile_does_not_enter_capture_router(client, disk):
    from homebox_companion.core import llm_router

    await client.delete("/api/llm/profiles/capture")
    r = await client.post(
        "/api/llm/profiles",
        json={"name": "only", "model": "gpt-6-luna", "status": "research", "credential_source": "env"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "research"
    assert resolve_llm_credentials().profile_name is None
    assert resolve_llm_credentials().model == "gpt-4.1"
    assert len(llm_router.get_router().model_list) == 1
    # Replacing a research-only selection retires the old role to Off, without
    # inventing a capture Primary or losing environment capture routing.
    replacement = await client.post(
        "/api/llm/profiles",
        json={"name": "replacement", "model": "gpt-6-luna", "status": "research", "credential_source": "env"},
    )
    assert replacement.status_code == 201, replacement.text
    assert ps.get_settings().llm_profiles[0].status == ps.ProfileStatus.OFF
    cleared = await client.put("/api/settings/research", json={"enabled": False, "profile_name": None})
    assert cleared.status_code == 200, cleared.text
    assert all(p.status == ps.ProfileStatus.OFF for p in ps.get_settings().llm_profiles)
    assert resolve_llm_credentials().profile_name is None
    assert llm_router.get_router().model_list[0]["litellm_params"]["model"] == "gpt-4.1"
    assert (await client.delete("/api/llm/profiles/replacement")).status_code == 204
    assert (await client.delete("/api/llm/profiles/only")).status_code == 204
    assert resolve_llm_credentials().profile_name is None
    assert llm_router.get_router().model_list[0]["litellm_params"]["model"] == "gpt-4.1"


def test_legacy_migration_preserves_secrets_and_only_safe_env_inheritance(disk):
    import yaml

    legacy = {
        "version": 3,
        "llm_profiles": [
            {"name": "capture", "model": "gpt-4.1", "status": "primary", "api_key": "OWN-secret"},
            {"name": "safe", "model": "gpt-6-luna", "status": "off"},
            {"name": "unsafe", "model": "gpt-6-luna", "api_base": "https://evil.invalid", "status": "off"},
        ],
    }
    disk.write_text(yaml.safe_dump(legacy))
    ps.clear_settings_cache()
    settings = ps.load_settings()
    assert settings.llm_profiles[0].api_key is not None
    assert settings.llm_profiles[0].api_key.get_secret_value() == "OWN-secret"
    assert settings.llm_profiles[1].credential_source == "env"
    assert settings.llm_profiles[2].credential_source == "own"
    assert disk.read_text().count("OWN-secret") == 1


@pytest.mark.asyncio
async def test_incompatible_environment_reference_rejected_and_test_override_cannot_leak(client, disk, monkeypatch):
    monkeypatch.setattr(config.settings, "llm_model", "anthropic/claude-sonnet-4")
    r = await client.post("/api/llm/profiles", json={"name": "env", "model": "gpt-6-luna", "credential_source": "env"})
    assert r.status_code == 400

    # Even an explicit connection-test endpoint must not send a saved key to a new destination.
    async def forbidden(**kwargs):
        pytest.fail("Test override leaked a saved key")

    monkeypatch.setattr(llm_profiles.litellm, "acompletion", forbidden)
    r = await client.post("/api/llm/profiles/capture/test", json={"api_base": "https://evil.invalid"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_custom_primary_does_not_inherit_environment_key_or_base(client, disk, monkeypatch):
    from homebox_companion.core import llm_router

    assert (
        await client.put("/api/llm/profiles/capture", json={"api_key": "", "api_base": "https://custom.invalid/v1"})
    ).status_code == 200
    creds = resolve_llm_credentials()
    assert creds.api_key is None
    router = llm_router.get_router()
    assert router.model_list[0]["litellm_params"].get("api_key") != "ENV-secret"
    assert (
        await client.post(
            "/api/llm/profiles", json={"name": "fallback", "model": "anthropic/claude-sonnet-4", "status": "fallback"}
        )
    ).status_code == 201
    assert llm_router.get_router().model_list[1]["litellm_params"].get("api_key") not in {"OWN-secret", "ENV-secret"}


@pytest.mark.asyncio
async def test_reference_chain_cycle_provider_edit_and_clear_selected_key_are_atomic(client, disk):
    for name, source in [("research", "capture"), ("chain", "research")]:
        r = await client.post(
            "/api/llm/profiles",
            json={
                "name": name,
                "model": "gpt-6-luna",
                "status": "research",
                "credential_source": "profile",
                "credential_profile_name": source,
            },
        )
        assert r.status_code == (201 if name == "research" else 400)
    before = disk.read_bytes()
    for changes in [
        {"credential_source": "profile", "credential_profile_name": "research"},
        {"model": "anthropic/claude-sonnet-4"},
        {"api_base": "https://evil.invalid/v1"},
    ]:
        assert (await client.put("/api/llm/profiles/capture", json=changes)).status_code == 400
        assert disk.read_bytes() == before
    assert (
        await client.put("/api/settings/research", json={"enabled": True, "profile_name": "research"})
    ).status_code == 200
    before = disk.read_bytes()
    assert (await client.put("/api/llm/profiles/capture", json={"api_key": ""})).status_code == 400
    assert disk.read_bytes() == before
    assert (
        await client.put("/api/settings/research", json={"enabled": False, "profile_name": "research"})
    ).status_code == 200
    assert (await client.put("/api/llm/profiles/capture", json={"api_key": ""})).status_code == 200
    assert not (await client.get("/api/llm/profiles")).json()["profiles"][1]["has_api_key"]


@pytest.mark.asyncio
async def test_own_key_retained_and_environment_reference_revalidated_at_runtime(client, disk, monkeypatch):
    from homebox_companion.core.llm_utils import resolve_profile_key

    r = await client.put("/api/llm/profiles/capture", json={"model": "gpt-6-luna", "api_key": None})
    assert r.status_code == 200
    assert "OWN-secret" not in r.text
    saved_key = ps.load_settings().llm_profiles[0].api_key
    assert saved_key is not None and saved_key.get_secret_value() == "OWN-secret"
    r = await client.post(
        "/api/llm/profiles",
        json={"name": "environment", "model": "gpt-6-luna", "status": "off", "credential_source": "env"},
    )
    assert r.status_code == 201
    p = ps.load_settings().llm_profiles[1]
    assert p.api_key is None
    assert resolve_profile_key(p) == "ENV-secret"
    monkeypatch.setattr(config.settings, "llm_api_base", "https://evil.invalid/v1")
    assert resolve_profile_key(p) is None
    assert not (await client.get("/api/llm/profiles")).json()["profiles"][1]["has_api_key"]


def test_router_build_cannot_reinstall_stale_credentials_after_save(disk, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from homebox_companion.core import llm_router

    entered, release = Event(), Event()
    original = llm_router._build_router_from_profiles

    def paused():
        value = original()
        entered.set()
        assert release.wait(5)
        return value

    monkeypatch.setattr(llm_router, "_build_router_from_profiles", paused)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(llm_router.get_router)
        assert entered.wait(5)
        saved = pool.submit(
            ps.mutate_settings, lambda settings: setattr(settings.llm_profiles[0], "model", "gpt-6-luna")
        )
        release.set()
        old = first.result(5)
        saved.result(5)
    new = llm_router.get_router()
    assert new is not old
    assert new.model_list[0]["litellm_params"]["model"] == "gpt-6-luna"


@pytest.mark.asyncio
async def test_fresh_process_restart_uses_persisted_ui_models_on_all_three_wires(client, disk):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    assert (await client.put("/api/llm/profiles/capture", json={"model": "gpt-6-luna"})).status_code == 200
    assert (
        await client.post(
            "/api/llm/profiles",
            json={
                "name": "research",
                "model": "gpt-6-luna",
                "status": "research",
                "credential_source": "profile",
                "credential_profile_name": "capture",
                "research_reasoning_effort": "high",
            },
        )
    ).status_code == 201
    assert (
        await client.put("/api/settings/research", json={"enabled": True, "profile_name": "research"})
    ).status_code == 200
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("model_restart_probe.py")), str(disk)],
        env={
            **os.environ,
            "HBC_LLM_MODEL": "gpt-4.1",
            "HBC_LLM_API_KEY": "ENV-secret",
            "HBC_RATE_LIMIT_ENABLED": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    wire = json.loads(result.stdout.strip().splitlines()[-1])
    assert wire["model"] == "gpt-6-luna"
    assert wire["source"] == "profile"
    assert [c["body"]["model"] for c in wire["calls"]] == ["gpt-6-luna"] * 3
    assert wire["calls"][1]["body"]["reasoning_effort"] == "none"
    assert wire["calls"][2]["body"]["reasoning"] == {"effort": "high"}
    assert wire["calls"][2]["url"] == "https://api.openai.com/v1/responses"


def test_new_official_openai_bootstrap_references_environment_without_copying_secret(disk):
    settings = ps.bootstrap_from_env()
    assert settings.llm_profiles[0].credential_source == "env"
    assert settings.llm_profiles[0].api_key is None
    ps.save_settings(settings)
    assert "ENV-secret" not in disk.read_text()
    assert resolve_llm_credentials().api_key == "ENV-secret"


def test_queued_research_policy_binds_reasoning_and_credential_reference():
    from types import SimpleNamespace

    from server.api.research_jobs import policy_hash

    p = ps.ModelProfile(name="research", model="gpt-6-luna")
    initial = policy_hash(SimpleNamespace(profile=p))
    p.research_reasoning_effort = "high"
    assert policy_hash(SimpleNamespace(profile=p)) != initial
    p.research_reasoning_effort = None
    p.credential_source = "profile"
    p.credential_profile_name = "capture"
    assert policy_hash(SimpleNamespace(profile=p)) != initial
