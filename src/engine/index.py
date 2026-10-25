"""Writes: dedup hashes, and storing, updating and deleting documents with their chunks."""

import hashlib
import json
import unicodedata

from engine import chunking, db, embed
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
    Raises on any database error; nothing is half-written, and a rerun is safe.
    """
    if not doc.text.strip():
        return "empty", None
    digest = content_hash(doc.text)
    same_source = db.run("SELECT id, content_hash FROM documents WHERE source = :s", s=doc.source)
    if same_source and same_source[0][1] == digest:
        return "unchanged", same_source[0][0]
    same_text = db.run("SELECT id FROM documents WHERE content_hash = :h", h=digest)
    if same_text:
        return "duplicate", same_text[0][0]

    rows = chunk_rows(doc)
    # Embedded before BEGIN: Bedrock takes ~0.1-0.2 s per call, a transaction should not wait.
    vectors = _embed_distinct([embed_input for _, _, _, embed_input in rows])
    fields = {
        "title": doc.title,
        "doc_type": doc.doc_type,
        "text": doc.text,
        "metadata": json.dumps(doc.metadata),
        "hash": digest,
    }
    with db.transaction() as conn:
        if same_source:
            status, document_id = "updated", same_source[0][0]
            conn.run(
                "UPDATE documents SET title = :title, doc_type = :doc_type, text = :text,"
                " metadata = CAST(:metadata AS jsonb), content_hash = :hash,"
                " version = version + 1 WHERE id = :id",
                id=document_id,
                **fields,
            )
            conn.run("DELETE FROM chunks WHERE document_id = :id", id=document_id)
        else:
            # Another ingest Lambda may have stored this source or this text after the checks
            # above. ON CONFLICT (either unique column) waits for that transaction and then
            # inserts nothing instead of failing; the row that won decides, as on a rerun.
            inserted = conn.run(
                "INSERT INTO documents (source, title, doc_type, text, metadata, content_hash)"
                " VALUES (:source, :title, :doc_type, :text, CAST(:metadata AS jsonb), :hash)"
                " ON CONFLICT DO NOTHING RETURNING id",
                source=doc.source,
                **fields,
            )
            status, document_id = ("inserted", inserted[0][0]) if inserted else ("lost", None)
        if document_id is not None:
            # ponytail: one INSERT per chunk (~2 per HotpotQA paragraph); a multi-row INSERT
            # if uploads with hundreds of chunks get slow.
            for strategy, ord_, text, embed_input in rows:
                conn.run(
                    "INSERT INTO chunks (document_id, strategy, ord, text, embedding)"
                    " VALUES (:id, :strategy, :ord, :text, CAST(:embedding AS halfvec(1024)))",
                    id=document_id,
                    strategy=strategy,
                    ord=ord_,
                    text=text,
                    embedding=json.dumps(vectors[embed_input]),
                )
    if status == "lost":
        return upsert(doc)  # the other row is committed now: this returns unchanged/duplicate
    return status, document_id


def delete(document_id: int) -> bool:
    """Delete a document and (by cascade) its chunks. False if the id is unknown.

    ponytail: if the connection dies after the server ran the DELETE, `db.run` retries it and
    the retry finds nothing, so a successful delete can report False (the API answers 404).
    """
    return bool(db.run("DELETE FROM documents WHERE id = :id RETURNING id", id=document_id))


def chunk_rows(doc: ParsedDoc) -> list[tuple[str, int, str, str]]:
    """(strategy, ord, chunk text, embedding input) for every chunk of both strategies.

    The stored and searched text is the chunk alone; the embedding input adds the title.
    """
    rows = []
    for strategy, chunker in (
        ("fixed", chunking.fixed_chunks),
        ("structured", chunking.structured_chunks),
    ):
        for ord_, text in enumerate(chunker(doc.text)):
            rows.append((strategy, ord_, text, f"{doc.title}\n\n{text}"))
    return rows


def _embed_distinct(inputs: list[str]) -> dict[str, list[float]]:
    """Embedding per distinct input. A short paragraph is one chunk under both strategies, so
    this halves the Bedrock calls of the HotpotQA bulk load."""
    vectors = {}
    for text in inputs:
        if text not in vectors:
            vectors[text] = embed.embed(text)
    return vectors
