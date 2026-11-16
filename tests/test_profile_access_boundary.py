"""Compare metadata access with the unchanged SDK's actual provider model ID."""

import json
import socket

import httpx
import httpx2
import pytest
import test_model_configuration as fixtures
from pydantic import SecretStr

from homebox_companion.ai.llm import vision_completion
from homebox_companion.core import config, llm_router
from homebox_companion.core import persistent_settings as ps
from server.app import create_app
from server.dependencies import require_auth

disk = fixtures.disk


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["own", "profile", "env"])
@pytest.mark.parametrize("model", ["gpt-4.1", "openai/gpt-4.1", "gpt-6-terra", "openai/gpt-6-terra"])
async def test_metadata_id_matches_actual_sdk_without_mutating_saved_literal(disk, monkeypatch, source, model):
    network = []
    wire = []

    def forbidden(*args, **kwargs):
        network.append(True)
        raise AssertionError("No real network allowed")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.invalid/v1")
    monkeypatch.setenv("OPENAI_API_BASE", "https://ambient.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-AMBIENT")
    # Unknown models remain unverified; opt in only to offline SDK serialization.
    monkeypatch.setattr(config.settings, "llm_allow_unsafe_models", True)
    settings = ps.load_settings()
    settings.llm_profiles[0].status = ps.ProfileStatus.OFF
    settings.llm_profiles.append(
        ps.ModelProfile(
            name="target",
            model=model,
            status=ps.ProfileStatus.PRIMARY,
            credential_source=source,
            credential_profile_name="capture" if source == "profile" else None,
            api_key=SecretStr("SYNTHETIC-OWN") if source == "own" else None,
        )
    )
    ps.save_settings(settings)
    before = disk.read_bytes()
    expected_id = model.removeprefix("openai/")
    expected_key = {"own": "SYNTHETIC-OWN", "profile": "OWN-secret", "env": "ENV-secret"}[source]
    original_send = httpx.AsyncClient.send

    async def intercepted(client, request, **kwargs):
        if request.url.host == "test":
            return await original_send(client, request, **kwargs)
        wire.append(request)
        assert request.headers["authorization"] == f"Bearer {expected_key}"
        cls = httpx2.Response if isinstance(request, httpx2.Request) else httpx.Response
        if request.method == "GET":
            return cls(200, request=request, json={"id": expected_id, "object": "model"})
        body = json.loads(request.content)
        return cls(
            200,
            request=request,
            json={
                "id": "chatcmpl_synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", intercepted)
    monkeypatch.setattr(httpx2.AsyncClient, "send", intercepted)
    app = create_app(config.settings, static_directory=str(disk.parent / "no-static"))
    app.dependency_overrides[require_auth] = lambda: None
    llm_router.invalidate_router()
    try:
        await vision_completion("Identify", "item", ["data:image/png;base64,c3ludGhldGlj"])
        assert len(wire) == 1
        assert str(wire[0].url) == "https://api.openai.com/v1/chat/completions"
        assert json.loads(wire[0].content)["model"] == expected_id
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/llm/profiles/target/test", json={})
            rows = (await client.get("/api/llm/profiles")).json()["profiles"]
        assert response.status_code == 200
        assert len(wire) == 2  # Exactly one metadata GET, no completion fallback.
        assert wire[1].method == "GET"
        assert str(wire[1].url) == f"https://api.openai.com/v1/models/{expected_id}"
        assert response.json()["success"] is True
        assert next(p for p in rows if p["name"] == "target")["model"] == model
        assert response.json()["model_info"]["model"] == model
        assert disk.read_bytes() == before
        assert network == []
    finally:
        llm_router.invalidate_router()


@pytest.mark.parametrize(
    "literal,expected",
    [
        ("gpt-4.1", "gpt-4.1"),
        ("openai/gpt-4.1", "gpt-4.1"),
        ("openai/gpt-6-terra", "gpt-6-terra"),
        ("openai/gpt-Future.Experimental_1", "gpt-Future.Experimental_1"),
        ("openai/o3", "o3"),
        ("openai/openai/gpt-4.1", None),
        ("OpenAI/gpt-4.1", None),
        ("other/gpt-4.1", None),
        ("openai/GPT-4.1", None),
        ("openai/", None),
        ("gpt-4.1/extra", None),
        (" gpt-4.1", None),
        ("gpt-4.1?query", None),
    ],
)
def test_provider_id_uses_existing_case_sensitive_grammar_exactly_once(literal, expected):
    from homebox_companion.core.credential_policy import OPENAI_BASE, official_openai_model_id

    for base in (None, "", OPENAI_BASE):
        assert official_openai_model_id(literal, base) == expected
    assert official_openai_model_id(literal, "https://custom.invalid/v1") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["OpenAI/gpt-4.1", "other/gpt-4.1", "openai/openai/gpt-4.1", "gpt-4.1/extra"])
async def test_invalid_model_override_cannot_dispatch_stored_credentials(disk, monkeypatch, model):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid override must not dispatch")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    app = create_app(config.settings, static_directory=str(disk.parent / "no-static"))
    app.dependency_overrides[require_auth] = lambda: None
    before = disk.read_bytes()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/llm/profiles/capture/test", json={"model": model})
    assert response.status_code == 400
    assert disk.read_bytes() == before
