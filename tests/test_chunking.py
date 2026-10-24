import pytest

from engine.chunking import fixed_chunks, structured_chunks


def numbered(n: int, start: int = 0) -> str:
    return " ".join(f"w{i}" for i in range(start, start + n))


# fixed_chunks


def test_fixed_empty_and_whitespace_only():
    assert fixed_chunks("") == []
    assert fixed_chunks(" \n\t  ") == []


def test_fixed_short_text_is_one_chunk():
    assert fixed_chunks("a b c", size=10, overlap=2) == ["a b c"]


def test_fixed_exactly_size_words_is_one_chunk():
    assert fixed_chunks(numbered(10), size=10, overlap=3) == [numbered(10)]


def test_fixed_second_chunk_starts_at_size_minus_overlap():
    chunks = fixed_chunks(numbered(11), size=10, overlap=3)
    assert len(chunks) == 2
    assert chunks[1].split()[0] == "w7"
    assert chunks[1] == numbered(4, start=7)  # last window is shorter


def test_fixed_overlap_words_repeat():
    first, second = fixed_chunks(numbered(15), size=10, overlap=4)
    assert first.split()[-4:] == second.split()[:4]


def test_fixed_zero_overlap_does_not_repeat_words():
    assert fixed_chunks(numbered(7), size=3, overlap=0) == ["w0 w1 w2", "w3 w4 w5", "w6"]


@pytest.mark.parametrize("size, overlap", [(10, -1), (10, 10), (10, 11), (0, 0)])
def test_fixed_invalid_size_or_overlap(size, overlap):
    with pytest.raises(ValueError):
        fixed_chunks("a b c", size=size, overlap=overlap)


def test_fixed_whitespace_is_normalized():
    assert fixed_chunks("a\tb\n\nc   d", size=10, overlap=0) == ["a b c d"]


# structured_chunks


def test_structured_empty_text():
    assert structured_chunks("") == []
    assert structured_chunks(" \n\n  \n") == []


def test_structured_packs_paragraphs_until_max_words_then_flushes():
    text = "a1 a2 a3\n\nb1 b2 b3\n\nc1 c2 c3"
    assert structured_chunks(text, max_words=6) == ["a1 a2 a3\n\nb1 b2 b3", "c1 c2 c3"]


def test_structured_paragraph_filling_max_words_exactly_stays_in_chunk():
    assert structured_chunks("a1 a2\n\nb1 b2", max_words=4) == ["a1 a2\n\nb1 b2"]


def test_structured_heading_starts_new_chunk_as_first_line():
    text = "a1 a2\n\n# Title\n\nb1 b2"
    assert structured_chunks(text, max_words=100) == ["a1 a2", "# Title\n\nb1 b2"]


def test_structured_heading_directly_followed_by_text_is_separated():
    text = "intro\n\n# Title\nbody one\nbody two"
    assert structured_chunks(text, max_words=100) == ["intro", "# Title\n\nbody one body two"]


def test_structured_stacked_headings_go_into_next_chunk():
    text = "# H1\n\n## H2\n\nbody"
    assert structured_chunks(text) == ["# H1\n\n## H2\n\nbody"]


def test_structured_trailing_heading_is_dropped():
    assert structured_chunks("body\n\n# Last") == ["body"]
    assert structured_chunks("# Only\n\n## Headings") == []


def test_structured_long_paragraph_is_split_and_only_first_piece_has_heading():
    text = "# Title\n\n" + numbered(7)
    assert structured_chunks(text, max_words=3) == [
        "# Title\n\nw0 w1 w2",  # exceeds max_words by the heading word
        "w3 w4 w5",
        "w6",
    ]


def test_structured_long_paragraph_closes_the_chunk_before_it():
    text = "short one\n\n" + numbered(5)
    assert structured_chunks(text, max_words=3) == ["short one", "w0 w1 w2", "w3 w4"]


def test_structured_heading_words_count_toward_max_words():
    text = "# Two words\n\na1 a2\n\nb1 b2"
    # heading (3 words) + a (2) = 5 fits; b would make 7 > 6
    assert structured_chunks(text, max_words=6) == ["# Two words\n\na1 a2", "b1 b2"]


def test_structured_paragraph_that_fits_only_without_heading_is_not_split():
    # The heading is never separated from its first paragraph: the chunk overflows instead.
    assert structured_chunks("# Head\n\na1 a2 a3", max_words=3) == ["# Head\n\na1 a2 a3"]


def test_structured_paragraphs_in_chunk_separated_by_exactly_one_blank_line():
    text = "a1\n\n\n\n   \nb1\nb2\n\n\nc1"
    assert structured_chunks(text, max_words=100) == ["a1\n\nb1 b2\n\nc1"]


def test_structured_crlf_input():
    text = "# T\r\n\r\na1 a2\r\nmore\r\n\r\nb1"
    assert structured_chunks(text, max_words=100) == ["# T\n\na1 a2 more\n\nb1"]


@pytest.mark.parametrize("max_words", [0, -5])
def test_structured_invalid_max_words(max_words):
    with pytest.raises(ValueError):
        structured_chunks("a b", max_words=max_words)


def test_structured_keeps_every_word_in_order():
    text = (
        "# Report\n\n"
        "## Summary\n"
        f"{numbered(4)}\n\n"
        f"{numbered(30, start=4)}\n\n"
        "# Details\n\n"
        f"{numbered(5, start=34)}\n\n"
        f"{numbered(5, start=39)}"
    )
    chunks = structured_chunks(text, max_words=12)
    assert len(chunks) > 3  # the sample really exercises packing and splitting
    # No heading is repeated or dropped here, so the words must match one to one.
    assert " ".join(chunks).split() == text.split()
