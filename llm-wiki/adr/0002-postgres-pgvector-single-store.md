---
title: Postgres with pgvector as the single store
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: 0015 (hosting only: RDS and local Docker replaced by Aurora Serverless v2 + Data API)
---

# ADR 0002: Postgres with pgvector as the single store

## Context

The system needs documents with metadata, chunks, dense vectors, a keyword index, CRUD with
versioning, dedup hashes and an LLM response cache, over 50k+ records. Hybrid search needs dense and
keyword results for the same chunks.

## Decision

One Postgres 17 database with pgvector. `chunks.embedding` is `halfvec(384)` with an HNSW index,
keyword search is the built-in `tsvector` with `ts_rank_cd` and a GIN index. Plain SQL through
psycopg 3, always parameterized. Update replaces a document's chunks in one transaction; delete
cascades. Local development runs `pgvector/pgvector:pg17` in Docker with the same schema; production
is RDS (ADR 0007).

## Consequences

One system to run, back up and explain; both retrievers and all metadata are joinable in one query;
transactions make update/delete trivially consistent. `halfvec` halves vector storage.
The cost: Postgres is not the fastest vector engine, HNSW build on a 1 GB RDS instance needs care
(raised `maintenance_work_mem`, build after bulk load), and a managed Postgres is the one AWS
resource that costs money while idle.

## Alternatives considered

**Qdrant/Pinecone + separate metadata store**: better vector features, but two stores to keep in
sync and no native keyword search alongside metadata.

**OpenSearch**: hybrid search built in, but heavy, expensive on AWS, and hides the fusion algorithm
we want to write ourselves (ADR 0003).

**Neon (serverless Postgres, free)**: same schema at $0, was the original choice. Kept as the
fallback; lost only to the "everything on AWS" goal.
