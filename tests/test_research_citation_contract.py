"""Official-schema-shaped synthetic fixtures, not actual search results.

Reference: OpenAI Responses url_citation positions locate citations, not quotations.
"""

import json

import pytest

from homebox_companion.research import ProductIdentity, parse_response

URL = "https://example.com/model"
IDENTITY = ProductIdentity(manufacturer="Example", identifier_kind="model_number", identifier_exact="MODEL-A")


def cited_response(*, suffix=False, empty=False):
    payload = {
        "candidates": []
        if empty
        else [
            {
                "manufacturer": "Example",
                "identifier_kind": "model_number",
                "identifier_exact": "MODEL-A",
                "source_urls": [URL],
                "claims": [{"field": "specifications", "value": "Steel, 12 mm", "source_urls": [URL]}],
            }
        ]
    }
    text = json.dumps(payload)
    annotations = []
    if not empty:
        if suffix:
            start = len(text) + 1
            text += " \ue200cite\ue202turn0search0\ue201"
            end = len(text)
        else:
            start = text.index(URL)
            end = start + len(URL)
        annotations = [
            {"type": "url_citation", "url": URL, "title": "Synthetic", "start_index": start, "end_index": end}
        ]
    return {
        "id": "resp_synthetic",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4.1-mini",
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_synthetic",
                "status": "completed",
                "action": {"type": "search", "sources": [{"type": "url", "url": URL}]},
            },
            {
                "type": "message",
                "id": "msg_synthetic",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": annotations}],
            },
        ],
    }


@pytest.mark.parametrize("suffix", [False, True])
def test_citation_location_is_not_a_supporting_text_span(suffix):
    result = parse_response(cited_response(suffix=suffix), IDENTITY)
    assert result.status == "matched"
    assert result.claims[0].source_urls == [URL]
    assert result.claims[0].evidence == "Cited model synthesis; original source text not independently verified"
    assert result.diagnostic.code == "matched"


def test_empty_candidates_after_completed_search_need_no_annotations():
    result = parse_response(cited_response(empty=True), IDENTITY)
    assert result.status == "no_results"
    assert result.diagnostic.code == "no_results"


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("no_search", "search_missing"),
        ("no_annotations", "citations_missing"),
        ("refusal", "response_refused"),
        ("bad_json", "malformed_json"),
        ("range", "citation_invalid"),
        ("bool_range", "citation_invalid"),
        ("mismatch", "identity_mismatch"),
        ("invented", "source_invalid"),
        ("field", "schema_invalid"),
        ("duplicate", "malformed_json"),
        ("trailing", "malformed_json"),
        ("conflicting_suffix", "citation_invalid"),
    ],
)
def test_parser_has_safe_distinct_rejection_codes(mutation, code):
    data = cited_response(suffix=mutation == "conflicting_suffix")
    part = data["output"][1]["content"][0]
    if mutation == "no_search":
        data["output"][0]["status"] = "failed"
    if mutation == "no_annotations":
        part["annotations"] = []
    if mutation == "refusal":
        part.update(type="refusal", refusal="SECRET-CANARY")
    if mutation == "bad_json":
        part["text"] = "not json"
    if mutation == "range":
        part["annotations"][0]["end_index"] = 100000
    if mutation == "bool_range":
        part["annotations"][0]["start_index"] = False
    if mutation == "mismatch":
        part["text"] = part["text"].replace("MODEL-A", "MODEL-B")
    if mutation == "invented":
        part["annotations"][0]["url"] = "https://example.com/other"
    if mutation == "field":
        part["text"] = part["text"].replace("specifications", "purchasePrice")
    if mutation == "duplicate":
        part["text"] = '{"candidates":[],"candidates":[]}'
    if mutation == "trailing":
        part["text"] += " SECRET-CANARY"
    if mutation == "conflicting_suffix":
        part["text"] = part["text"].replace("\ue200cite\ue202turn0search0\ue201", "SECRET-CANARY")
        part["annotations"][0]["end_index"] = len(part["text"])
    if mutation in {"bad_json", "duplicate"}:
        part["annotations"] = []
    result = parse_response(data, IDENTITY)
    assert result.status == "failed"
    assert result.diagnostic.code == code
    assert "SECRET-CANARY" not in result.model_dump_json()
