"""Tests for eval/metrics.py: pure functions, expected values worked out by hand."""

import pytest

from eval.metrics import (
    abstention_precision_recall,
    citation_precision,
    contradiction_precision_recall,
    exact_match,
    f1,
    normalize_answer,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_partial():
    # gold {a, b}; only a is retrieved -> 1/2
    assert recall_at_k(["a", "x"], {"a", "b"}, k=2) == 0.5


def test_recall_full():
    assert recall_at_k(["b", "x", "a"], {"a", "b"}, k=3) == 1.0


def test_recall_zero():
    assert recall_at_k(["x", "y"], {"a"}, k=2) == 0.0


def test_recall_ignores_items_after_k():
    # b sits at position 3, outside the first 2
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, k=2) == 0.5


def test_recall_duplicates_in_retrieved_count_once():
    # two chunks of a, gold {a, b} -> 1/2, not 2/2
    assert recall_at_k(["a", "a", "x"], {"a", "b"}, k=3) == 0.5


def test_recall_k_larger_than_retrieved():
    assert recall_at_k(["a"], {"a"}, k=10) == 1.0


def test_recall_empty_gold_raises():
    with pytest.raises(ValueError):
        recall_at_k(["a"], set(), k=1)


def test_recall_k_below_one_raises():
    with pytest.raises(ValueError):
        recall_at_k(["a"], {"a"}, k=0)


def test_reciprocal_rank_first():
    assert reciprocal_rank(["a", "x"], {"a"}) == 1.0


def test_reciprocal_rank_third():
    # first gold item is at rank 3 -> 1/3; the later gold item does not matter
    assert reciprocal_rank(["x", "y", "a", "b"], {"a", "b"}) == pytest.approx(1 / 3)


def test_reciprocal_rank_none():
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_reciprocal_rank_empty_gold_raises():
    with pytest.raises(ValueError):
        reciprocal_rank(["a"], set())


def test_normalize_removes_punctuation():
    assert normalize_answer("Hello, world!") == "hello world"


def test_normalize_removes_whole_word_articles_only():
    # "theory" and "another" contain article letters but are not articles
    assert normalize_answer("The theory of an another A idea") == "theory of another idea"


def test_normalize_collapses_whitespace():
    assert normalize_answer("  one \t two\n\nthree  ") == "one two three"


def test_normalize_lowercases():
    assert normalize_answer("PaRiS") == "paris"


def test_exact_match_true_after_normalization():
    assert exact_match("The Eiffel Tower!", "eiffel   tower") == 1.0


def test_exact_match_false():
    assert exact_match("Eiffel Tower", "Eiffel") == 0.0


def test_f1_partial_overlap_with_repeated_words():
    # "a" is an article and is dropped: pred words [b, b, c], gold words [b, c, c].
    # Multiset overlap = min(2, 1) for b + min(1, 2) for c = 2.
    # precision 2/3, recall 2/3 -> F1 = 2/3
    assert f1("a b b c", "b c c") == pytest.approx(2 / 3)


def test_f1_identical_is_one():
    assert f1("blue whale", "Blue Whale.") == 1.0


def test_f1_no_overlap_is_zero():
    assert f1("cat", "dog") == 0.0


def test_f1_yes_no_differ_is_zero():
    assert f1("yes", "no") == 0.0
    # token overlap would give 0.4 here; the special case forces 0.0
    assert f1("no", "no it is not") == 0.0
    assert f1("noanswer", "some answer") == 0.0


def test_f1_yes_yes_is_one():
    assert f1("Yes.", "yes") == 1.0


def test_f1_both_empty_is_one():
    # "the" normalizes to nothing
    assert f1("the", "") == 1.0


def test_f1_one_empty_is_zero():
    assert f1("", "paris") == 0.0
    assert f1("paris", "") == 0.0


def test_citation_precision_counts_distinct_sources():
    # cited a, a, b, x -> distinct {a, b, x}; gold {a, b} -> 2/3
    assert citation_precision(["a", "a", "b", "x"], {"a", "b"}) == pytest.approx(2 / 3)


def test_citation_precision_none_when_nothing_cited():
    assert citation_precision([], {"a"}) is None


def test_abstention_precision_recall():
    # abstained on q0, q1, q2; truly unanswerable q0, q1, q3
    # true positives 2 -> precision 2/3, recall 2/3
    predicted = [True, True, True, False]
    actual = [True, True, False, True]
    precision, recall = abstention_precision_recall(predicted, actual)
    assert precision == pytest.approx(2 / 3)
    assert recall == pytest.approx(2 / 3)


def test_abstention_nothing_predicted():
    assert abstention_precision_recall([False, False], [True, False]) == (0.0, 0.0)


def test_abstention_nothing_actual():
    assert abstention_precision_recall([True, False], [False, False]) == (0.0, 0.0)


def test_abstention_length_mismatch_raises():
    with pytest.raises(ValueError):
        abstention_precision_recall([True], [True, False])


def test_contradiction_precision_recall():
    # flagged q0, q1; planted q0, q2, q3. True positives 1 -> precision 1/2, recall 1/3
    predicted = [True, True, False, False]
    actual = [True, False, True, True]
    precision, recall = contradiction_precision_recall(predicted, actual)
    assert precision == 0.5
    assert recall == pytest.approx(1 / 3)


def test_contradiction_nothing_predicted():
    assert contradiction_precision_recall([False], [True]) == (0.0, 0.0)


def test_contradiction_nothing_actual():
    assert contradiction_precision_recall([True], [False]) == (0.0, 0.0)


def test_contradiction_length_mismatch_raises():
    with pytest.raises(ValueError):
        contradiction_precision_recall([True, False], [True])
