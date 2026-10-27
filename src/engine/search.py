"""Reads: hybrid search (dense + keyword -> RRF -> MMR) and lookups of documents and chunks."""

from datetime import UTC

from engine import db, embed, rank
from engine.models import Hit, ParsedDoc

STRATEGIES = ("fixed", "structured")
MODES = ("dense", "hybrid", "mmr")

# Candidates per retriever, and the MMR pool. Equal to pgvector's hnsw.ef_search default: one
# HNSW scan returns at most ef_search rows, so asking for more would not get more. 40 is also
# what keeps pure-Python MMR fast (rank.mmr).
CANDIDATES = 40

# Fusion and diversity settings, chosen by the retrieval sweep over the eval questions (ADR 0029).
# The keyword list is noisy (OR over every word of a long question), so it counts half; k0=10
# instead of the usual 60 keeps dense's top ranks clearly ahead of a keyword-only match.
RRF_K0 = 10
KEYWORD_WEIGHT = 0.5
MMR_LAMBDA = 0.85

# The partial HNSW index of the strategy serves this (sql/schema.sql, ADR 0024).
_DENSE_SQL = """
SELECT id, 1 - (embedding <=> CAST(:q AS halfvec(1024)))
FROM chunks
WHERE strategy = :strategy AND embedding IS NOT NULL
ORDER BY embedding <=> CAST(:q AS halfvec(1024))
LIMIT :n
"""

# Eval only, the embedding comparison (ADR 0032): cosine on the first :dims numbers of the stored
# 1024 (Cohere V4 vectors are Matryoshka: a prefix is a smaller embedding). The expression is not
# the indexed column, so this is an exact scan of every chunk of the strategy, no HNSW.
_DENSE_PREFIX_SQL = """
SELECT id, 1 - (subvector(embedding, 1, CAST(:dims AS int)) <=> CAST(:q AS halfvec))
FROM chunks
WHERE strategy = :strategy AND embedding IS NOT NULL
ORDER BY subvector(embedding, 1, CAST(:dims AS int)) <=> CAST(:q AS halfvec)
LIMIT :n
"""

# plainto_tsquery ANDs every word, so a long multi-hop question matches almost no chunk. Its
# text form is "'a' & 'b'"; turning each " & " into " | " gives OR, and ts_rank_cd still
# ranks chunks with more of the words higher. Lexemes never contain spaces, so the replace
# cannot cut one. Only stop words -> empty query -> matches nothing, no error.
_KEYWORD_SQL = """
SELECT c.id
FROM chunks c,
     (SELECT CAST(replace(plainto_tsquery('english', :q)::text, ' & ', ' | ') AS tsquery) AS q) t
WHERE c.strategy = :strategy AND c.tsv @@ t.q
ORDER BY ts_rank_cd(c.tsv, t.q) DESC, c.id
LIMIT :n
"""

# Vectors only when MMR needs them: 1024 numbers as text are ~10 KB per row.
_HITS_SQL = """
SELECT c.id, c.document_id, d.title, d.source, c.text,
       CASE WHEN :vectors THEN c.embedding::text END
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE c.id = ANY(:ids)
"""

_DOCUMENT_COLUMNS = """
d.id, d.source, d.title, d.doc_type, d.version, d.created_at,
(SELECT count(*) FROM chunks c WHERE c.document_id = d.id)
"""


def search(query: str, k: int = 10, strategy: str = "fixed", mode: str = "mmr") -> list[Hit]:
    """Top `k` chunks of one chunking `strategy` ("fixed" | "structured") for `query`.

    `mode` selects the evaluated configuration: "dense" (vector search only, score = cosine
    similarity), "hybrid" (dense top-N and keyword top-N fused by `rank.rrf` with the keyword
    list at `KEYWORD_WEIGHT`, score = RRF score), "mmr" (hybrid, then `rank.mmr` at
    `MMR_LAMBDA` with its per-document cap). Blank query -> [].
    Raises ValueError on an unknown strategy or mode, or k outside 1..CANDIDATES.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}, expected one of {STRATEGIES}")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")
    if not 1 <= k <= CANDIDATES:
        raise ValueError(f"k must be in 1..{CANDIDATES}, got {k}")
    if not query.strip():
        return []

    vector = _vector_text(embed.embed_query(query))
    dense = [
        (row[0], row[1]) for row in db.run(_DENSE_SQL, q=vector, strategy=strategy, n=CANDIDATES)
    ]
    if mode == "dense":
        return _hits(dense[:k])

    keyword = [row[0] for row in db.run(_KEYWORD_SQL, q=query, strategy=strategy, n=CANDIDATES)]
    fused = rank.rrf(
        [[chunk_id for chunk_id, _ in dense], keyword], k0=RRF_K0, weights=[1.0, KEYWORD_WEIGHT]
    )
    if mode == "hybrid":
        return _hits(fused[:k])

    pool = fused[:CANDIDATES]
    rows = db.run(_HITS_SQL, ids=[chunk_id for chunk_id, _ in pool], vectors=True)
    candidates = _to_hits(pool, rows)
    vectors = {row[0]: _parse_vector(row[5]) for row in rows}
    return rank.mmr(candidates, vectors, k, lam=MMR_LAMBDA)


def dense_prefix(vector: list[float], dims: int, k: int = 10, strategy: str = "fixed") -> list[Hit]:
    """Exact dense search with the first `dims` numbers of `vector` and of every stored vector.

    For the eval's embedding comparison only: a full scan takes seconds, not milliseconds.
    """
    rows = db.run(
        _DENSE_PREFIX_SQL, q=_vector_text(vector[:dims]), dims=dims, strategy=strategy, n=k
    )
    return _hits([(row[0], row[1]) for row in rows])


def _hits(scored: list[tuple[int, float]]) -> list[Hit]:
    if not scored:
        return []
    rows = db.run(_HITS_SQL, ids=[chunk_id for chunk_id, _ in scored], vectors=False)
    return _to_hits(scored, rows)


def _to_hits(scored: list[tuple[int, float]], rows: list[list]) -> list[Hit]:
    """Hits in the order of `scored` (best first); ids without a row (deleted meanwhile) dropped.

    `ANY(:ids)` returns rows in no particular order, so the ranking order is restored here.
    """
    by_id = {row[0]: row for row in rows}
    hits = []
    for chunk_id, score in scored:
        row = by_id.get(chunk_id)
        if row is not None:
            hits.append(Hit(row[0], row[1], row[2], row[3], row[4], score))
    return hits


def _vector_text(vector: list[float]) -> str:
    """pgvector's text input format, "[0.1,0.2]": vectors travel as text and are cast in SQL."""
    return "[" + ",".join(str(x) for x in vector) + "]"


