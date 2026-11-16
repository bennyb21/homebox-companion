"""Actual public captures: usable suggestions, not verified factual claims."""

import json
from pathlib import Path

import pytest
from test_research_citation_contract import cited_response

from homebox_companion.research import parse_response


@pytest.mark.parametrize("name", ["public-markdown-citation.json", "public-control-markdown-citation.json"])
def test_actual_previous_outputs_are_editable_suggestions(name):
    result = parse_response(json.loads((Path(__file__).parent / "fixtures/research" / name).read_text()))
    assert result.status == "matched" and result.claims
    assert result.sources
    assert all(not claim.source_urls for claim in result.claims)
    assert all("Not independently verified" in claim.evidence for claim in result.claims)


@pytest.mark.parametrize(
    "annotations",
    [
        None,
        [],
        [None],
        [{"type": "url_citation", "url": "javascript:alert"}],
        [{"type": "url_citation", "url": "https://example.com/real", "start_index": False, "end_index": 99999}],
    ],
)
def test_unusable_metadata_never_rejects_usable_fields(annotations):
    data = cited_response(suffix=True)
    data["output"][1]["content"][0]["annotations"] = annotations
    result = parse_response(data)
    assert result.status == "matched"
    assert all(source.url.startswith("https://") for source in result.sources)
