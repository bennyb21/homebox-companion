"""Exact printed OEM identifiers survive validation and provider transport."""

import json

import httpx
import pytest
from pydantic import SecretStr
from test_research_evidence import response

from homebox_companion.core.persistent_settings import ModelProfile
from homebox_companion.research import OpenAIResponsesResearchProvider, ProductIdentity, ResearchPolicy


@pytest.mark.asyncio
async def test_grouped_identifier_is_sent_and_matched_literally():
    exact = "A 000 123 45 67"
    identity = ProductIdentity(identifier_kind="part_number", identifier_exact=exact, identity_confirmed=True)
    data = response() | {"object": "response", "created_at": 1, "model": "gpt-4.1-mini"}
    part = data["output"][2]["content"][0]
    part["text"] = part["text"].replace("AB-123-x", exact)
    part["annotations"][0]["end_index"] = len(part["text"])
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=data)

    provider = OpenAIResponsesResearchProvider(
        ResearchPolicy(enabled=True, profile_name="research"),
        ModelProfile(name="research", model="gpt-4.1-mini", api_key=SecretStr("synthetic")),
        transport=httpx.MockTransport(respond),
    )
    result = await provider.research(identity)
    assert result.status == "matched"
    assert json.loads(calls[0]["input"])["identifier_exact"] == exact
    from homebox_companion.research import parse_response

    compact = identity.model_copy(update={"identifier_exact": exact.replace(" ", "")})
    assert parse_response(data, compact).status == "ambiguous"
