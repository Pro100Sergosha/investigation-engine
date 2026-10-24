"""Document indexing: dedup hashes now; insert, update and delete arrive with db.py."""

import hashlib
import unicodedata


def normalize(text: str) -> str:
    """Text as compared for dedup: NFKC, whitespace runs collapsed to one space, trimmed.

    Case is kept: two texts differing only in case are rare and may differ in meaning (ids, names).
    """
    return " ".join(unicodedata.normalize("NFKC", text).split())


def content_hash(text: str) -> str:
    """sha256 hex of the normalized text. The dataset job and `ingest` must dedup identically."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()
