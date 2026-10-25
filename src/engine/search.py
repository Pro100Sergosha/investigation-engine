"""Reads: hybrid search (dense + keyword -> RRF -> MMR) and lookups of documents and chunks."""

from engine.models import Hit, ParsedDoc


def search(query: str, k: int = 10, strategy: str = "structured", mode: str = "mmr") -> list[Hit]:
    """Top `k` chunks of one chunking `strategy` ("fixed" | "structured") for `query`.

    `mode` selects the evaluated configuration: "dense" (vector search only, score = cosine
    similarity), "hybrid" (dense top-N and keyword top-N fused by `rank.rrf`, score = RRF
    score), "mmr" (hybrid, then `rank.mmr` with its per-document cap). Blank query -> [].
    Raises ValueError on an unknown strategy or mode.
    """
    raise NotImplementedError


def get_document(document_id: int) -> ParsedDoc | None:
    """The stored document (full text, metadata) for the agent's tool, or None if unknown."""
    raise NotImplementedError


def list_documents(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """A page of documents newest first, and the total count.

    Each dict is the API `Document`: {"id", "source", "title", "doc_type", "version",
    "created_at" (ISO 8601 UTC string), "chunks" (count over all strategies)} (llm-wiki/04).
    """
    raise NotImplementedError


def document_detail(document_id: int) -> dict | None:
    """The API `Document` plus "text" and "metadata", or None if unknown."""
    raise NotImplementedError


def get_chunks(chunk_ids: list[int]) -> list[dict]:
    """API `Source` dicts plus "ord": {"chunk_id", "document_id", "title", "source", "text",
    "ord"}, in the order of `chunk_ids`; unknown ids are left out.

    `GET /chunks/{id}` asks for one id; `POST /ask` asks for every cited chunk at once.
    """
    raise NotImplementedError
