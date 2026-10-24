---
title: Architecture
status: current
last_updated: 2026-10-24
owner: Pro100Sergosha
---

# 02 Architecture

## Built so far

Only the skeleton: the `api` Lambda answers `GET /health` (once the first CodeBuild deploy runs), the shared contracts in
`src/engine/models.py` exist. Everything below marked *(planned)* is decided (see the ADRs) but not
built. Update this section as streams land.

## Principles

1. **Explainable without AI.** Own small code, no RAG or web frameworks
   ([ADR 0001](adr/0001-own-code-no-rag-frameworks.md)).
2. **The core is pure Python with no AWS imports.** Chunkers, dedup, RRF, MMR, the agent loop, the
   citation validator and metrics are functions over plain data, unit-tested without a database,
   network or mocks. `handlers.py` is the thin layer that knows about Lambda events.
3. **Serverless, no VPC, no NAT** ([ADR 0007](adr/0007-serverless-lambda-no-vpc-public-rds.md)).
4. **One store**: Postgres + pgvector for documents, chunks, vectors, keyword index and LLM cache
   ([ADR 0002](adr/0002-postgres-pgvector-single-store.md)).
5. **Grounding is enforced by the server, not requested in a prompt**
   ([ADR 0005](adr/0005-agent-loop-with-citation-validation.md)).
6. **Everything is infrastructure as code**, one production environment
   ([ADR 0010](adr/0010-cdk-single-production-environment.md)).

## Component map

```
browser ──HTTPS──> Lambda Function URL ──> api Lambda (container image)        [built: /health]
   │                                         GET  /                 -> index.html        (planned)
   │                                         GET  /documents        POST /documents/upload-url
   │                                         DELETE /documents/{id} GET  /chunks/{id}
   │                                         POST /ask  (agent loop, timeout 90 s)
   │                                             │  └──HTTPS──> Groq (fallback: Bedrock)
   │                                             └──TLS──> RDS Postgres + pgvector   (planned)
   └──PUT (presigned)──> S3 uploads/ ──event──> ingest Lambda (same image)          (planned)
                                                  parse -> dedup -> chunk -> embed -> RDS

laptop: bulk loader (HotpotQA, fastembed) ──TLS──> RDS      eval runner ──> engine.ask() in-process
```

## Data flow

Ingestion: parse (pdf: pypdf, docx: python-docx, html/md/jsonl: stdlib) -> normalize -> sha256 ->
exact dedup -> chunk (fixed 300/50 tokens or structure-aware) -> embed (bge-small, 384d) -> insert
`documents` + `chunks` in one transaction.

Question: agent loop -> `search(q)` = dense top-N + keyword top-N -> RRF -> MMR with per-document
cap -> optional `get_document(id)` -> repeat up to 6 steps -> `final_answer` JSON -> citation
validator -> `Answer(status=answered | insufficient | conflicting)` with claims, citations,
contradictions and the trace.

## Service by service

| Concern | Choice | Why |
|---|---|---|
| Compute | Lambda, Python 3.12, one container image, x86_64 | [ADR 0009](adr/0009-one-container-image-for-all-lambdas.md) |
| HTTP entry | Lambda Function URL, UI served by the same function | [ADR 0008](adr/0008-function-url-not-api-gateway.md) |
| Database | RDS Postgres 17 + pgvector, public with forced TLS | [ADR 0002](adr/0002-postgres-pgvector-single-store.md), [ADR 0007](adr/0007-serverless-lambda-no-vpc-public-rds.md) |
| Search | dense + `tsvector`, own RRF + MMR | [ADR 0003](adr/0003-hybrid-search-own-rrf-mmr.md) |
| Embeddings | fastembed `BAAI/bge-small-en-v1.5` | [ADR 0003](adr/0003-hybrid-search-own-rrf-mmr.md) |
| LLM | Groq, Bedrock fallback, Postgres cache | [ADR 0004](adr/0004-groq-llm-with-postgres-cache.md) |
| Uploads | presigned S3 PUT, S3 event -> `ingest` | [ADR 0008](adr/0008-function-url-not-api-gateway.md) |
| Config and secrets | `.env` locally, SSM Parameter Store SecureString in prod | free, not in image or env vars |
| Observability | one JSON log line per request in CloudWatch Logs, no custom metrics | free tier; binadar paid $6/month for 22 extra metrics |
| IaC and deploy | CDK (Python); GitHub Actions checks PRs, CodeBuild diffs PRs and deploys `main` | [ADR 0010](adr/0010-cdk-single-production-environment.md), [ADR 0012](adr/0012-codebuild-cicd-via-codeconnections.md) |
| Data | HotpotQA + synthetic Acme | [ADR 0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md) |
