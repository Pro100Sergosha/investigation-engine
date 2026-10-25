from contextlib import contextmanager

import pytest

from engine import db, embed, index
from engine.index import chunk_rows, content_hash, normalize
from engine.models import ParsedDoc


def _doc(text: str, title: str = "Ada Lovelace", source: str = "test:ada") -> ParsedDoc:
    return ParsedDoc(source=source, title=title, doc_type="md", text=text)


class FakeDB:
    """Just enough of `documents` for upsert_many: rows by source, the statements it sends."""

    def __init__(self):
        self.rows: dict[str, list] = {}  # source -> [id, content_hash, version]
        self.chunks: dict[int, int] = {}  # document id -> chunk count
        self.on_insert = None  # called before a document INSERT: simulates another Lambda

    def run(self, sql: str, **params) -> list[list]:
        if sql.startswith("SELECT id, content_hash"):
            row = self.rows.get(params["s"])
            return [row[:2]] if row else []
        if sql.startswith("SELECT id FROM documents"):
            return [[row[0]] for row in self.rows.values() if row[1] == params["h"]]
        if sql.startswith("INSERT INTO documents"):
            if self.on_insert:
                self.on_insert()
            taken = params["source"] in self.rows or any(
                row[1] == params["hash"] for row in self.rows.values()
            )
            if taken:
                return []
            self.rows[params["source"]] = [len(self.rows) + 1, params["hash"], 1]
            return [[len(self.rows)]]
        if sql.startswith("UPDATE documents"):
            row = next(row for row in self.rows.values() if row[0] == params["id"])
            row[1], row[2] = params["hash"], row[2] + 1
        elif sql.startswith("DELETE FROM chunks"):
            self.chunks.pop(params["id"], None)
        elif sql.startswith("INSERT INTO chunks"):
            self.chunks[params["id"]] = self.chunks.get(params["id"], 0) + 1
        return []

    @contextmanager
    def transaction(self):
        yield self


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(db, "run", fake.run)
    monkeypatch.setattr(db, "transaction", fake.transaction)
    return fake


@pytest.fixture
def embedded(monkeypatch):
    """Records each embed_documents call (its list of inputs)."""
    calls: list[list[str]] = []

    def embed_documents(texts):
        calls.append(texts)
        return [[0.0] * 3 for _ in texts]

    monkeypatch.setattr(embed, "embed_documents", embed_documents)
    return calls


def test_normalize_collapses_whitespace_and_unicode_forms():
    assert normalize("  Acme Payments\n\n outage\t") == "Acme Payments outage"
    assert normalize("ﬁle") == "file"  # NFKC folds the ligature


def test_content_hash_ignores_formatting_but_not_case():
    assert content_hash("a  b\nc") == content_hash("a b c")
    assert content_hash("a b c") != content_hash("A b c")
    assert len(content_hash("")) == 64


def test_upsert_skips_blank_text_before_touching_the_database():
    # db.run would fail here (no DB_HOST), and so would Bedrock: the blank check must come first.
    assert index.upsert(_doc(" \n\t ")) == ("empty", None)


def test_chunk_rows_has_both_strategies_numbered_from_zero():
    text = "# Life\n\n" + "word " * 400
    rows = chunk_rows(_doc(text))
    for strategy in ("fixed", "structured"):
        ords = [ord_ for s, ord_, _, _ in rows if s == strategy]
        assert ords == list(range(len(ords))) and len(ords) >= 2


def test_embedding_input_is_title_then_chunk_but_stored_text_is_chunk_alone():
    rows = chunk_rows(_doc("He was born in London."))
    assert rows[0][2] == "He was born in London."
    assert rows[0][3] == "Ada Lovelace\n\nHe was born in London."


def test_identical_chunks_of_both_strategies_are_embedded_once(fake_db, embedded):
    doc = _doc("A short paragraph, one chunk under both strategies.")
    assert index.upsert(doc) == ("inserted", 1)
    assert embedded == [[chunk_rows(doc)[0][3]]]
    assert fake_db.chunks == {1: 2}  # both strategies stored from one embedding


def test_upsert_many_embeds_only_new_docs_and_each_input_once(fake_db, embedded):
    old = _doc("Already stored.", source="test:old")
    fake_db.rows["test:old"] = [1, content_hash(old.text), 1]
    words = [f"w{i}" for i in range(400)]
    long = _doc(" ".join(words), title="T", source="test:long")
    # Its only chunk is the first fixed chunk of `long`: one embedding input shared by two docs.
    short = _doc(" ".join(words[:300]), title="T", source="test:short")
    results = index.upsert_many([old, long, _doc(" "), short])
    assert results == [("unchanged", 1), ("inserted", 2), ("empty", None), ("inserted", 3)]
    assert len(embedded) == 1  # one call for the whole batch
    sent = embedded[0]
    expected = {row[3] for doc in (long, short) for row in chunk_rows(doc)}
    assert len(sent) == len(set(sent)) and set(sent) == expected
    assert len(sent) < len(chunk_rows(long)) + len(chunk_rows(short))
    assert not any("Already stored." in text for text in sent)


def test_same_text_or_source_twice_in_one_batch_is_decided_like_one_by_one(fake_db, embedded):
    first = _doc("Version one.", source="test:a")
    same_text = _doc("Version one.", source="test:b")
    same_source = _doc("Version two.", source="test:a")
    results = index.upsert_many([first, same_text, same_source])
    assert results == [("inserted", 1), ("duplicate", 1), ("updated", 1)]
    assert fake_db.rows == {"test:a": [1, content_hash("Version two."), 2]}
    assert len(embedded) == 2  # the second round embeds only the update


def test_a_doc_stored_meanwhile_by_another_lambda_becomes_unchanged(fake_db, embedded):
    doc = _doc("Raced.")

    def other_lambda():
        fake_db.on_insert = None
        fake_db.rows[doc.source] = [7, content_hash(doc.text), 1]

    fake_db.on_insert = other_lambda
    assert index.upsert_many([doc]) == [("unchanged", 7)]


def test_upsert_is_upsert_many_of_one(fake_db, embedded):
    doc = _doc("Once.")
    assert index.upsert(doc) == ("inserted", 1)
    assert index.upsert(doc) == index.upsert_many([doc])[0] == ("unchanged", 1)
    assert [texts for texts in embedded if texts] == [["Ada Lovelace\n\nOnce."]]  # reruns: none
