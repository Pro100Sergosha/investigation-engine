---
title: Architecture
status: current
last_updated: 2026-10-25
owner: Pro100Sergosha
---

# 02 Architecture

## Built so far

Wave 2 (2026-10-25): the `api` Lambda serves the page and the document routes (llm-wiki/04);
`ingest` parses, dedups, chunks, embeds (Cohere Embed V4, 96 texts per request) and stores every
object put under `uploads/` or `bulk/`, and keeps the events it gave up on in an SQS queue; `search.py` runs dense + keyword -> RRF -> MMR; `llm.py` is the Bedrock client.
Wave 3 (2026-10-26): `agent.ask` (tool-calling loop, ADR 0025) behind `POST /ask`. Not built:
the Acme corpus, the evaluation runner. Everything marked *(planned)* is decided (see the ADRs)
but not built.

## Contracts

The shared types are in `src/engine/models.py`; the HTTP interface is in
[04 API contract](04-api-contract.md). Pure-logic modules exist as signatures whose docstrings are
the specification, with `NotImplementedError` bodies until their wave owners implement them:

| Function | Module | Notes |
|---|---|---|
| `parse(path, source) -> ParsedDoc` | `parsers.py` | `source` is passed by the caller (`upload:<filename>`): a temp path is not an identity |
| `read_jsonl(path) -> list[ParsedDoc]` | `parsers.py` | bulk shards, one `ParsedDoc` per line |
| `fixed_chunks`, `structured_chunks` | `chunking.py` | strategies "fixed" and "structured"; a token is a whitespace word |
| `rrf`, `mmr` | `rank.py` | MMR relevance is the normalized fused score, diversity is cosine of chunk vectors |
| `build_answer(raw, retrieved) -> Answer` | `grounding.py` | the citation validator and the status rules; passes the model's short `answer` through, "" when insufficient |
| recall@k, reciprocal rank, EM, F1, citation precision, abstention P/R, contradiction P/R | `eval/metrics.py` | gold labels are document sources, not database ids |
| `normalize`, `content_hash` | `index.py` | implemented: the dataset job and `ingest` must dedup identically |
| `embed_documents(texts) -> list[list[float]]`, `embed_query(text) -> list[float]` | `embed.py` | implemented: Cohere Embed V4 (`eu.*` profile), 1024 floats of unit length, 96 texts per request (`search_document`), queries as `search_query`, adaptive retry on throttling |
| `upsert_many(docs) -> [(status, id)]`, `upsert(doc)`, `delete(id)` | `index.py` | implemented: dedup checks of the whole batch before any embedding (also within the batch), the distinct inputs of all docs to write embedded in one go, one transaction per doc; `upsert(doc)` is `upsert_many([doc])[0]`; chunks embedded as `<title>\n\n<chunk>` |
| `search(query, k, strategy, mode)`, `get_document`, `list_documents`, `document_detail`, `get_chunks`, `document_chunks` | `search.py` | implemented, `k` 1-40: `mode` is `dense`, `hybrid` (RRF) or `mmr` (RRF + MMR), the evaluated configurations; `document_chunks(id, strategy)` serves the agent's `get_document` tool |
| `converse(system, messages, tools, model, max_tokens, use_cache, tool_choice, deadline, cache_history) -> dict` | `llm.py` | implemented: retry, Haiku -> gpt-oss fallback, Postgres cache (ADR 0023); `deadline` stops retries and the fallback when a whole attempt (35 s) no longer fits (ADR 0025) |
| `ask(question, strategy, mode, max_steps) -> Answer` | `agent.py` | implemented (ADR 0025): server-seeded first search, tools `search` / `get_document` / `final_answer`, last step forced to `final_answer`, 80 s deadline; `max_steps=1` is single-shot RAG; `trace` entries with `"step": "llm"` carry `model`, `cached`, `usage` (the eval runner paces and costs from them); never raises for model errors or timeouts, abstains instead. `Answer.answer` is the short direct answer EM/F1 compare |

`ParsedDoc.text` has one shape for every format: paragraphs separated by a blank line, headings
on their own line starting with `#`. The structure-aware chunker depends on it.

## Principles

1. **Explainable without AI.** Own small code, no RAG or web frameworks
   ([ADR 0001](adr/0001-own-code-no-rag-frameworks.md)).
2. **The core is pure Python with no AWS imports.** Chunkers, dedup, RRF, MMR, the agent loop, the
   citation validator and metrics are functions over plain data, unit-tested without a database,
   network or mocks. `handlers.py` is the thin layer that knows about Lambda events.
