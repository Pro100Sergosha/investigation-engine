---
title: Hybrid search with hand-written RRF and MMR
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: 0016 (embedding model only: fastembed replaced by Titan V2 1024d)
---

# ADR 0003: Hybrid search with hand-written RRF and MMR

## Context

The task requires hybrid search (semantic + keyword) and at least one own ranking algorithm, not
only library calls. Dense retrieval misses exact names, ids and numbers; keyword retrieval misses
paraphrases. Multi-document questions also need results from several documents, not ten chunks of
one.

## Decision

`search(query, k)` runs dense top-N (pgvector) and keyword top-N (`ts_rank_cd`), fuses them with
Reciprocal Rank Fusion (`score = sum 1 / (k0 + rank)`, `k0 = 60`), then re-ranks with Maximal
Marginal Relevance and a per-document cap. Embeddings: fastembed `BAAI/bge-small-en-v1.5` (384d,
ONNX, CPU). Both algorithms are pure functions with unit tests, no DB needed.

## Consequences

RRF needs no score normalization between incomparable scores, is a few lines, and is easy to
derive on a whiteboard. MMR plus the cap gives multi-hop questions coverage across documents.
The cost: fixed `k0` and MMR lambda are tuned by eye, then by the eval sweep; two queries per
search instead of one.

## Alternatives considered

**Weighted score sum**: needs normalization of cosine vs `ts_rank_cd`, fragile across queries.

**Cross-encoder reranker**: better quality, but another model in the Lambda image and more latency.
Listed as a bonus, after the core.

**Own BM25**: optional comparison against `ts_rank_cd` if time allows.
