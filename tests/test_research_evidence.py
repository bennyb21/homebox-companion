"""Synthetic citations are not evidence of live search quality."""

import copy
import json

import pytest

from homebox_companion import research


def response():
    payload = {
        "candidates": [
            {
                "manufacturer": "Example",
                "identifier_exact": "AB-123-x",
                "identifier_kind": "part_number",
                "source_urls": ["https://example.com/part"],
                "claims": [
                    {"field": "specifications", "value": "Steel, 12 mm", "source_urls": ["https://example.com/part"]}
                ],
            }
        ]
    }
    text = json.dumps(payload)
    return {
        "id": "resp_synthetic",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "sources": [{"type": "url", "url": "https://example.com/part"}]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/part",
                                "title": "Synthetic source",
                                "start_index": 0,
                                "end_index": len(text),
                            }
                        ],
                    }
                ],
            },
        ],
    }


def parse(data):
    assert hasattr(research, "parse_response")
    return research.parse_response(
        data,
        research.ProductIdentity(identifier_kind="part_number", identifier_exact="AB-123-x", identity_confirmed=True),
    )


@pytest.mark.asyncio
async def test_successful_sdk_response_is_parsed_without_second_request():
    import httpx
    from pydantic import SecretStr

    from homebox_companion.core.persistent_settings import ModelProfile

    data = response() | {"object": "response", "created_at": 1, "model": "gpt-4.1-mini"}
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=data)

    provider = research.OpenAIResponsesResearchProvider(
        research.ResearchPolicy(enabled=True, profile_name="research"),
        ModelProfile(name="research", model="gpt-4.1-mini", api_key=SecretStr("synthetic")),
        transport=httpx.MockTransport(respond),
    )
    result = await provider.research(
        research.ProductIdentity(identifier_kind="part_number", identifier_exact="AB-123-x", identity_confirmed=True)
    )
    assert result.status == "matched"
    assert len(calls) == 1
    assert "editable AI suggestions" in json.loads(calls[0].content)["instructions"]


def test_annotation_positions_do_not_claim_to_be_supporting_excerpts():
    data = response()
    data["output"][2]["content"][0]["annotations"][0]["end_index"] = 2
    # Provider links are display metadata, not proof of the proposed fields.
    result = parse(data)
    assert result.status == "matched"
    assert "Not independently verified" in result.claims[0].evidence


def test_identity_corrections_remain_reviewable_proposals():
    data = response()
    content = data["output"][2]["content"][0]
    payload = json.loads(content["text"])
    payload["candidates"][0]["claims"][0].update(field="part_number", value="AB-123-y")
    content["text"] = json.dumps(payload)
    content["annotations"][0]["end_index"] = len(content["text"])
    assert parse(data).status == "matched"


@pytest.mark.parametrize(
    "value",
    [
        "Guaranteed fits VIN ABC123",
        "Vehicle fitment guaranteed",
        "Seriennummer S-123",
        "Montagefreigabe für alle Fahrzeuge",
    ],
)
def test_wording_does_not_act_as_a_certification_or_rejection_gate(value):
    data = response()
    content = data["output"][2]["content"][0]
    payload = json.loads(content["text"])
    payload["candidates"][0]["claims"][0]["value"] = value
    content["text"] = json.dumps(payload, ensure_ascii=False)
    content["annotations"][0]["end_index"] = len(content["text"])
    assert parse(data).status == "matched"


def test_cited_exact_identity_creates_reviewable_synthesis_not_fake_quote():
    result = parse(response())
    assert result.status == "matched"
    assert result.claims[0].field == "specifications"
    assert result.claims[0].value == "Steel, 12 mm"
    assert "Not independently verified" in result.claims[0].evidence
    assert result.sources[0].url == "https://example.com/part"


@pytest.mark.parametrize(
    "mutation,status",
    [
        ("no_search", "matched"),
        ("no_annotations", "matched"),
        ("incomplete", "failed"),
        ("similar", "matched"),
        ("collision", "ambiguous"),
        ("fake_source", "matched"),
        ("javascript", "matched"),
        ("userinfo", "matched"),
        ("price", "no_results"),
        ("invalid_json", "failed"),
        ("empty", "no_results"),
    ],
)
def test_metadata_is_separate_and_unknown_fields_are_ignored(mutation, status):
    data = response()
    content = data["output"][2]["content"][0]
    payload = json.loads(content["text"])
    if mutation == "no_search":
        data["output"][1]["status"] = "in_progress"
    if mutation == "no_annotations":
        content["annotations"] = []
    if mutation == "incomplete":
        data["status"] = "incomplete"
    if mutation == "similar":
        payload["candidates"][0]["identifier_exact"] = "AB-123-y"
    if mutation == "collision":
        other = copy.deepcopy(payload["candidates"][0])
        other["manufacturer"] = "Other"
        payload["candidates"].append(other)
    if mutation == "fake_source":
        payload["candidates"][0]["claims"][0]["source_urls"] = ["https://invented.example/claim"]
    if mutation in {"javascript", "userinfo"}:
        url = "javascript:alert(1)" if mutation == "javascript" else "https://user:pass@example.com/part"
        content["annotations"][0]["url"] = url
    if mutation == "price":
        payload["candidates"][0]["claims"][0]["field"] = "purchasePrice"
    if mutation == "empty":
        payload["candidates"] = []
    content["text"] = "not json" if mutation == "invalid_json" else json.dumps(payload)
    if content["annotations"]:
        content["annotations"][0]["end_index"] = len(content["text"])
    result = parse(data)
    assert result.status == status
    assert bool(result.claims) == (status == "matched")