3. **Serverless, no NAT, no VPC, no passwords**: Lambdas and CodeBuild outside any VPC; Aurora
   (express configuration) reached through its internet access gateway with IAM auth tokens
   ([ADR 0021](adr/0021-aurora-express-iam-auth.md)).
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
browser ──HTTPS──> Lambda Function URL ──> api Lambda (container image, at most 4 at once)
   │                                         GET  /                 -> index.html
   │                                         GET  /documents        POST /documents/upload-url
   │                                         DELETE /documents/{id} GET  /chunks/{id}
   │                                         POST /ask  (agent loop, 80 s deadline, timeout 90 s)
   │                                             ├──IAM──> Bedrock: Claude Haiku, gpt-oss-120b, Cohere Embed V4 (eu.*)
   │                                             └──IAM token, TLS 5432──> Aurora (express)
   └──PUT (presigned)──> S3 uploads/ ──event──> ingest Lambda (same image, at most 2 at once)
                                                  parse -> dedup -> chunk -> Cohere V4 (96 per request) -> Aurora
                                                  gave up after 2 retries -> SQS IngestFailures

CodeBuild investigation-jobs: dataset (HotpotQA shards -> S3 -> ingest) | redrive-ingest
                              (IngestFailures -> ingest) | acme, eval (planned)
```

## Data flow

Ingestion: parse (pdf: pypdf, docx: python-docx, html/md/jsonl: stdlib) -> normalize -> sha256 ->
exact dedup -> chunk (fixed 300/50 tokens or structure-aware) -> embed (Cohere Embed V4, 1024d,
the chunks of a whole file in batches of 96) -> insert `documents` + `chunks`, one transaction per
document (`db.py`). Bulk corpus: JSONL shards in S3, same path.

Question (`POST /ask` -> `agent.ask`, ADR 0025): the server searches the question itself
(k = 8) and puts the hits into the first message -> Claude Haiku calls tools: `search(q, k)` =
Cohere query vector (`search_query`) -> dense top-40 (partial HNSW of the strategy) + keyword
top-40 (OR `tsquery`, `ts_rank_cd`) -> RRF -> MMR over the top-40 fused, with per-document cap
(modes `dense | hybrid | mmr`, ADR 0024); `get_document(id)` = the document's chunks, up to
8,000 characters, citable -> up to 6 LLM calls, the last one (or the one with < 45 s left of
the 80 s deadline) forced to `final_answer` -> citation validator (only chunk ids shown in this
run count) -> `Answer(status=answered | insufficient | conflicting)` with the short answer,
claims, citations, contradictions and the trace -> the handler adds the cited chunks as
`sources`.

## Service by service

| Concern | Choice | Why |
|---|---|---|
| Compute | Lambda, Python 3.12, one container image (no ML runtime), x86_64 | [ADR 0016](adr/0016-titan-embeddings-no-model-in-lambda.md) |
| HTTP entry | Lambda Function URL, UI served by the same function | [ADR 0008](adr/0008-function-url-not-api-gateway.md) |
| Database | Aurora Serverless v2 express configuration (PG 17.9 + pgvector), IAM-token connections (pg8000) | [ADR 0002](adr/0002-postgres-pgvector-single-store.md), [ADR 0015](adr/0015-aurora-serverless-data-api.md), [ADR 0021](adr/0021-aurora-express-iam-auth.md) |
| Search | dense + `tsvector`, own RRF + MMR | [ADR 0003](adr/0003-hybrid-search-own-rrf-mmr.md) |
| Embeddings | Bedrock Cohere Embed V4 through the `eu.*` profile, 1024d, 96 texts per request | [ADR 0022](adr/0022-cohere-embed-v4-batched.md) |
| LLM | Bedrock: Claude Haiku 4.5 (agent), gpt-oss-120b (fallback), Qwen3-235B (judge); `llm.converse`: own retry loop, Haiku-only fallback, `cachePoint` for Claude only, Postgres cache | [ADR 0017](adr/0017-bedrock-claude-haiku-llm.md), [ADR 0023](adr/0023-llm-client-own-retry-fallback-cache.md) |
| Ingestion | presigned S3 PUT or bulk shard, S3 event -> `ingest` (2 at once); events it gave up on -> SQS `IngestFailures`, rerun by `make redrive-ingest` | [ADR 0008](adr/0008-function-url-not-api-gateway.md), [ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md), [ADR 0022](adr/0022-cohere-embed-v4-batched.md) |
| Jobs | CodeBuild `investigation-jobs`: dataset, acme, eval | [ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md) |
| Config and secrets | no database password (IAM auth tokens), GitHub token in SSM; no LLM keys (IAM) | not in code, image or env vars |
| Observability | one JSON log line per request in CloudWatch Logs, no custom metrics | free tier; binadar paid $6/month for 22 extra metrics |
| IaC and deploy | CDK (Python); GitHub Actions checks PRs, CodeBuild diffs PRs and deploys `main` | [ADR 0010](adr/0010-cdk-single-production-environment.md), [ADR 0012](adr/0012-codebuild-cicd-via-codeconnections.md) |
| Data | HotpotQA + synthetic Acme | [ADR 0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md) |
