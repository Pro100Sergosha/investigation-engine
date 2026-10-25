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
    """Store one document: `upsert_many([doc])[0]`, the same code path as a bulk shard."""
    return upsert_many([doc])[0]


def upsert_many(docs: list[ParsedDoc]) -> list[tuple[str, int | None]]:
    """Store each doc keyed by its source, with chunks of both strategies and their embeddings.

    Returns one (status, document_id) per doc, in input order, the same as storing the docs one
    after another:
    - "empty", None: blank text, nothing stored;
    - "unchanged", id: this source is stored with the same content hash (a rerun);
    - "duplicate", id of the other document: the same content hash under another source;
    - "inserted", new id: a new source;
    - "updated", id: a known source with new content: version + 1, chunks replaced.

    1. The checks run before any embedding, so a rerun of a shard costs no Bedrock call.
    2. A doc with the same source or hash as an earlier doc of `docs` that is about to be
       written is decided after that one is stored (a second round of this function), so two
       docs of one shard never both insert.
    3. The distinct embedding inputs of all docs to write are embedded in one go (96 per
       Bedrock request). An input is "<title>\\n\\n<chunk text>": a chunk alone often lacks the
       name of its subject ("He was born in ..."). A short paragraph is the same chunk under both
       strategies and is embedded once.
    4. Each doc is written in its own transaction: its row and its chunks change together.
    Raises on any Bedrock or database error. Docs written before the error stay, complete;
    nothing is half-written, and a rerun is safe (it returns "unchanged" for those).
    """
    results: list[tuple[str, int | None]] = [("empty", None)] * len(docs)
    to_write = []  # (position, doc, hash, id of the stored row with this source, or None)
    writing_sources, writing_hashes = set(), set()
    later = []  # positions decided in a second round, after this round's writes
    for i, doc in enumerate(docs):
        if not doc.text.strip():
            continue  # stays "empty"
        digest = content_hash(doc.text)
        if doc.source in writing_sources or digest in writing_hashes:
            later.append(i)
            continue
        same_source = db.run(
            "SELECT id, content_hash FROM documents WHERE source = :s", s=doc.source
        )
        if same_source and same_source[0][1] == digest:
            results[i] = ("unchanged", same_source[0][0])
            continue
        same_text = db.run("SELECT id FROM documents WHERE content_hash = :h", h=digest)
        if same_text:
            results[i] = ("duplicate", same_text[0][0])
            continue
        to_write.append((i, doc, digest, same_source[0][0] if same_source else None))
        writing_sources.add(doc.source)
        writing_hashes.add(digest)

    rows = {i: chunk_rows(doc) for i, doc, _, _ in to_write}
    # Embedded before any BEGIN: a request takes 2-3 s, a transaction should not wait on it.
    inputs = list(dict.fromkeys(row[3] for doc_rows in rows.values() for row in doc_rows))
    vectors = dict(zip(inputs, embed.embed_documents(inputs), strict=True))
    for i, doc, digest, existing_id in to_write:
        results[i] = _write(doc, digest, existing_id, rows[i], vectors)
        if results[i][0] == "lost":
            later.append(i)

    if later:
        # What blocked these docs is committed now, so the checks see it.
        later.sort()
        for i, result in zip(later, upsert_many([docs[i] for i in later]), strict=True):
            results[i] = result
    return results


def _write(
    doc: ParsedDoc,
    digest: str,
    existing_id: int | None,
    rows: list[tuple[str, int, str, str]],
    vectors: dict[str, list[float]],
) -> tuple[str, int | None]:
    """Insert the document, or update `existing_id`, with its chunks in one transaction.

    ("lost", None): another ingest Lambda stored this source or this text after the checks.
    """
    fields = {
        "title": doc.title,
        "doc_type": doc.doc_type,
        "text": doc.text,
        "metadata": json.dumps(doc.metadata),
        "hash": digest,
    }
    with db.transaction() as conn:
        if existing_id is not None:
            status, document_id = "updated", existing_id
            conn.run(
                "UPDATE documents SET title = :title, doc_type = :doc_type, text = :text,"
                " metadata = CAST(:metadata AS jsonb), content_hash = :hash,"
                " version = version + 1 WHERE id = :id",
                id=document_id,
                **fields,
            )
            conn.run("DELETE FROM chunks WHERE document_id = :id", id=document_id)
        else:
            # ON CONFLICT (either unique column) waits for the other transaction and then
            # inserts nothing instead of failing; the row that won decides, as on a rerun.
            inserted = conn.run(
                "INSERT INTO documents (source, title, doc_type, text, metadata, content_hash)"
                " VALUES (:source, :title, :doc_type, :text, CAST(:metadata AS jsonb), :hash)"
                " ON CONFLICT DO NOTHING RETURNING id",
                source=doc.source,
                **fields,
            )
            if not inserted:
                return "lost", None  # the empty transaction commits
            status, document_id = "inserted", inserted[0][0]
        # ponytail: one INSERT per chunk (~1-2 per HotpotQA paragraph); a multi-row INSERT
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
