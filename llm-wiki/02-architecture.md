---
title: Architecture
status: current
last_updated: 2026-10-24
owner: Pro100Sergosha
---

# 02 Architecture

## Built so far

Only the skeleton: the `api` Lambda answers `GET /health`, and the contracts the parallel waves code
against exist (see below). Everything marked *(planned)* is decided (see the ADRs) but not built.
Update this section as streams land.

## Contracts

The shared types are in `src/engine/models.py`; the HTTP interface is in
[04 API contract](04-api-contract.md). Pure-logic modules exist as signatures whose docstrings are
the specification, with `NotImplementedError` bodies until their wave-1 owners implement them:

| Function | Module | Notes |
|---|---|---|
| `parse(path, source) -> ParsedDoc` | `parsers.py` | `source` is passed by the caller (`upload:<filename>`): a temp path is not an identity |
| `read_jsonl(path) -> list[ParsedDoc]` | `parsers.py` | bulk shards, one `ParsedDoc` per line |
| `fixed_chunks`, `structured_chunks` | `chunking.py` | strategies "fixed" and "structured"; a token is a whitespace word |
| `rrf`, `mmr` | `rank.py` | MMR relevance is the normalized fused score, diversity is cosine of chunk vectors |
| `build_answer(raw, retrieved) -> Answer` | `grounding.py` | the citation validator and the status rules |
| recall@k, reciprocal rank, EM, F1, citation precision, abstention P/R | `eval/metrics.py` | gold labels are document sources, not database ids |
| `normalize`, `content_hash` | `index.py` | implemented: the dataset job and `ingest` must dedup identically |

`ParsedDoc.text` has one shape for every format: paragraphs separated by a blank line, headings
on their own line starting with `#`. The structure-aware chunker depends on it.

## Principles

1. **Explainable without AI.** Own small code, no RAG or web frameworks
   ([ADR 0001](adr/0001-own-code-no-rag-frameworks.md)).
2. **The core is pure Python with no AWS imports.** Chunkers, dedup, RRF, MMR, the agent loop, the
   citation validator and metrics are functions over plain data, unit-tested without a database,
   network or mocks. `handlers.py` is the thin layer that knows about Lambda events.
3. **Serverless, no NAT, no public database endpoint**: Lambdas and CodeBuild outside any VPC,
   Aurora reached through the Data API ([ADR 0015](adr/0015-aurora-serverless-data-api.md)).
4. **Nothing runs on the author's computer**: ingestion, corpus generation and evaluation run in
   Lambda and CodeBuild ([ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md)).
5. **One store**: Postgres + pgvector for documents, chunks, vectors, keyword index and LLM cache
   ([ADR 0002](adr/0002-postgres-pgvector-single-store.md)).
6. **Grounding is enforced by the server, not requested in a prompt**
   ([ADR 0005](adr/0005-agent-loop-with-citation-validation.md)).
7. **Everything is infrastructure as code**, one production environment
   ([ADR 0010](adr/0010-cdk-single-production-environment.md)).

## Component map

```
browser ──HTTPS──> Lambda Function URL ──> api Lambda (container image)        [built: /health]
   │                                         GET  /                 -> index.html        (planned)
   │                                         GET  /documents        POST /documents/upload-url
   │                                         DELETE /documents/{id} GET  /chunks/{id}
   │                                         POST /ask  (agent loop, timeout 90 s)
   │                                             ├──IAM──> Bedrock: Claude Haiku, gpt-oss-120b, Titan V2 (planned)
   │                                             └──IAM──> RDS Data API ──> Aurora Serverless v2   (planned)
   └──PUT (presigned)──> S3 uploads/ ──event──> ingest Lambda (same image)              (planned)
                                                  parse -> dedup -> chunk -> Titan V2 -> Data API

CodeBuild investigation-jobs: dataset (HotpotQA shards -> S3 -> ingest) | acme | eval     (planned)
```

## Data flow

Ingestion: parse (pdf: pypdf, docx: python-docx, html/md/jsonl: stdlib) -> normalize -> sha256 ->
exact dedup -> chunk (fixed 300/50 tokens or structure-aware) -> embed (Titan V2, 1024d) -> insert
`documents` + `chunks` in one transaction (Data API). Bulk corpus: JSONL shards in S3, same path.

Question: agent loop -> `search(q)` = dense top-N + keyword top-N -> RRF -> MMR with per-document
cap -> optional `get_document(id)` -> repeat up to 6 steps -> `final_answer` JSON -> citation
validator -> `Answer(status=answered | insufficient | conflicting)` with claims, citations,
contradictions and the trace.

## Service by service

| Concern | Choice | Why |
|---|---|---|
| Compute | Lambda, Python 3.12, one container image (no ML runtime), x86_64 | [ADR 0016](adr/0016-titan-embeddings-no-model-in-lambda.md) |
| HTTP entry | Lambda Function URL, UI served by the same function | [ADR 0008](adr/0008-function-url-not-api-gateway.md) |
| Database | Aurora Serverless v2 (PG 17 + pgvector), min 0 ACU, Data API only | [ADR 0002](adr/0002-postgres-pgvector-single-store.md), [ADR 0015](adr/0015-aurora-serverless-data-api.md) |
| Search | dense + `tsvector`, own RRF + MMR | [ADR 0003](adr/0003-hybrid-search-own-rrf-mmr.md) |
| Embeddings | Bedrock Titan Text Embeddings V2, 1024d | [ADR 0016](adr/0016-titan-embeddings-no-model-in-lambda.md) |
| LLM | Bedrock: Claude Haiku (agent), gpt-oss-120b (fallback), Qwen3-235B (judge); Postgres cache | [ADR 0017](adr/0017-bedrock-claude-haiku-llm.md) |
| Ingestion | presigned S3 PUT or bulk shard, S3 event -> `ingest` | [ADR 0008](adr/0008-function-url-not-api-gateway.md), [ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md) |
| Jobs | CodeBuild `investigation-jobs`: dataset, acme, eval | [ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md) |
| Config and secrets | DB credentials in Secrets Manager (Data API), GitHub token in SSM; no LLM keys (IAM) | not in code, image or env vars |
| Observability | one JSON log line per request in CloudWatch Logs, no custom metrics | free tier; binadar paid $6/month for 22 extra metrics |
| IaC and deploy | CDK (Python); GitHub Actions checks PRs, CodeBuild diffs PRs and deploys `main` | [ADR 0010](adr/0010-cdk-single-production-environment.md), [ADR 0012](adr/0012-codebuild-cicd-via-codeconnections.md) |
| Data | HotpotQA + synthetic Acme | [ADR 0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md) |
