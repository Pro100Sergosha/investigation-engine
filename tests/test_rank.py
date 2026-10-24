"""Tests for rank.py: RRF and MMR, pure logic with small hand-checkable vectors."""

import pytest

from engine.models import Hit
from engine.rank import mmr, rrf


def _hit(chunk_id: int, score: float, document_id: int | None = None) -> Hit:
    # By default every chunk is its own document, so the per-document cap does not interfere.
    return Hit(
        chunk_id=chunk_id,
        document_id=document_id if document_id is not None else chunk_id,
        title=f"doc {chunk_id}",
        source=f"test:{chunk_id}",
        text=f"chunk {chunk_id}",
        score=score,
    )


def _ids(hits: list[Hit]) -> list[int]:
    return [hit.chunk_id for hit in hits]


# --- rrf ---


def test_rrf_single_list_keeps_order_and_scores():
    assert rrf([[7, 3, 9]]) == [(7, 1 / 61), (3, 1 / 62), (9, 1 / 63)]


def test_rrf_id_in_both_lists_outranks_ids_in_one():
    # 2 is rank 2 in both lists: 2/62 beats 1/61 of the ids that are first in only one list.
    result = rrf([[1, 2], [3, 2]])
    assert [chunk_id for chunk_id, _ in result] == [2, 1, 3]
    assert result[0][1] == pytest.approx(1 / 62 + 1 / 62)


def test_rrf_id_missing_from_a_list_gets_nothing_from_it():
    result = dict(rrf([[1, 2], [2]]))
    assert result[1] == 1 / 61
    assert result[2] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_duplicate_id_in_one_list_counts_once_at_best_rank():
    # 5 appears at ranks 1 and 3; only rank 1 counts. The repeat still occupies rank 3.
    result = dict(rrf([[5, 6, 5, 7]]))
    assert result[5] == 1 / 61
    assert result[7] == 1 / 64


def test_rrf_ties_broken_by_smaller_id():
    assert rrf([[9], [4]]) == [(4, 1 / 61), (9, 1 / 61)]


def test_rrf_empty_input():
    assert rrf([]) == []
    assert rrf([[], []]) == []


def test_rrf_custom_k0_changes_scores():
    assert rrf([[1, 2]], k0=0) == [(1, 1 / 1), (2, 1 / 2)]


# --- mmr ---


def test_mmr_lam_one_is_pure_relevance_order():
    hits = [_hit(1, 0.2), _hit(2, 0.9), _hit(3, 0.5)]
    # Identical vectors: similarity would punish duplicates if lam < 1.
    vectors = {1: [1.0, 0.0], 2: [1.0, 0.0], 3: [1.0, 0.0]}
    assert _ids(mmr(hits, vectors, k=3, lam=1.0)) == [2, 3, 1]


def test_mmr_lam_zero_avoids_near_duplicate():
    hits = [_hit(1, 1.0), _hit(2, 0.9), _hit(3, 0.1)]
    vectors = {1: [1.0, 0.0], 2: [1.0, 0.1], 3: [0.0, 1.0]}
    # lam=0: first pick is a tie at 0 -> earlier candidate (1). Then hit 2 is ~0.995 similar
    # to 1 (value -0.995), hit 3 is orthogonal (value 0) -> 3 beats 2 despite lower score.
    assert _ids(mmr(hits, vectors, k=2, lam=0.0)) == [1, 3]


def test_mmr_balances_relevance_and_diversity_by_hand():
    # lam = 0.5. Scores 1.0, 0.9, 0.5 -> relevance 1.0, 0.9, 0.5 (best score is 1.0).
    # A=(1,0), B=(1,0) (copy of A), C=(0,1).
    # Step 1, nothing picked, similarity 0: A = 0.5, B = 0.45, C = 0.25 -> A.
    # Step 2: B = 0.5*0.9 - 0.5*cos(A,B)=1 -> -0.05; C = 0.5*0.5 - 0.5*0 = 0.25 -> C.
    # Step 3: B is the only one left.
    hits = [_hit(1, 1.0), _hit(2, 0.9), _hit(3, 0.5)]
    vectors = {1: [1.0, 0.0], 2: [1.0, 0.0], 3: [0.0, 1.0]}
    assert _ids(mmr(hits, vectors, k=3, lam=0.5)) == [1, 3, 2]


