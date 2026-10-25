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

## Update 2026-10-25

`engine.search` implements the decision: dense top-40 and keyword top-40 per strategy (40 =
pgvector's default `hnsw.ef_search`), RRF over both, then MMR (`lam = 0.7`, cap 3 per document)
over the top 40 fused candidates. The three modes the evaluation compares are `dense`, `hybrid`
and `mmr`. How the strategy filter and the keyword query are built: ADR 0024.

Measured on 2026-10-25 against the real cluster (pgvector 0.8.1, PostgreSQL 17.9) with 10 test
documents, from a laptop in Tbilisi, warm, median of 5, k = 10: embedding the question with
Titan V2 187 ms; `dense` 715 ms, `hybrid` 960 ms, `mmr` 1,117 ms in total. Almost all of the
database part is network: one parameterized `db.run` costs ~260 ms from the laptop against a
95 ms round trip (pg8000 prepares, then executes: ~2.7 round trips per statement), and the
server-side work at this size is negligible. From a Lambda in `eu-north-1` the round trip should
be about 1 ms, so a search should cost roughly the embedding call plus MMR. MMR in pure Python
over 40 candidates of 1,024 floats took 189 ms on the laptop; fetching the candidate vectors
(~10 KB of text per row) added ~100 ms over the laptop link. To be re-measured from the Lambda
and over the full corpus.
