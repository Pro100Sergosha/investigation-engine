"""Own ranking: Reciprocal Rank Fusion of dense + keyword, then MMR with a per-document cap."""

import math

from engine.models import Hit


def rrf(rankings: list[list[int]], k0: int = 60) -> list[tuple[int, float]]:
    """Fuse ranked lists of chunk ids (best first) into one: score(id) = sum 1 / (k0 + rank).

    `rank` starts at 1 in each list; an id missing from a list gets nothing from it; an id
    repeated inside one list counts only at its best rank. Returns (chunk_id, score) sorted by
    score descending, ties broken by smaller chunk id so the order is deterministic.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        seen: set[int] = set()
        for position, chunk_id in enumerate(ranking):
            if chunk_id in seen:
                continue  # a repeat is worse than its first position, so it adds nothing
            seen.add(chunk_id)
            rank = position + 1
            # Big k0 flattens the curve: rank 1 vs rank 2 differ little, so one list's
            # top spot cannot beat an id that is merely good in both lists.
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k0 + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0 if either vector is all zeros (its direction is undefined)."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


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
    if not 0 <= lam <= 1:
        raise ValueError(f"lam must be in [0, 1], got {lam}")
    if per_doc_cap < 1:
        raise ValueError(f"per_doc_cap must be >= 1, got {per_doc_cap}")
    if not candidates or k < 1:
        return []
    for hit in candidates:
        if hit.chunk_id not in vectors:
            raise KeyError(hit.chunk_id)

    # Normalize so lam trades off two numbers on the same 0..1 scale as cosine similarity;
    # raw RRF scores are ~0.03 and would be drowned by similarity.
    best_score = max(hit.score for hit in candidates)

    picked: list[Hit] = []
    remaining = list(candidates)  # keeps candidate order, so scanning it breaks ties
    picked_per_doc: dict[int, int] = {}
    # Pure Python is fast enough: ~40 candidates, k picks, a few thousand cosines of 1024 floats.
    while len(picked) < k:
        best_index = -1
        best_value = 0.0
        for index, hit in enumerate(remaining):
            if picked_per_doc.get(hit.document_id, 0) >= per_doc_cap:
                continue

            relevance = hit.score / best_score if best_score > 0 else 0.0
            # Similarity to the closest already-picked hit; 0 while nothing is picked.
            max_similarity = 0.0
            for j, other in enumerate(picked):
                similarity = _cosine(vectors[hit.chunk_id], vectors[other.chunk_id])
                if j == 0 or similarity > max_similarity:
                    max_similarity = similarity
            value = lam * relevance - (1 - lam) * max_similarity

            # Strict > while scanning in order: a tie keeps the earlier candidate.
            if best_index == -1 or value > best_value:
                best_index = index
                best_value = value

        if best_index == -1:
            break  # every remaining candidate sits in a document that hit the cap
        best_hit = remaining.pop(best_index)
        picked.append(best_hit)
        picked_per_doc[best_hit.document_id] = picked_per_doc.get(best_hit.document_id, 0) + 1
    return picked
