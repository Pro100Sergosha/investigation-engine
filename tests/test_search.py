"""Tests for search.py: validation, row mapping and fusion wiring, without a database."""

from datetime import datetime, timedelta, timezone

import pytest

from engine import db, embed, search


def _no_calls(*args, **kwargs):
    raise AssertionError("must not reach Bedrock or the database")


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(embed, "embed_query", _no_calls)
    monkeypatch.setattr(db, "run", _no_calls)


@pytest.mark.parametrize(
    "kwargs",
    [{"strategy": "semantic"}, {"mode": "bm25"}, {"k": 0}, {"k": search.CANDIDATES + 1}],
)
def test_search_rejects_bad_arguments_before_any_call(offline, kwargs):
    with pytest.raises(ValueError):
        search.search("eiffel tower", **kwargs)


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_search_blank_query_is_empty_without_any_call(offline, query):
    assert search.search(query) == []


def test_get_chunks_empty_list_makes_no_call(offline):
    assert search.get_chunks([]) == []


def test_vector_text_round_trips_through_parse():
    text = search._vector_text([0.5, -1.25, 3e-05])
    assert text == "[0.5,-1.25,3e-05]"
    assert search._parse_vector(text) == [0.5, -1.25, 3e-05]


def test_parse_vector_reads_pgvector_output():
    assert search._parse_vector("[0.1,-0.0002,1]") == [0.1, -0.0002, 1.0]


def _row(chunk_id: int, document_id: int = 1, vector: str | None = None) -> list:
    return [chunk_id, document_id, f"title {document_id}", f"test:{document_id}", "text", vector]


def test_to_hits_keeps_ranking_order_and_drops_missing_rows():
    rows = [_row(3), _row(1)]  # ANY(:ids) returns rows in no particular order
    hits = search._to_hits([(1, 0.9), (2, 0.8), (3, 0.7)], rows)
    assert [(hit.chunk_id, hit.score) for hit in hits] == [(1, 0.9), (3, 0.7)]


def test_sources_in_order_follows_ids_skips_unknown_and_repeats():
    rows = [[7, 1, "t", "s", "seven", 0], [5, 2, "u", "r", "five", 3]]
    sources = search._sources_in_order([5, 99, 7, 5], rows)
    assert [source["chunk_id"] for source in sources] == [5, 7]
    assert sources[0] == {
        "chunk_id": 5,
        "document_id": 2,
        "title": "u",
        "source": "r",
        "text": "five",
        "ord": 3,
    }


def test_document_chunks_filters_by_strategy_and_keeps_sql_order(monkeypatch):
    calls = []

    def run(sql, **params):
        calls.append(params)
        return [[8, 2, "t", "s", "first", 0], [5, 2, "t", "s", "second", 1]]  # ORDER BY ord

    monkeypatch.setattr(db, "run", run)
    chunks = search.document_chunks(2, "fixed")
    assert calls == [{"id": 2, "strategy": "fixed"}]
    assert [(c["chunk_id"], c["ord"]) for c in chunks] == [(8, 0), (5, 1)]


def test_dense_prefix_sends_the_cut_query_and_keeps_the_scan_order(monkeypatch):
    calls = []

    def run(sql, **params):
        calls.append(params)
        if "subvector" in sql:
            return [[7, 0.9], [3, 0.8]]
        return [[3, 1, "t", "s", "three", None], [7, 1, "t", "s", "seven", None]]

    monkeypatch.setattr(db, "run", run)
    hits = search.dense_prefix([0.5, 0.25, 1.0], 2, k=2)
    assert calls[0] == {"q": "[0.5,0.25]", "dims": 2, "strategy": "fixed", "n": 2}
    assert [(h.chunk_id, h.score) for h in hits] == [(7, 0.9), (3, 0.8)]


def test_document_created_at_is_iso_utc():
    tbilisi = timezone(timedelta(hours=4))
    row = [1, "test:a", "A", "md", 2, datetime(2026, 10, 25, 18, 0, tzinfo=tbilisi), 6]
    assert search._document(row) == {
        "id": 1,
        "source": "test:a",
        "title": "A",
        "doc_type": "md",
        "version": 2,
        "created_at": "2026-10-25T14:00:00+00:00",
        "chunks": 6,
    }


def _fake_db(dense: list[tuple[int, float]], keyword: list[int], vectors: dict[int, str]):
    """Stands in for db.run by statement: fixed retriever outputs, hit rows for asked ids."""

    def run(sql, **params):
        if sql is search._DENSE_SQL:
            return [list(pair) for pair in dense]
        if sql is search._KEYWORD_SQL:
            return [[chunk_id] for chunk_id in keyword]
        assert sql is search._HITS_SQL
        # Every chunk its own document, so the MMR per-document cap does not interfere.
        return [_row(i, document_id=i, vector=vectors.get(i)) for i in reversed(params["ids"])]

    return run


@pytest.fixture
def fused_inputs(monkeypatch):
    monkeypatch.setattr(embed, "embed_query", lambda text: [1.0, 0.0])
    dense = [(1, 0.9), (2, 0.8), (3, 0.7)]
    keyword = [3, 4]
    # 1 and 3 point the same way, so MMR should push 3 down after picking 1.
    vectors = {1: "[1,0]", 2: "[0,1]", 3: "[1,0]", 4: "[0.7,0.7]"}
    monkeypatch.setattr(db, "run", _fake_db(dense, keyword, vectors))


def test_dense_mode_scores_are_cosine_similarities(fused_inputs):
    hits = search.search("q", k=2, mode="dense")
    assert [(hit.chunk_id, hit.score) for hit in hits] == [(1, 0.9), (2, 0.8)]


def test_hybrid_mode_fuses_dense_and_keyword_with_rrf(fused_inputs):
    hits = search.search("q", k=3, mode="hybrid")
    # k0=10, keyword at half weight: 3 is in both lists (dense rank 3, keyword rank 1) and gets
    # 1/13 + 0.5/11; keyword-only 4 (0.5/12) falls behind dense 1 and 2.
    assert [hit.chunk_id for hit in hits] == [3, 1, 2]
    assert hits[0].score == pytest.approx(1 / 13 + 0.5 / 11)


def test_mmr_mode_reranks_the_fused_candidates(fused_inputs):
    hits = search.search("q", k=3, mode="mmr")
    # Fused order is 3, 1, 2, 4; 1 duplicates 3's direction, so 2 comes before it. 4 is the
    # least relevant (min-max relevance 0) and stays out at lam 0.85.
    assert [hit.chunk_id for hit in hits] == [3, 2, 1]
