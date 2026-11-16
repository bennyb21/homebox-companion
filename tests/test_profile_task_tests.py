"""Task-aware profile tests with synthetic mock HTTP only."""

import httpx
import pytest
import test_model_configuration as fixtures

client = fixtures.client
disk = fixtures.disk


@pytest.fixture(autouse=True)
def blocked_network(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Real network forbidden; synthetic transport required")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-6-terra", "gpt-6.1-terra", "gpt-6-luna"])
async def test_official_connection_is_exact_read_only_model_access(client, disk, monkeypatch, model):
    calls = []

    async def send(_transport, request):
        calls.append(request)
        assert request.method == "GET"
        assert str(request.url) == f"https://api.openai.com/v1/models/{model}"
        assert request.headers["authorization"] == "Bearer OWN-secret"
        return httpx.Response(
            200,
            json={"id": model, "object": "model", "owned_by": "openai", "created": 1},
            headers={"x-request-id": "req_0123456789abcdef"},
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://evil.invalid/v1")
    await client.post(
        "/api/llm/profiles",
        json={
            "name": "Off",
            "model": model,
            "status": "off",
            "credential_source": "profile",
            "credential_profile_name": "capture",
        },
    )
    before = disk.read_bytes()
    response = await client.post("/api/llm/profiles/Off/test", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True, body
    assert body["diagnostic"]["code"] == "connection_verified"
    assert "not tested" in body["message"].lower()
    assert body["model_info"]["model"] == model
    assert len(calls) == 1
    assert disk.read_bytes() == before


@pytest.mark.asyncio
async def test_documented_terra_eligibility_bypasses_stale_sdk_catalog(client, disk, monkeypatch):
    import litellm

    monkeypatch.setattr(litellm, "supports_web_search", lambda *a, **k: False)
    for name, model in [("documented", "gpt-6.1-terra"), ("literal", "gpt-6-terra")]:
        response = await client.post(
            "/api/llm/profiles",
            json={
                "name": name,
                "model": model,
                "status": "off",
                "credential_source": "profile",
                "credential_profile_name": "capture",
            },
        )
        assert response.status_code == 201
    rows = {p["name"]: p for p in (await client.get("/api/settings/research")).json()["profiles"]}
    assert rows["documented"]["eligible"] is True
    assert rows["documented"]["eligibility_source"] == "official_metadata"
    assert rows["literal"]["eligible"] is False
    assert rows["literal"]["eligibility_source"] == "unverified"
    options = (await client.get("/api/llm/profiles")).json()["reasoning_options"]
    assert options["gpt-6.1-terra"] == ["none", "low", "medium", "high", "xhigh", "max"]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,success", [("matched", True), ("no_results", True), ("incomplete", False)])
@pytest.mark.parametrize("whole_context", [False, True])
async def test_explicit_research_test_uses_named_off_profile_same_adapter(
    client, disk, monkeypatch, outcome, success, whole_context
):
    import json

    from test_research_citation_contract import IDENTITY, cited_response

    from homebox_companion.core import field_preferences

    preferences = disk.parent / "field_preferences.json"
    preferences.write_text(json.dumps({"output_language": "German"}))
    monkeypatch.setattr(field_preferences, "PREFERENCES_FILE", preferences)
    calls = []
    data = cited_response(empty=outcome == "no_results")
    if outcome == "incomplete":
        data.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})

    async def send(_transport, request):
        calls.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses" and request.method == "POST"
        body = json.loads(request.content)
        assert body["model"] == "gpt-6.1-terra"
        assert body["max_tool_calls"] == 1 and body["max_output_tokens"] == 2400
        assert body["store"] is False and body["background"] is False
        assert body["tool_choice"] == "required"
        context = json.loads(body["input"][0]["content"][0]["text"])
        assert "German" in body["instructions"]
        if whole_context:
            assert context["description"] == "Example Maker pump MODEL-A, label PART-02"
        else:
            assert context["model_number"] == IDENTITY.identifier_exact
            assert context["manufacturer"] == IDENTITY.manufacturer
        assert "identity_confirmed" not in context
        assert request.headers["authorization"] == "Bearer OWN-secret"
        return httpx.Response(200, json=data)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    await client.post(
        "/api/llm/profiles",
        json={
            "name": "Off",
            "model": "gpt-6.1-terra",
            "status": "off",
            "credential_source": "profile",
            "credential_profile_name": "capture",
        },
    )
    before = disk.read_bytes()
    response = await client.post(
        "/api/llm/profiles/Off/test",
        json={"test_kind": "research"}
        | (
            {"context": {"description": "Example Maker pump MODEL-A, label PART-02"}}
            if whole_context
            else {"identity": IDENTITY.model_dump(exclude_none=True)}
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is success
    assert body["research_result"]["status"] == ("failed" if outcome == "incomplete" else outcome)
    assert body["diagnostic"]["code"] == ("response_incomplete" if outcome == "incomplete" else outcome)
    assert len(calls) == 1
    assert disk.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"test_kind": "research"}, {"test_kind": "mystery"}, {"unexpected": True}])
async def test_invalid_task_test_contract_rejects_before_network(client, body):
    response = await client.post("/api/llm/profiles/capture/test", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_test_identity_does_not_echo_override_key(client):
    response = await client.post(
        "/api/llm/profiles/capture/test", json={"test_kind": "research", "api_key": "SECRET-OVERRIDE-CANARY"}
    )
    assert response.status_code == 422
    assert "SECRET-OVERRIDE-CANARY" not in response.text


@pytest.mark.parametrize("model", ["gpt-6-terra", "gpt-6.1-terra"])
def test_official_capture_routing_preserves_literal_despite_catalog_absence(model, disk, monkeypatch):
    from homebox_companion.core import llm_router
    from homebox_companion.core import persistent_settings as ps

    settings = ps.load_settings()
    settings.llm_profiles[0].model = model
    ps.save_settings(settings)
    llm_router.invalidate_router()
    router = llm_router.get_router()
    params = router.model_list[0]["litellm_params"]
    assert params["model"] == model
    assert params["custom_llm_provider"] == "openai"
    assert params["api_base"] == "https://api.openai.com/v1"
    llm_router.invalidate_router()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [
        (400, "request_rejected"),
        (401, "authentication_failed"),
        (404, "model_not_found"),
        (429, "rate_limited"),
        (503, "provider_unavailable"),
        (307, "redirect_rejected"),
    ],
)
async def test_connection_reports_known_http_failure_once(client, monkeypatch, status, code):
    calls = []

    async def send(_transport, request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"x-request-id": "req_SECRET-CANARY", "location": "https://evil.invalid"},
            json={"error": {"message": "SECRET-CANARY"}},
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    response = await client.post("/api/llm/profiles/capture/test", json={})
    body = response.json()
    assert body["success"] is False
    assert body["diagnostic"]["code"] == code
    assert body["diagnostic"]["http_status"] == status
    assert body["diagnostic"]["request_id"] is None
    assert "SECRET-CANARY" not in response.text
    assert len(calls) == 1 and calls[0].method == "GET"
