"""Own ranking: Reciprocal Rank Fusion of dense + keyword, then MMR with a per-document cap."""

from engine.models import Hit


def rrf(rankings: list[list[int]], k0: int = 60) -> list[tuple[int, float]]:
    """Fuse ranked lists of chunk ids (best first) into one: score(id) = sum 1 / (k0 + rank).

    `rank` starts at 1 in each list; an id missing from a list gets nothing from it; an id
    repeated inside one list counts only at its best rank. Returns (chunk_id, score) sorted by
    score descending, ties broken by smaller chunk id so the order is deterministic.
    """
    raise NotImplementedError


def mmr(
    candidates: list[Hit],
    vectors: dict[int, list[float]],
    k: int = 10,
    lam: float = 0.7,
    per_doc_cap: int = 3,
) -> list[Hit]:
    """Pick up to `k` hits balancing relevance against similarity to hits already picked.

    Relevance is the hit's fused score divided by the best fused score among candidates (so it
    lies in [0, 1]; all 0 if the best is 0); similarity is cosine between chunk vectors
    (`vectors[chunk_id]`, one per candidate; 0 if either vector is all zeros). No candidates or
    k < 1 -> []. Each step picks the candidate maximizing
    `lam * relevance - (1 - lam) * max similarity to the picked ones` (0 when nothing is picked),
    skipping candidates whose document already has `per_doc_cap` picked hits. Ties go to the
    earlier candidate. Hits are returned unchanged, in pick order. Raises KeyError if a
    candidate has no vector, ValueError unless 0 <= lam <= 1 and per_doc_cap >= 1.
    """
    raise NotImplementedError
