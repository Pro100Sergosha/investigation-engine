"""Two chunking strategies compared in the evaluation: fixed windows and structure-aware."""

# A "token" here is a whitespace-separated word (`text.split()`): no tokenizer dependency, and
# Cohere Embed V4's input limit (128k tokens) is far above 300 words.


def fixed_chunks(text: str, size: int = 300, overlap: int = 50) -> list[str]:
    """Strategy "fixed": windows of `size` words, each starting `size - overlap` words later.

    Words are re-joined with single spaces. Windowing stops at the first window that reaches the
    end of the text, so the last window may be shorter and never lies inside the previous one
    (300 words, size 300 -> exactly one chunk). Empty or whitespace-only text -> [].
    Raises ValueError unless 0 <= overlap < size.
    """
    if overlap < 0 or overlap >= size:  # also rejects size <= 0
        raise ValueError(f"need 0 <= overlap < size, got size={size}, overlap={overlap}")
    words = text.split()
    step = size - overlap
    chunks = []
    start = 0
    while start < len(words):
        end = start + size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break  # this window reached the end; another one would lie inside it
        start += step
    return chunks


def structured_chunks(text: str, max_words: int = 300) -> list[str]:
    """Strategy "structured": split on headings and paragraphs (the `ParsedDoc.text` shape).

    Consecutive paragraphs are packed into one chunk while it stays within `max_words`; a heading
    always starts a new chunk and is kept as its first line, so the chunk says what it is about.
    Headings with no paragraph before the next heading (h1 directly followed by h2) are stacked
    into the next chunk; trailing headings with no paragraph at all are dropped. Heading words
    count toward `max_words`. A paragraph longer than `max_words` is split with
    `fixed_chunks(p, max_words, 0)`; each piece is its own chunk and only the first one carries
    the headings (so it may exceed `max_words` by the heading words). Paragraphs inside a chunk
    stay separated by a blank line. Empty text -> [].
    Raises ValueError unless max_words > 0.
    """
    if max_words <= 0:
        raise ValueError(f"max_words must be > 0, got {max_words}")
    chunks = []
    parts = []  # the chunk being built: heading lines first, then paragraphs
    chunk_words = 0
    has_paragraph = False  # a chunk made only of headings is never emitted

    for block in _split_blocks(text):
        heading = ""
        if block[0].startswith("#"):
            # A heading may be followed by paragraph text with no blank line; cut it off.
            heading = " ".join(block[0].split())
            block = block[1:]
        words = " ".join(block).split()

        # A new heading, or a paragraph that does not fit, closes the chunk.
        if has_paragraph and (heading or chunk_words + len(words) > max_words):
            chunks.append("\n\n".join(parts))
            parts = []
            chunk_words = 0
            has_paragraph = False

        if heading:
            parts.append(heading)
            chunk_words += len(heading.split())
        if not words:
            continue

        paragraph = " ".join(words)
        if len(words) > max_words:
            # Only the first piece carries the headings; the chunk is closed right here.
            pieces = fixed_chunks(paragraph, max_words, 0)
            pieces[0] = "\n\n".join(parts + [pieces[0]])
            chunks.extend(pieces)
            parts = []
            chunk_words = 0
        else:
            parts.append(paragraph)
            chunk_words += len(words)
            has_paragraph = True

    if has_paragraph:
        chunks.append("\n\n".join(parts))
    return chunks


def _split_blocks(text: str) -> list[list[str]]:
    """Blocks are runs of non-blank lines; each block is a list of stripped lines."""
    blocks = []
    block = []
    for line in text.splitlines():  # splitlines also handles \r\n
        line = line.strip()
        if line == "":
            if block:
                blocks.append(block)
                block = []
        else:
            block.append(line)
    if block:
        blocks.append(block)
    return blocks
