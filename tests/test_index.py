from engine import embed, index
from engine.index import chunk_rows, content_hash, normalize
from engine.models import ParsedDoc


def _doc(text: str, title: str = "Ada Lovelace") -> ParsedDoc:
    return ParsedDoc(source="test:ada", title=title, doc_type="md", text=text)


def test_normalize_collapses_whitespace_and_unicode_forms():
    assert normalize("  Acme Payments\n\n outage\t") == "Acme Payments outage"
    assert normalize("ﬁle") == "file"  # NFKC folds the ligature


def test_content_hash_ignores_formatting_but_not_case():
    assert content_hash("a  b\nc") == content_hash("a b c")
    assert content_hash("a b c") != content_hash("A b c")
    assert len(content_hash("")) == 64


def test_upsert_skips_blank_text_before_touching_the_database():
    # db.run would fail here (no DB_HOST): the blank check must come first.
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


def test_identical_chunks_of_both_strategies_are_embedded_once(monkeypatch):
    calls = []
    monkeypatch.setattr(embed, "embed", lambda text: calls.append(text) or [0.0])
    rows = chunk_rows(_doc("A short paragraph, one chunk under both strategies."))
    vectors = index._embed_distinct([embed_input for _, _, _, embed_input in rows])
    assert len(rows) == 2 and len(calls) == 1
    assert set(vectors) == {rows[0][3]}
