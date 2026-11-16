"""Synthetic provider metadata only; never a paid search acceptance test."""

from typing import Never

import httpx
import pytest
from pydantic import SecretStr

from homebox_companion.core.persistent_settings import ModelProfile
from homebox_companion.research import OpenAIResponsesResearchProvider, ProductIdentity, ResearchPolicy, parse_response


def test_incomplete_retains_safe_reason_without_provider_body():
    result = parse_response(
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
            "error": {"message": "SECRET-QUERY-CANARY"},
        },
        ProductIdentity(identifier_kind="model_number", identifier_exact="PUBLIC-A", identity_confirmed=True),
    )
    assert result.status == "failed"
    diagnostic = result.model_dump().get("diagnostic")
    assert diagnostic is not None
    assert diagnostic["code"] == "response_incomplete"
    assert diagnostic["stage"] == "response"
    assert diagnostic["incomplete_reason"] == "max_output_tokens"
    assert "SECRET-QUERY-CANARY" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [
        (400, "request_rejected"),
        (401, "authentication_failed"),
        (403, "access_denied"),
        (404, "model_not_found"),
        (429, "rate_limited"),
        (503, "provider_unavailable"),
        (307, "redirect_rejected"),
    ],
)
async def test_http_failure_metadata_at_real_single_dispatch_boundary(status, code, capsys):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"x-request-id": "req_0123456789abcdef", "location": "https://evil.invalid"},
            json={"error": {"message": "SECRET-QUERY-CANARY", "type": "invalid_request_error"}},
        )

    provider = OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=True, profile_name="test"),
        ModelProfile(name="test", model="gpt-4.1-mini", api_key=SecretStr("SECRET-KEY-CANARY")),
        transport=httpx.MockTransport(respond),
    )
    result = await provider.research(
        ProductIdentity(identifier_kind="model_number", identifier_exact="PUBLIC-QUERY-CANARY", identity_confirmed=True)
    )
    assert len(calls) == 1
    assert result.status == "unknown_outcome"
    d = result.model_dump().get("diagnostic")
    assert d is not None
    assert d["code"] == code and d["http_status"] == status
    assert d["request_id"] == "req_0123456789abcdef"
    assert d["dispatch_started"] is True
    assert len(d["correlation_id"]) == 32
    captured = capsys.readouterr()
    for canary in ("SECRET-QUERY-CANARY", "SECRET-KEY-CANARY", "PUBLIC-QUERY-CANARY"):
        assert canary not in result.model_dump_json() + captured.out + captured.err


@pytest.mark.asyncio
async def test_successful_http_parse_failure_keeps_operation_metadata():
    provider = OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=True, profile_name="test"),
        ModelProfile(name="test", model="gpt-4.1-mini", api_key=SecretStr("SYNTHETIC")),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"x-request-id": "req_0123456789abcdef"},
                json={
                    "id": "SDK-ENCODED-SECRET",
                    "object": "response",
                    "created_at": 1,
                    "model": "gpt-4.1-mini",
                    "status": "incomplete",
                    "output": [],
                    "incomplete_details": {"reason": "max_output_tokens"},
                },
            )
        ),
    )
    result = await provider.research(ProductIdentity(identifier_kind="model_number", identifier_exact="PUBLIC-A"))
    assert result.diagnostic is not None
    assert result.diagnostic.code == "response_incomplete"
    assert result.diagnostic.http_status == 200
    assert result.diagnostic.request_id == "req_0123456789abcdef"
    assert result.diagnostic.dispatch_started is True
    assert "SDK-ENCODED-SECRET" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_disabled_configuration_has_no_dispatch_and_safe_diagnostic():
    result = await OpenAIResponsesResearchProvider(ResearchPolicy(), None).research(
        ProductIdentity(identifier_kind="model_number", identifier_exact="PUBLIC-A")
    )
    assert result.diagnostic is not None
    assert result.diagnostic.code == "configuration_invalid"
    assert result.diagnostic.dispatch_started is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,code",
    [
        ("invalid_http_body", "response_invalid"),
        ("timeout", "timeout"),
        ("disconnect", "transport_error"),
        ("cancel", None),
    ],
)
async def test_single_dispatch_failure_is_never_retried(failure, code):
    import asyncio

    calls = []

    def respond(request):
        calls.append(request)
        if failure == "invalid_http_body":
            return httpx.Response(200, content=b"not JSON SECRET-CANARY")
        if failure == "timeout":
            raise httpx.ReadTimeout("SECRET-CANARY")
        if failure == "cancel":
            raise asyncio.CancelledError()
        raise httpx.ReadError("SECRET-CANARY")

    provider = OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=True, profile_name="test"),
        ModelProfile(name="test", model="gpt-4.1-mini", api_key=SecretStr("SYNTHETIC")),
        transport=httpx.MockTransport(respond),
    )
    identity = ProductIdentity(identifier_kind="model_number", identifier_exact="PUBLIC-A")
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await provider.research(identity)
    else:
        result = await provider.research(identity)
        assert result.status == "unknown_outcome"
        assert result.diagnostic is not None
        assert result.diagnostic.code == code
        assert result.diagnostic.dispatch_started is True
        assert "SECRET-CANARY" not in result.model_dump_json()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "value", ["req_SECRET-KEY-CANARY", "resp_0123456789abcdef", "req_" + "a" * 100, "req_0123456789abcdef\n", None]
)
def test_untrusted_request_ids_are_dropped_not_truncated(value):
    from homebox_companion.research_diagnostics import safe_request_id

    assert safe_request_id(value) is None


@pytest.mark.parametrize("mode", ["cold", "vision_first"])
def test_production_binding_in_fresh_process(tmp_path, mode):
    import json
    import subprocess
    import sys
    from pathlib import Path

    run = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("research_binding_probe.py")),
            str(tmp_path / "synthetic-settings.yaml"),
            mode,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    summary = json.loads(run.stdout.splitlines()[-1])
    assert summary["network"] == "blocked"
    assert len(summary["cases"]) == 8
    assert all(c["posts"] == 1 for c in summary["cases"])


@pytest.mark.asyncio
async def test_unverified_model_is_distinct_from_remote_denial():
    calls = []

    def forbidden(request: httpx.Request) -> Never:
        calls.append(request)
        raise AssertionError("Unverified model must not dispatch a provider request")

    provider = OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=True, profile_name="test"),
        ModelProfile(name="test", model="gpt-6-terra", api_key=SecretStr("SYNTHETIC")),
        transport=httpx.MockTransport(forbidden),
    )
    result = await provider.research(ProductIdentity(identifier_kind="model_number", identifier_exact="PUBLIC-A"))
    assert result.diagnostic is not None
    assert result.diagnostic.code == "model_unverified"
    assert result.diagnostic.stage == "provider_resolution"
    assert result.diagnostic.dispatch_started is False
    assert result.diagnostic.http_status is None
    assert calls == []
