from engine.index import content_hash, normalize


def test_normalize_collapses_whitespace_and_unicode_forms():
    assert normalize("  Acme Payments\n\n outage\t") == "Acme Payments outage"
    assert normalize("ﬁle") == "file"  # NFKC folds the ligature


def test_content_hash_ignores_formatting_but_not_case():
    assert content_hash("a  b\nc") == content_hash("a b c")
    assert content_hash("a b c") != content_hash("A b c")
    assert len(content_hash("")) == 64
