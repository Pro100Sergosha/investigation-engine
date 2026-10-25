---
title: Known gaps
status: current
last_updated: 2026-10-25
owner: Pro100Sergosha
---

# 14 Known gaps

What does not work yet, or works on a temporary arrangement. Remove an entry in the same commit
that closes it.

| Gap | Why | Closes when |
|---|---|---|
| A PDF page becomes one paragraph: paragraph boundaries inside a page are lost, so fixed and structured chunking behave alike on PDFs | pypdf rarely emits blank lines between paragraphs (`parsers._read_pdf`) | split on vertical gaps between lines (pypdf `visitor_text`) if PDF retrieval measurably suffers |
| DOCX tables, headers, footers and text boxes are not indexed | `parsers._read_docx` reads body paragraphs only | an Acme document keeps facts in a table |
| Branch protection is off: a red PR can be merged by hand | GitHub free plan offers it only on public repositories | the repository is made public (required for submission anyway) |
| Claude Haiku 4.5 limited to 10 requests/min per profile (`eu.*` and `global.*`); an eval sweep takes ~2 h | Bedrock quota of a new account ([ADR 0017](adr/0017-bedrock-claude-haiku-llm.md) update) | the account-level increase to 10,000 is approved |
| No reserved concurrency on `api` | not configured yet | added with the real `/ask` route (quota is 400, so it is possible here) |
| `ingest` is a stub: it logs the S3 keys and indexes nothing | wave 1 built the infrastructure only | wave 2 wires parse -> dedup -> chunk -> embed -> `db.py` into `handlers.ingest` |
| Schema changes are additive only (`IF NOT EXISTS`); a new index over a loaded table holds the deploy for minutes | schema applied by a custom resource on deploy ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | accepted; a destructive change gets a one-off job |
| `concurrent_build_limit=1` on `investigation-deploy` is in the code but not deployed: merges in quick succession still race (2026-10-24: ECR "tag is immutable", a stack deployed before the stack it imports from) | `Investigation-Cicd-prod` is deployed only by hand | the owner runs `make diff-cicd` + `make deploy-cicd`; until then merge one PR at a time |
| The database endpoint is public (internet access gateway) | the Free plan creates Aurora only with express configuration ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | accepted: IAM-only auth, TLS, no password exists |
| Old paid account `788607671121` still exists, no budget on it | abandoned in favour of the Free-plan project ([ADR 0011](adr/0011-free-plan-aws-project.md)) | closed in the console, or a budget alert added |
| No SSE streaming of answers | not supported on Python Lambda Function URLs ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | accepted, listed as future work |
| The UI page is served at `GET /`, but the routes it calls (`/documents`, `/ask`, `/chunks`) return 404: only `/?stub` works | wave 1 built the page against the API contract with a stub mode | the wave-2 API routes task adds the routes |
| Dense recall unmeasured: one HNSW scan returns at most `hnsw.ef_search` (40) rows and we ask for 40; on random vectors recall@40 vs exact search was 0.625 | pgvector default `ef_search`; `search.py` asks for `CANDIDATES = 40` | the eval measures Recall@K; if low, `SET LOCAL hnsw.ef_search` inside `db.transaction()` before the dense query |
| Search latency from the Lambda and the cost of OR keyword queries over the full corpus are not measured (laptop: dense 0.7 s, hybrid 1.0 s, mmr 1.1 s, mostly network) | measured before the bulk load, from Tbilisi | measured after the bulk load |
| Prompt caching saves nothing yet: Haiku 4.5 caches only prefixes of >= 4,096 tokens, the agent prompt is ~1.3k | `llm.py` puts one `cachePoint` after the system prompt (harmless below the minimum) | the agent adds a `cachePoint` after the history once it passes 4,096 tokens (wave 3) |
| Under sustained Haiku throttling (10 requests/min) answers silently come from gpt-oss-120b; a worst-case call (30 s read timeout x 4 attempts + fallback) exceeds the api Lambda's 90 s | `llm.py` retries ~10 s per model then falls back ([ADR 0023](adr/0023-llm-client-own-retry-fallback-cache.md)) | the agent loop gets its own deadline, the eval runner paces calls and records `model` (wave 3) |
