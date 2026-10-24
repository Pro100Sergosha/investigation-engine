"""Two chunking strategies compared in the evaluation: fixed windows and structure-aware."""

# A "token" here is a whitespace-separated word (`text.split()`): no tokenizer dependency, and
# Titan's 8k-token input limit is far above 300 words.


def fixed_chunks(text: str, size: int = 300, overlap: int = 50) -> list[str]:
    """Strategy "fixed": windows of `size` words, each starting `size - overlap` words later.

    Words are re-joined with single spaces. Windowing stops at the first window that reaches the
    end of the text, so the last window may be shorter and never lies inside the previous one
    (300 words, size 300 -> exactly one chunk). Empty or whitespace-only text -> [].
    Raises ValueError unless 0 <= overlap < size.
    """
    raise NotImplementedError


def structured_chunks(text: str, max_words: int = 300) -> list[str]:
    """Strategy "structured": split on headings and paragraphs (the `ParsedDoc.text` shape).

    Consecutive paragraphs are packed into one chunk while it stays within `max_words`; a heading
    always starts a new chunk and is kept as its first line, so the chunk says what it is about.
    Headings with no paragraph before the next heading (h1 directly followed by h2) are stacked
    into the next chunk; trailing headings with no paragraph at all are dropped. Heading words
    count toward `max_words`. A paragraph longer than `max_words` is split with
    `fixed_chunks(p, max_words, 0)`; each piece is its own chunk and only the first one carries
    the headings (so it may exceed `max_words` by the heading words). Paragraphs inside a chunk stay separated by a blank line. Empty text -> [].
    Raises ValueError unless max_words > 0.
    """
    raise NotImplementedError
