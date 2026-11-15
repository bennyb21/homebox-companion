"""Server-owned diagnostic vocabulary. Never copy provider messages into it."""

import re
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

Stage = Literal["configuration", "provider_resolution", "dispatch", "response", "parse"]


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    stage: Stage
    message: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    request_id: str | None = None
    dispatch_started: bool | None = None
    correlation_id: str = Field(default_factory=lambda: uuid4().hex)
    incomplete_reason: Literal["max_output_tokens", "content_filter", "other"] | None = None


MESSAGES = {
    "credential_missing": "No credential is available from the selected source. "
    "Review the profile credential settings.",
    "model_unverified": "This exact model's web search capability is unverified. No research request was sent.",
    "connection_verified": "Authentication and exact model metadata access verified. "
    "Generation and web search were not tested.",
    "configuration_invalid": "Research is disabled or its profile, destination, "
    "credential or reasoning is not configured.",
    "response_invalid": "The provider returned an unusable response. No automatic repair request was made.",
    "response_refused": "The provider declined this request. No automatic retry was made.",
    "search_missing": "The response did not contain a completed web search; no claims can be adopted.",
    "citations_missing": "The response proposed candidates without provider URL citations.",
    "citation_invalid": "The provider citation locations were invalid or conflicted with the result format.",
    "source_invalid": "A proposed source was unsafe or was not backed by a provider URL citation.",
    "malformed_json": "The response did not follow the single JSON result format. No repair request was made.",
    "schema_invalid": "The response contained unsupported fields or an invalid result structure.",
    "identity_mismatch": "The response did not match the exact requested product identity.",
    "claim_invalid": "The response contained an unsupported or identity-changing claim.",
    "matched": "Research completed with one matching candidate. Review its cited model synthesis before adoption.",
    "ambiguous": "Research returned multiple candidates. No claims were selected for adoption.",
    "no_results": "The research request completed with no matching results; this is not product verification.",
    "response_incomplete": "The response did not complete within the provider output budget or policy. "
    "No automatic retry was made.",
    "request_rejected": "The provider rejected the request parameters. Review the model and task settings.",
    "authentication_failed": "The provider rejected authentication. Review the selected credential source.",
    "access_denied": "The provider denied access. Review model and project permissions.",
    "model_not_found": "The provider did not find or allow access to this exact model identifier.",
    "rate_limited": "The provider reported a rate or quota limit. "
    "Review account limits before another explicit request.",
    "provider_unavailable": "The provider reported a server error. No automatic retry was made.",
    "redirect_rejected": "The provider redirected the request; redirects are not followed.",
    "transport_error": "The connection ended without a usable response. No automatic retry was made.",
    "timeout": "The request timed out. Completion and billing are unknown; no automatic retry was made.",
    "provider_resolution_failed": "The local provider adapter could not prepare the request. Review provider settings.",
}


def safe_request_id(value: object) -> str | None:
    # Reject rather than truncate arbitrary header content or encoded SDK response IDs.
    return value if isinstance(value, str) and re.fullmatch(r"req_[a-f0-9]{16,64}", value) else None


def http_error_code(status: int) -> str:
    if 200 <= status < 300:
        return "response_invalid"
    if 300 <= status < 400:
        return "redirect_rejected"
    if status >= 500:
        return "provider_unavailable"
    return {401: "authentication_failed", 403: "access_denied", 404: "model_not_found", 429: "rate_limited"}.get(
        status, "request_rejected"
    )


def diagnostic(code: str, stage: Stage, **metadata) -> Diagnostic:
    return Diagnostic(code=code, stage=stage, message=MESSAGES[code], **metadata)