def test_mmr_relevance_is_normalized_by_best_score():
    # Raw scores are tiny (RRF-like). lam=0.9, relevance = score / 0.04 = 1, 0.75, 0.25.
    # Step 2: hit 2 = 0.9*0.75 - 0.1*1 = 0.575; hit 3 = 0.9*0.25 - 0 = 0.225 -> 2 wins.
    # Without normalization hit 2 = 0.9*0.03 - 0.1 < 0 and the dissimilar hit 3 would win.
    # With lam=0.5: hit 2 = 0.5*0.75 - 0.5 = -0.125; hit 3 = 0.5*0.25 = 0.125 -> 3 wins.
    hits = [_hit(1, 0.04), _hit(2, 0.03), _hit(3, 0.01)]
    vectors = {1: [1.0, 0.0], 2: [1.0, 0.0], 3: [0.0, 1.0]}
    assert _ids(mmr(hits, vectors, k=2, lam=0.9)) == [1, 2]
    assert _ids(mmr(hits, vectors, k=2, lam=0.5)) == [1, 3]


def test_mmr_per_doc_cap_one_gives_one_hit_per_document():
    # Hits 1 and 2 are the most relevant but share document 10.
    hits = [_hit(1, 1.0, 10), _hit(2, 0.9, 10), _hit(3, 0.2, 20)]
    vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [1.0, 1.0]}
    assert _ids(mmr(hits, vectors, k=3, lam=1.0, per_doc_cap=1)) == [1, 3]


def test_mmr_cap_can_leave_fewer_than_k():
    hits = [_hit(1, 1.0, 10), _hit(2, 0.9, 10), _hit(3, 0.8, 10)]
    vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [1.0, 1.0]}
    assert _ids(mmr(hits, vectors, k=3, per_doc_cap=2)) == [1, 2]


def test_mmr_k_larger_than_candidates_returns_all():
    hits = [_hit(1, 0.5), _hit(2, 0.4)]
    vectors = {1: [1.0, 0.0], 2: [0.0, 1.0]}
    assert _ids(mmr(hits, vectors, k=10)) == [1, 2]


def test_mmr_k_zero_or_negative_returns_empty():
    hits = [_hit(1, 0.5)]
    assert mmr(hits, {1: [1.0]}, k=0) == []
    assert mmr(hits, {1: [1.0]}, k=-1) == []


def test_mmr_no_candidates_returns_empty():
    assert mmr([], {}) == []


def test_mmr_zero_vector_has_zero_similarity():
    # Hit 2 is a zero vector: similarity to hit 1 is 0 (not a ZeroDivisionError), so with
    # lam=0.5 it scores 0.5*0.8 = 0.4, beating hit 3 = 0.5*0.5 - 0.5*cos(1,3)=1 -> -0.25.
    hits = [_hit(1, 1.0), _hit(2, 0.8), _hit(3, 0.5)]
    vectors = {1: [1.0, 0.0], 2: [0.0, 0.0], 3: [1.0, 0.0]}
    assert _ids(mmr(hits, vectors, k=2, lam=0.5)) == [1, 2]


def test_mmr_all_scores_zero_does_not_divide_by_zero():
    # Relevance is 0 for all; with lam=0.5 the second pick is the dissimilar one.
    hits = [_hit(1, 0.0), _hit(2, 0.0), _hit(3, 0.0)]
    vectors = {1: [1.0, 0.0], 2: [1.0, 0.0], 3: [0.0, 1.0]}
    assert _ids(mmr(hits, vectors, k=2, lam=0.5)) == [1, 3]


def test_mmr_missing_vector_raises_keyerror():
    hits = [_hit(1, 1.0), _hit(2, 0.5)]
    with pytest.raises(KeyError):
        mmr(hits, {1: [1.0, 0.0]})


@pytest.mark.parametrize("lam", [-0.1, 1.1])
def test_mmr_lam_out_of_range_raises(lam):
    with pytest.raises(ValueError):
        mmr([_hit(1, 1.0)], {1: [1.0]}, lam=lam)


def test_mmr_per_doc_cap_zero_raises():
    with pytest.raises(ValueError):
        mmr([_hit(1, 1.0)], {1: [1.0]}, per_doc_cap=0)


def test_mmr_validates_args_even_without_candidates():
    with pytest.raises(ValueError):
        mmr([], {}, lam=2.0)


def test_mmr_returns_same_hit_objects_unchanged():
    hits = [_hit(1, 0.5), _hit(2, 0.9)]
    vectors = {1: [1.0, 0.0], 2: [0.0, 1.0]}
    result = mmr(hits, vectors, k=2, lam=1.0)
    assert result[0] is hits[1]
    assert result[1] is hits[0]
    assert (hits[0].score, hits[1].score) == (0.5, 0.9)


def test_mmr_tie_goes_to_earlier_candidate():
    hits = [_hit(1, 0.5), _hit(2, 0.5), _hit(3, 0.5)]
    vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [1.0, 1.0]}
    assert _ids(mmr(hits, vectors, k=1, lam=1.0)) == [1]
