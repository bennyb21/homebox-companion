"""Request validation privacy through create_app, not DTO-only validation."""

import io
import json
import socket

import httpx
import pytest
import pytest_asyncio
import test_model_configuration as fixtures
from fastapi.exceptions import RequestValidationError
from loguru import logger
from pydantic import BaseModel, model_validator

from homebox_companion.core import config
from server.app import create_app
from server.dependencies import get_verified_gateway, require_auth

disk = fixtures.disk
KEY = "KEY-VALIDATION-CANARY"
QUERY = "QUERY-VALIDATION-CANARY"
IDENTITY = {"identifier_kind": "model_number", "identifier_exact": "MODEL-A"}
LOOKUP = {
    "draft_id": "draft",
    "revision": "revision",
    "entity_type_id": "00000000-0000-0000-0000-000000000001",
    "template_id": "00000000-0000-0000-0000-000000000002",
    "identity": IDENTITY,
    "current_values": {},
}


class CrossFieldInput(BaseModel):
    api_key: str
    model: str

    @model_validator(mode="after")
    def reject(self):
        raise ValueError(f"{self.api_key}: {self.model}")


@pytest_asyncio.fixture
async def private_client(disk, monkeypatch):
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Validation must never dispatch")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    app = create_app(config.settings, static_directory=str(disk.parent / "missing"))
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_verified_gateway] = lambda: object()

    @app.post("/api/llm/profiles/validation-probe")
    async def cross_field(body: CrossFieldInput):
        raise AssertionError("Invalid input reached endpoint")

    @app.post("/api/llm/profiles/error-probe")
    async def custom_error():
        raise RequestValidationError(
            [{"type": KEY, "loc": ("body", QUERY, KEY), "msg": QUERY, "ctx": {"error": ValueError(KEY)}, "input": KEY}],
            body={"api_key": KEY},
        )

    @app.post("/api/llm/profiles/bug-probe")
    async def actual_bug():
        raise RuntimeError("Not a validation error")

    before = disk.read_bytes()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    assert disk.read_bytes() == before
    assert attempts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/llm/profiles/capture/test", {"api_key": [KEY]}),
        ("POST", "/api/llm/profiles/capture/test", {"api_key": {KEY: QUERY}}),
        ("POST", "/api/llm/profiles/capture/test", [{"api_key": KEY}]),
        ("POST", "/api/llm/profiles/capture/test", KEY),
        ("POST", "/api/llm/profiles/capture/test", 42),
        ("POST", "/api/llm/profiles/capture/test", {"test_kind": KEY}),
        ("POST", "/api/llm/profiles/capture/test", {"identity": [QUERY]}),
        ("POST", "/api/llm/profiles/capture/test", {"identity": {**IDENTITY, "identifier_exact": QUERY + ":private"}}),
        ("POST", "/api/llm/profiles/capture/test", {"identity": {**IDENTITY, "manufacturer": [QUERY]}}),
        ("POST", "/api/llm/profiles/capture/test", {"identity": {**IDENTITY, QUERY: KEY}}),
        ("POST", "/api/llm/profiles/capture/test", {KEY: QUERY}),
        ("POST", "/api/llm/profiles/capture/test", {"api_key": "os.environ/" + KEY}),
        ("POST", "/api/llm/profiles", {"name": "target", "model": "gpt-4.1", "api_key": [KEY]}),
        ("PUT", "/api/llm/profiles/capture", {"api_key": {QUERY: KEY}}),
        ("PUT", "/api/settings/research", {"enabled": QUERY}),
        ("POST", "/api/research/lookups", {**LOOKUP, "current_values": {QUERY: [KEY]}}),
        ("POST", "/api/research/lookups", {**LOOKUP, "current_values": {"api_key": [KEY]}}),
        ("POST", "/api/research/lookups", {**LOOKUP, "identity": {**IDENTITY, "identifier_kind": QUERY}}),
        (
            "POST",
            "/api/research/lookups/" + QUERY + "/apply",
            {"draft_id": "a", "revision": "a", "selected": [KEY], "current_values": {}},
        ),
        (
            "POST",
            "/api/research/jobs",
            {
                "item_id": "item",
                "idempotency_key": "once",
                "identity": {**IDENTITY, "identifier_exact": QUERY + ":private"},
            },
        ),
        ("GET", "/api/research/jobs/" + QUERY, None),
        ("POST", "/api/research/jobs/00000000-0000-0000-0000-000000000001/apply", {"selected": [KEY]}),
        ("POST", "/api/login", {"username": "user", "password": [KEY]}),
        ("POST", "/api/llm/profiles/validation-probe", {"api_key": KEY, "model": QUERY}),
        ("POST", "/api/llm/profiles/error-probe", {}),
    ],
)
async def test_invalid_private_requests_never_echo_inputs_or_context(
    private_client, capsys, caplog, method, path, body
):
    capture = io.StringIO()
    sink = logger.add(capture)
    try:
        response = await private_client.request(method, path, json=body)
    finally:
        logger.remove(sink)
    assert response.status_code == 422
    captured = capsys.readouterr()
    # httpx's caller-side access log includes the URL; the application must not log it or the raw error.
    emitted = response.text + capture.getvalue() + captured.out + captured.err
    assert KEY not in emitted and QUERY not in emitted
    assert not any(KEY in r.message or QUERY in r.message for r in caplog.records if r.name != "httpx")
    payload = response.json()
    assert isinstance(payload["detail"], str)  # Existing frontend error extraction accepts this directly.
    assert payload["errors"]
    for error in payload["errors"]:
        assert set(error) == {"loc", "type", "msg"}
        assert isinstance(error["loc"], list)
        assert isinstance(error["type"], str) and isinstance(error["msg"], str)
    if isinstance(body, dict) and "current_values" in body and body["current_values"]:
        assert payload["errors"][0]["loc"] == ["body", "current_values", "[field]"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ['{"api_key":"' + KEY + '","' + QUERY + '":', '"' + KEY, "[" + json.dumps({"api_key": KEY})]
)
async def test_malformed_json_is_input_free(private_client, raw):
    response = await private_client.post(
        "/api/llm/profiles/capture/test", content=raw, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert KEY not in response.text and QUERY not in response.text
    assert isinstance(response.json()["detail"], str)
    assert response.json()["errors"][0]["type"] == "json_invalid"


@pytest.mark.asyncio
async def test_safe_known_location_is_actionable(private_client):
    response = await private_client.post("/api/llm/profiles/capture/test", json={"api_key": [KEY]})
    assert response.json()["errors"] == [
        {"loc": ["body", "api_key"], "type": "string_type", "msg": "Expected a string."}
    ]


@pytest.mark.asyncio
async def test_other_validation_and_programming_errors_are_not_swallowed(private_client):
    response = await private_client.get("/api/version?force_check=not-a-boolean")
    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "not-a-boolean"
    with pytest.raises(RuntimeError, match="Not a validation error"):
        await private_client.post("/api/llm/profiles/bug-probe", json={})
