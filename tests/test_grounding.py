"""Tests for grounding.py: citation validation and answer status, pure logic."""

import pytest

from engine.grounding import build_answer
from engine.models import Claim

RETRIEVED = {1, 2, 3, 5}


def _claim(text: str, citations: list) -> dict:
    return {"text": text, "citations": citations}


# --- citations and claims ---


def test_happy_path_answered():
    raw = {"status": "answered", "claims": [_claim("Paris is the capital.", [1, 2])]}
    answer = build_answer(raw, RETRIEVED)
    assert answer.status == "answered"
    assert answer.claims == [Claim(text="Paris is the capital.", citations=[1, 2])]
    assert answer.contradictions == []


def test_citation_not_retrieved_is_removed():
    raw = {"status": "answered", "claims": [_claim("A", [1, 99])]}
    assert build_answer(raw, RETRIEVED).claims == [Claim(text="A", citations=[1])]


def test_bool_citation_is_removed():
    # True == 1 in Python, and 1 is retrieved: it must still not count.
    raw = {"status": "answered", "claims": [_claim("A", [True, 2])]}
    assert build_answer(raw, RETRIEVED).claims == [Claim(text="A", citations=[2])]


def test_non_int_citations_are_removed():
    raw = {"status": "answered", "claims": [_claim("A", ["1", 2.0, None, 3])]}
    assert build_answer(raw, RETRIEVED).claims == [Claim(text="A", citations=[3])]


def test_duplicate_citations_deduped_keeping_first_order():
    raw = {"status": "answered", "claims": [_claim("A", [3, 1, 3, 2, 1])]}
    assert build_answer(raw, RETRIEVED).claims == [Claim(text="A", citations=[3, 1, 2])]


def test_claim_without_valid_citation_dropped_and_traced():
    bad = _claim("Made up.", [99, True])
    raw = {"status": "answered", "claims": [_claim("Real.", [1]), bad]}
    answer = build_answer(raw, RETRIEVED)
    assert answer.claims == [Claim(text="Real.", citations=[1])]
    assert answer.trace[0]["dropped_claims"] == [bad]


def test_blank_text_claim_dropped():
    blank = _claim("  \n", [1])
    raw = {"status": "answered", "claims": [blank, _claim("B", [2])]}
    answer = build_answer(raw, RETRIEVED)
    assert answer.claims == [Claim(text="B", citations=[2])]
    assert answer.trace[0]["dropped_claims"] == [blank]


def test_claim_text_kept_as_given():
    raw = {"status": "answered", "claims": [_claim("  padded  ", [1])]}
    assert build_answer(raw, RETRIEVED).claims[0].text == "  padded  "


def test_claim_that_only_lost_some_citations_is_not_traced():
    raw = {"status": "answered", "claims": [_claim("A", [1, 99])]}
    assert build_answer(raw, RETRIEVED).trace[0]["dropped_claims"] == []


def test_empty_retrieved_drops_everything():
    raw = {"status": "answered", "claims": [_claim("A", [1])]}
    answer = build_answer(raw, set())
    assert answer.status == "insufficient"
    assert answer.claims == []


# --- contradictions ---


@pytest.mark.parametrize("citations", [[1], [5, 5], [1, 99], [1, True]])
def test_contradiction_with_one_distinct_valid_citation_dropped(citations):
    bad = _claim("X vs Y", citations)
    raw = {"status": "conflicting", "claims": [_claim("A", [1])], "contradictions": [bad]}
    answer = build_answer(raw, RETRIEVED)
    assert answer.contradictions == []
    assert answer.trace[0]["dropped_contradictions"] == [bad]
    # The model said "conflicting", but nothing survived: rules fall through to "answered".
    assert answer.status == "answered"


def test_blank_text_contradiction_dropped():
    blank = _claim(" ", [2, 3])
    raw = {"status": "conflicting", "claims": [_claim("A", [1])], "contradictions": [blank]}
    answer = build_answer(raw, RETRIEVED)
    assert answer.contradictions == []
    assert answer.trace[0]["dropped_contradictions"] == [blank]


def test_contradiction_with_two_valid_citations_is_conflicting():
    raw = {
        "status": "answered",
        "claims": [_claim("A", [1])],
        "contradictions": [_claim("Doc 2 says 2019, doc 3 says 2020.", [2, 99, 3, 2])],
    }
    answer = build_answer(raw, RETRIEVED)
    assert answer.status == "conflicting"
    assert answer.contradictions == [
        Claim(text="Doc 2 says 2019, doc 3 says 2020.", citations=[2, 3])
    ]


def test_contradiction_survives_without_claims_is_conflicting():
    raw = {"status": "insufficient", "claims": [], "contradictions": [_claim("X", [1, 2])]}
    assert build_answer(raw, RETRIEVED).status == "conflicting"


def test_missing_contradictions_means_empty():
    raw = {"status": "answered", "claims": [_claim("A", [1])]}
    answer = build_answer(raw, RETRIEVED)
    assert answer.contradictions == []
    assert answer.trace[0]["dropped_contradictions"] == []


# --- status ---


def test_model_insufficient_keeps_surviving_claims():
    raw = {"status": "insufficient", "claims": [_claim("Partial fact.", [1])]}
    answer = build_answer(raw, RETRIEVED)
    assert answer.status == "insufficient"
    assert answer.claims == [Claim(text="Partial fact.", citations=[1])]


def test_no_surviving_claims_is_insufficient():
    raw = {"status": "answered", "claims": [_claim("A", [99])]}
    assert build_answer(raw, RETRIEVED).status == "insufficient"


def test_no_claims_at_all_is_insufficient():
    assert build_answer({"status": "answered", "claims": []}, RETRIEVED).status == "insufficient"


@pytest.mark.parametrize("status", ["maybe", 7, None])
def test_unknown_status_treated_as_answered(status):
    raw = {"status": status, "claims": [_claim("A", [1])]}
    assert build_answer(raw, RETRIEVED).status == "answered"


def test_missing_status_treated_as_answered():
    assert build_answer({"claims": [_claim("A", [1])]}, RETRIEVED).status == "answered"


# --- shape errors ---


@pytest.mark.parametrize(
    "raw",
    [
        ["not", "a", "dict"],
        {"status": "answered"},  # no claims
        {"status": "answered", "claims": "A"},
        {"status": "answered", "claims": [{"citations": [1]}]},  # no text
        {"status": "answered", "claims": [{"text": 5, "citations": [1]}]},
        {"status": "answered", "claims": ["A"]},  # item not a dict
        {"status": "answered", "claims": [{"text": "A", "citations": 1}]},
        {"status": "answered", "claims": [{"text": "A"}]},  # no citations
        {"status": "answered", "claims": [], "contradictions": {"text": "X"}},
        {"status": "answered", "claims": [], "contradictions": [{"text": "X", "citations": 1}]},
    ],
)
def test_wrong_shape_raises(raw):
    with pytest.raises(ValueError):
        build_answer(raw, RETRIEVED)


# --- trace ---


def test_trace_has_exactly_one_grounding_entry():
    raw = {"status": "answered", "claims": [_claim("A", [1])]}
    assert build_answer(raw, RETRIEVED).trace == [
        {"step": "grounding", "dropped_claims": [], "dropped_contradictions": []}
    ]
