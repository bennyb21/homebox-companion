"""Input-free validation errors for credential and research request boundaries."""

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Match the registered route template, never a caller-supplied field/path value.
_PRIVATE_ROUTES = ("/llm/profiles", "/research", "/settings/research", "/login")

# Only schema-owned paths may survive. In particular, keys of current_values
# are arbitrary user data even when they happen to look like schema field names.
_BODY_FIELDS = {
    "name",
    "new_name",
    "model",
    "api_key",
    "api_base",
    "status",
    "credential_source",
    "credential_profile_name",
    "research_reasoning_effort",
    "test_kind",
    "identity",
    "enabled",
    "profile_name",
    "draft_id",
    "revision",
    "entity_type_id",
    "template_id",
    "current_values",
    "selected",
    "item_id",
    "idempotency_key",
    "username",
    "password",
}
_SAFE_PATHS = (
    {("body",), ("path",), ("query",), ("header",)}
    | {("body", field) for field in _BODY_FIELDS}
    | {
        ("body", "identity", field)
        for field in ("manufacturer", "identifier_kind", "identifier_exact", "identity_confirmed")
    }
    | {("path", field) for field in ("name", "lookup_id", "id_")}
    | {("header", field) for field in ("authorization", "x-group-id")}
)
_MESSAGES = {
    "missing": "Field is required.",
    "string_type": "Expected a string.",
    "string_too_short": "String is too short.",
    "string_too_long": "String is too long.",
    "string_pattern_mismatch": "String has an invalid format.",
    "bool_type": "Expected a boolean.",
    "bool_parsing": "Expected a boolean.",
    "int_type": "Expected an integer.",
    "int_parsing": "Expected an integer.",
    "list_type": "Expected a list.",
    "dict_type": "Expected an object.",
    "model_type": "Expected an object.",
    "model_attributes_type": "Expected an object.",
    "literal_error": "Choose an allowed value.",
    "enum": "Choose an allowed value.",
    "extra_forbidden": "Unexpected field.",
    "uuid_parsing": "Expected a UUID.",
    "uuid_type": "Expected a UUID.",
    "too_long": "Too many entries.",
    "too_short": "Too few entries.",
    "json_invalid": "Malformed JSON body.",
    "value_error": "Invalid value or field combination.",
}


def _safe_location(location: tuple) -> list[str | int]:
    safe: list[str | int] = []
    for segment in location:
        if isinstance(segment, str) and (*safe, segment) in _SAFE_PATHS:
            safe.append(segment)
        elif type(segment) is int and safe == ["body", "selected"] and 0 <= segment < 8:
            safe.append(segment)
        else:
            safe.append("[field]")
            break
    return safe


async def private_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Included routers may retain local templates; direct app routes include /api.
    route_path = getattr(request.scope.get("route"), "path", "").removeprefix("/api")
    if not any(route_path == prefix or route_path.startswith(prefix + "/") for prefix in _PRIVATE_ROUTES):
        return await request_validation_exception_handler(request, exc)

    # Never serialize/log the exception, input, context, body, or custom message.
    # Even error types can be validator-supplied; unknown types are fixed too.
    errors = []
    for error in exc.errors():
        error_type = error.get("type")
        safe_type = error_type if error_type in _MESSAGES else "value_error"
        errors.append({"loc": _safe_location(error.get("loc", ())), "type": safe_type, "msg": _MESSAGES[safe_type]})
    return JSONResponse(
        status_code=422, content={"detail": "Request validation failed. Check the supplied fields.", "errors": errors}
    )
