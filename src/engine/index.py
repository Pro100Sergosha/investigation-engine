"""Writes: dedup hashes, and storing, updating and deleting documents with their chunks."""

import hashlib
import unicodedata

from engine.models import ParsedDoc


def normalize(text: str) -> str:
    """Text as compared for dedup: NFKC, whitespace runs collapsed to one space, trimmed.

    Case is kept: two texts differing only in case are rare and may differ in meaning (ids, names).
    """
    return " ".join(unicodedata.normalize("NFKC", text).split())


def content_hash(text: str) -> str:
    """sha256 hex of the normalized text. The dataset job and `ingest` must dedup identically."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def upsert(doc: ParsedDoc) -> tuple[str, int | None]:
    """Store `doc` keyed by its source, with chunks of both strategies and their embeddings.

    Returns (status, document_id):
    - "empty", None: blank text, nothing stored;
    - "unchanged", id: this source is stored with the same content hash (a rerun);
    - "duplicate", id of the other document: the same content hash under another source;
    - "inserted", new id: a new source;
    - "updated", id: a known source with new content: version + 1, chunks replaced.
    The checks run before any embedding, so a rerun of a shard costs no Bedrock calls. Each
    chunk is embedded as "<title>\\n\\n<chunk text>": a chunk alone often lacks the name of its
    subject ("He was born in ..."). The document row and its chunks change in one transaction.
    """
    raise NotImplementedError


def delete(document_id: int) -> bool:
    """Delete a document and (by cascade) its chunks. False if the id is unknown."""
    raise NotImplementedError