def _parse_vector(text: str) -> list[float]:
    """Inverse of `_vector_text` for `embedding::text`: "[0.1,0.2]" -> [0.1, 0.2]."""
    return [float(x) for x in text.strip("[]").split(",")]


def get_document(document_id: int) -> ParsedDoc | None:
    """The stored document (full text, metadata) for the agent's tool, or None if unknown."""
    rows = db.run(
        "SELECT source, title, doc_type, text, metadata FROM documents WHERE id = :id",
        id=document_id,
    )
    if not rows:
        return None
    source, title, doc_type, text, metadata = rows[0]
    return ParsedDoc(source=source, title=title, doc_type=doc_type, text=text, metadata=metadata)


def list_documents(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """A page of documents newest first, and the total count.

    Each dict is the API `Document`: {"id", "source", "title", "doc_type", "version",
    "created_at" (ISO 8601 UTC string), "chunks" (count over all strategies)} (llm-wiki/04).
    """
    rows = db.run(
        f"SELECT {_DOCUMENT_COLUMNS} FROM documents d "
        "ORDER BY d.created_at DESC, d.id DESC LIMIT :limit OFFSET :offset",
        limit=limit,
        offset=offset,
    )
    total = db.run("SELECT count(*) FROM documents")[0][0]
    return [_document(row) for row in rows], total


def document_detail(document_id: int) -> dict | None:
    """The API `Document` plus "text" and "metadata", or None if unknown."""
    rows = db.run(
        f"SELECT {_DOCUMENT_COLUMNS}, d.text, d.metadata FROM documents d WHERE d.id = :id",
        id=document_id,
    )
    if not rows:
        return None
    return _document(rows[0]) | {"text": rows[0][7], "metadata": rows[0][8]}


def _document(row: list) -> dict:
    """API `Document` from a row of `_DOCUMENT_COLUMNS`. pg8000 returns timestamptz in UTC."""
    return {
        "id": row[0],
        "source": row[1],
        "title": row[2],
        "doc_type": row[3],
        "version": row[4],
        "created_at": row[5].astimezone(UTC).isoformat(),
        "chunks": row[6],
    }


def get_chunks(chunk_ids: list[int]) -> list[dict]:
    """API `Source` dicts plus "ord": {"chunk_id", "document_id", "title", "source", "text",
    "ord"}, in the order of `chunk_ids`; unknown ids are left out.

    `GET /chunks/{id}` asks for one id; `POST /ask` asks for every cited chunk at once.
    """
    if not chunk_ids:
        return []
    rows = db.run(
        "SELECT c.id, c.document_id, d.title, d.source, c.text, c.ord "
        "FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY(:ids)",
        ids=list(chunk_ids),
    )
    return _sources_in_order(chunk_ids, rows)


def document_chunks(document_id: int, strategy: str) -> list[dict]:
    """The chunks of one document for one chunking `strategy`, in document order (`ord`), as
    `Source` dicts plus "ord"; [] for an unknown document. The agent's `get_document` tool reads
    a document this way so that every passage it shows has a citable chunk id.
    """
    rows = db.run(
        "SELECT c.id, c.document_id, d.title, d.source, c.text, c.ord "
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.document_id = :id AND c.strategy = :strategy ORDER BY c.ord",
        id=document_id,
        strategy=strategy,
    )
    return _sources_in_order([row[0] for row in rows], rows)


def _sources_in_order(chunk_ids: list[int], rows: list[list]) -> list[dict]:
    """Rows as `Source` dicts in the order of `chunk_ids`; unknown ids left out, repeats once."""
    by_id = {row[0]: row for row in rows}
    sources = []
    for chunk_id in dict.fromkeys(chunk_ids):
        row = by_id.get(chunk_id)
        if row is not None:
            keys = ("chunk_id", "document_id", "title", "source", "text", "ord")
            sources.append(dict(zip(keys, row, strict=True)))
    return sources
