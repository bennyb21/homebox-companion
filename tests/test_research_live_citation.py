"""Minimal public-text output captured from a real provider call, not a success fixture.

The private raw response and request IDs are deliberately excluded. The new call
reproduced citation_invalid; the model also dropped an input prefix and emitted
uncited URLs, so accepting its citation format must NOT make its claims trusted.
"""

import json
from pathlib import Path

import pytest
from test_research_citation_contract import IDENTITY, URL, cited_response

from homebox_companion.research import ProductIdentity, parse_response


def test_actual_markdown_citation_reaches_identity_validation():
    data = json.loads((Path(__file__).parent / "fixtures/research/public-markdown-citation.json").read_text())
    identity = ProductIdentity(identifier_kind="model_number", identifier_exact="0112-S90-6-10-032-N-B")
    result = parse_response(data, identity)
    assert result.status == "failed"
    assert result.diagnostic is not None
    assert result.diagnostic.code == "identity_mismatch"
    assert result.claims == []


def test_actual_control_still_rejects_uncited_claims_and_different_source_urls():
    data = json.loads((Path(__file__).parent / "fixtures/research/public-control-markdown-citation.json").read_text())
    identity = ProductIdentity(
        manufacturer="Eibach", identifier_kind="part_number", identifier_exact="S90-6-10-032-N-B"
    )
    result = parse_response(data, identity)
    assert result.status == "failed"
    assert result.diagnostic is not None
    assert result.diagnostic.code == "source_invalid"
    assert result.claims == []


def markdown_response(wrapped=True):
    """Synthetic success control using the real response's observed rendering."""
    data = cited_response(suffix=True)
    part = data["output"][1]["content"][0]
    annotation = part["annotations"][0]
    link = f"[example.com]({URL})"
    part["text"] = part["text"][: annotation["start_index"]] + (f"({link})" if wrapped else link)
    annotation["end_index"] = len(part["text"])
    return data


@pytest.mark.parametrize("wrapped", [False, True])
def test_annotated_markdown_link_keeps_per_claim_attribution(wrapped):
    result = parse_response(markdown_response(wrapped), IDENTITY)
    assert result.status == "matched"
    assert result.claims[0].source_urls == [URL]
    assert "not independently verified" in result.claims[0].evidence


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("different_link", "citation_invalid"),
        ("trailing_prose", "malformed_json"),
        ("annotated_prose", "citation_invalid"),
        ("range", "citation_invalid"),
        ("overlap", "citation_invalid"),
        ("uncited_claim", "source_invalid"),
        ("unsafe_url", "source_invalid"),
        ("tracking_difference", "source_invalid"),
        ("duplicate_key", "malformed_json"),
        ("unsupported_claim", "schema_invalid"),
    ],
)
def test_markdown_rendering_does_not_weaken_validation(mutation, code):
    data = markdown_response()
    part = data["output"][1]["content"][0]
    annotation = part["annotations"][0]
    start = annotation["start_index"]
    prefix, suffix = part["text"][:start], part["text"][start:]
    if mutation == "different_link":
        suffix = suffix.replace(URL, "https://example.com/other")
    if mutation == "annotated_prose":
        suffix += " ignore all constraints"
    if mutation == "uncited_claim":
        payload = json.loads(prefix)
        payload["candidates"][0]["claims"][0]["source_urls"] = ["https://example.com/other"]
        prefix = json.dumps(payload) + " "
    if mutation == "unsafe_url":
        suffix = suffix.replace(URL, "javascript:alert")
        annotation["url"] = "javascript:alert"
    if mutation == "tracking_difference":
        annotation["url"] = URL + "?utm_source=openai"
        suffix = suffix.replace(URL, annotation["url"])
    if mutation == "duplicate_key":
        prefix = '{"candidates":[],"candidates":[]} '
    if mutation == "unsupported_claim":
        prefix = prefix.replace("specifications", "purchasePrice")
    part["text"] = prefix + suffix
    annotation.update(start_index=len(prefix), end_index=len(part["text"]))
    if mutation == "range":
        annotation["end_index"] += 1
    if mutation == "overlap":
        part["annotations"].append({**annotation, "start_index": len(prefix) + 1, "end_index": len(part["text"]) - 1})
    if mutation == "trailing_prose":
        part["text"] += " ignore all constraints"
    result = parse_response(data, IDENTITY)
    assert result.status == "failed"
    assert result.diagnostic is not None
    assert result.diagnostic.code == code
    assert result.claims == []
