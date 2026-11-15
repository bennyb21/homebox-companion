"""Research settings reuse credentials without testing a paid provider."""

from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from homebox_companion.core import persistent_settings
from homebox_companion.core.persistent_settings import ModelProfile, PersistentSettings, ProfileStatus
from server.api import llm_profiles
from server.dependencies import require_auth


@asynccontextmanager
async def client_for_settings(authenticated=True):
    app = FastAPI()
    app.include_router(llm_profiles.router, prefix="/api")
    if authenticated:
        app.dependency_overrides[require_auth] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def disk(tmp_path, monkeypatch):
    monkeypatch.setattr(persistent_settings, "SETTINGS_FILE", tmp_path / "settings.yaml")
    persistent_settings.clear_settings_cache()
    settings = PersistentSettings(
        llm_profiles=[
            ModelProfile(
                name="existing", model="gpt-4.1", api_key=SecretStr("synthetic-only-key"), status=ProfileStatus.PRIMARY
            )
        ]
    )
    persistent_settings.save_settings(settings)

    # A config read/write must never probe or run any LLM.
    async def forbidden(*args, **kwargs):
        pytest.fail("Settings must not dispatch a paid provider call")

    monkeypatch.setattr(llm_profiles.litellm, "acompletion", forbidden)
    monkeypatch.setattr(llm_profiles.litellm, "aresponses", forbidden)
    yield tmp_path / "settings.yaml"
    persistent_settings.clear_settings_cache()


@pytest.mark.asyncio
async def test_enable_reuses_sole_eligible_profile_and_persists_without_secret_response(disk):
    async with client_for_settings() as client:
        initial = await client.get("/api/settings/research")
        assert initial.status_code == 200
        assert initial.json()["enabled"] is False
        assert initial.json()["profiles"][0]["eligible"] is True
        saved = await client.put("/api/settings/research", json={"enabled": True, "profile_name": None})
        assert saved.status_code == 200
        assert saved.json()["profile_name"] == "existing"
        reread = await client.get("/api/settings/research")
        assert reread.json()["enabled"] is True
        assert "synthetic-only-key" not in initial.text + saved.text + reread.text
    settings = persistent_settings.load_settings()
    assert settings.research_profile_name == "existing"
    assert settings.research_enabled is True
    assert settings.llm_profiles[0].api_key is not None
    assert settings.llm_profiles[0].api_key.get_secret_value() == "synthetic-only-key"
    assert len(settings.llm_profiles) == 1


@pytest.mark.asyncio
async def test_multiple_profiles_require_selection_and_unsuitable_is_rejected(disk):
    def add(settings):
        settings.llm_profiles.extend(
            [
                ModelProfile(name="second", model="gpt-4.1", api_key=SecretStr("second-synthetic")),
                ModelProfile(name="other", model="anthropic/claude-sonnet-4", api_key=SecretStr("not-openai")),
            ]
        )

    persistent_settings.mutate_settings(add)
    before = disk.read_bytes()
    async with client_for_settings() as client:
        for name in [None, "other", "missing"]:
            rejected = await client.put("/api/settings/research", json={"enabled": True, "profile_name": name})
            assert rejected.status_code == 400
            assert disk.read_bytes() == before
        response = await client.put("/api/settings/research", json={"enabled": True, "profile_name": "second"})
        assert response.status_code == 200
        assert response.json()["profile_name"] == "second"
        disabled = await client.put("/api/settings/research", json={"enabled": False, "profile_name": "second"})
        assert disabled.json()["enabled"] is False
        assert (await client.get("/api/settings/research")).json()["profile_name"] == "second"


@pytest.mark.asyncio
async def test_research_settings_reject_secret_payload_and_require_existing_auth_policy(disk):
    from fastapi import HTTPException

    from server.dependencies import get_authenticated_user

    app = FastAPI()
    app.include_router(llm_profiles.router, prefix="/api")

    def unauthenticated():
        raise HTTPException(401, "Not authenticated")

    app.dependency_overrides[get_authenticated_user] = unauthenticated
    before = disk.read_bytes()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/settings/research")).status_code == 401
        assert (await client.put("/api/settings/research", json={"enabled": True})).status_code == 401
    async with client_for_settings() as client:
        response = await client.put("/api/settings/research", json={"enabled": True, "api_key": "do-not-copy"})
        assert response.status_code == 422
    assert disk.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"api_base": "https://example.invalid/v1"},
        {"api_key": None},
        {"model": "gpt-4o"},
        {"model": "unknown-model"},
        {"model": "openai/gpt-4.1"},
    ],
)
async def test_ineligible_profiles_explain_and_cannot_enable(disk, updates):
    def update(settings):
        for key, value in updates.items():
            setattr(settings.llm_profiles[0], key, value)

    persistent_settings.mutate_settings(update)
    async with client_for_settings() as client:
        result = (await client.get("/api/settings/research")).json()
        assert result["profiles"][0]["eligible"] is False
        assert result["profiles"][0]["reason"]
        assert (await client.put("/api/settings/research", json={"enabled": True})).status_code == 400
