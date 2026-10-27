# AI Investigation Engine — MVP plan

Source: Upgaming Talent Growth Program, "Applied AI – AI Investigation Engine Task" ([docs/task.pdf](docs/task.pdf), Georgian).
Goal: multi-source investigation over 50k+ documents with cited, evidence-based answers that
abstain on missing data and flag contradictions. Not "chat with PDF".

Deliverables: GitHub repo (with real history), live demo URL, README, Evaluation Report,
AI Usage Report. Interview: explain architecture, walk the RAG pipeline, fix bugs and add
features live **without AI**. Every line here must be explainable — so no LangChain/LlamaIndex,
own small code instead.

## 0. Status

**Updated 2026-10-26 (day 3 of 6).** Waves 0-4 merged (PRs #4-#37). Corpus: 66,619 documents
(66,555 HotpotQA + 64 Acme, `make acme-load` done; + 6 injected Acme documents, #42). Haiku falls back `eu.*` -> `global.*` (#29,
ADR 0028; `eu.*` answers `ServiceUnavailableException` since the morning of 10-26); search tuned
(#30, ADR 0029). Full eval done (#31): `retrieval`, `agent`, `agent-structured`, `single-shot`,
results in `eval/results/` and llm-wiki/09 Results; the loop beats single-shot on multi-hop
(0.87 vs 0.52). Contradiction output fixed (#32, ADR 0025 update): `agent` judge 0.82, citation
precision 0.94, abstention P/R 0.77/0.91, contradiction P/R 1.00/0.67 (was 0.75/0.25).
Wave 4 merged (#34-#37): README, EVALUATION.md (failure analysis, judge spot-check: 6 of 10
verdicts agree with the author, the judge is the stricter one), AI_USAGE.md; eval cost now prices
prompt-cache tokens (#37: `agent` ~$0.016 per question, ~3x single-shot). The UI was checked on
the public URL on 10-26: upload, duplicate, update, delete, metadata, a question with its source.
The short-answer fix was dropped: the traces show it could win at most 2 of 25 EM points.
Monitoring and load test (#40, ADR 0033): CloudWatch dashboard from built-in metrics and Logs
Insights; 200 GETs at 1/5/10 clients answer in ~26 ms p50, above 4 clients ~50% get 429 (the
reserved concurrency); search latency from the Lambda measured (0.74 s).
Model comparison bonus (#43, ADR 0032): embedding prefixes 1024/512/256 measured, 1024 kept;
gpt-oss-120b vs Haiku: judge 0.89 vs 0.82, contradiction recall 0.92 vs 0.67, ~7x cheaper, but
abstention recall 0.82 vs 0.91, Haiku kept; no Bedrock reranker in eu-north-1.
**Behind:** nothing; the mandatory part is done except the author's sections of AI_USAGE.md.
Open Function URL protected (#39, ADR 0030; live after merge): seed corpus read-only, admin
token in SSM, daily caps on `/ask` and uploads. Next: optional fixes from
EVALUATION.md (repair malformed `claims` on the server, runner errors vs abstentions); defense
rehearsal. Prompt-injection tests done (#42): 8/8 injections resisted.

How status is kept (every PR that finishes or advances a task updates it in the same PR):
- this section: date, current day and wave, what is behind, what is next;
- the wave table in section 5: the row gets `**Done (#PR):**`; the day table: `**Done:**` or
  `**In progress:**` with what is left;
- the task checklist below: `[x]` only when the requirement works end to end on the deployed
  system; otherwise `[ ]` with the merged pieces (PR numbers) and a **Left:** note, and the
  "Left of the mandatory part" line at its top kept in step.

## 1. Task checklist (mirrors [docs/task.pdf](docs/task.pdf))

One line per bullet of the task, in the task's order and with its section numbers. `[x]` = works
end to end on the deployed system; `[ ]` = not yet, **Left:** says what is missing. Evidence
(PRs, files, numbers) follows the dash.

**Left of the mandatory part (sections 2-5, 7):** the author's own sections of AI_USAGE.md
(TODOs). Everything else in sections 2-5 and 7 is done.

### 2. Main requirements

**Document processing** (accept, process and index documents of different formats; choose the
processing architecture and justify it)
- [x] At least three file formats — PDF, DOCX, HTML, Markdown, JSONL in `parsers.py` (#16), wired into `ingest` (#21); the Acme corpus in four formats loaded (#28), eval answers cite all four (#31)
- [x] Extract text and important metadata — `ParsedDoc` (source, title, date, doc type, service names) from the parsers (#16), stored by `index.upsert` (#22); shown on the document view in the UI (checked 10-26: Acme docs carry `services`; a Markdown upload without a `Services:` line has none)
- [x] Chunking — `chunking.py`: fixed 300/50 and structure-aware (#6), both stored side by side
- [x] Handle duplicate information — sha256 of normalized text (#4), HotpotQA deduplicated in the dataset job (#7), `index.upsert` skips same-hash documents (#22); checked 10-26: the same text under another file name logged `{"duplicate": 1}`, document count unchanged (the UI only times out after 2 min, 14 Known gaps)
- [x] Add new documents, update and delete existing ones — `index.upsert/delete` (#22), API routes + `ingest` (#21); checked 10-26 through the UI: upload -> version 1, same name with new text -> version 2 (answers use the new text), delete -> document and its chunks 404
- [x] Compare at least two chunking strategies — eval (#31): fixed vs structured Recall@10 0.89 vs 0.83, judge 0.74 vs 0.70 (llm-wiki/09)
- [x] Choose and justify the processing architecture — S3 -> `ingest` Lambda -> Aurora, ADR 0018, 0022, 0024 (README summary is in section 7)

**Vector database and search**
- [x] Vector database or a database with vector search — Aurora PostgreSQL 17 + pgvector `halfvec(1024)` (#8, #10, ADR 0002, 0021)
- [x] Embeddings and semantic search (plain SQL text search does not count) — Cohere Embed V4 (#24, ADR 0022), dense search (#23); 66,619 documents indexed
- [x] Hybrid search: semantic + keyword — dense + `tsvector` keyword + RRF in `search.py` (#23); fixed/hybrid Recall@10 0.89, MRR 0.79 (#31)
- [x] At least one own search or ranking component (not only ready-made libraries) — hand-written weighted RRF + MMR with a per-document cap in `rank.py` (#5, #30, ADR 0003, 0029)

**LLM integration and RAG**
- [x] At least one LLM — Claude Haiku 4.5 on Bedrock, gpt-oss-120b fallback, Qwen3 judge (ADR 0017)
- [x] RAG architecture — `agent.ask` over `search.py` (#27), `POST /ask` on the public URL
- [x] Combine information from different documents — multi-doc questions: judge 0.93 (`agent`, #32 prompt)
- [x] Process complex questions in several steps — agent loop with sub-searches (#27, ADR 0025); multi-hop judge 0.87 vs 0.52 for single-shot
- [x] Answers based on the relevant evidence — claims must cite retrieved chunks, the validator drops the rest (#14); 0 claims dropped in 288 answers
- [x] Sources and citation mechanism — claims with cited chunks and `sources` in `POST /ask` (#27); citation precision 0.94
- [x] Attempt to detect contradictory information — `conflicting` status (#14), prompt fix (#32): contradiction precision 1.00, recall 0.67
- [x] Abstain when information is insufficient — `insufficient` status (#14, #27): abstention precision 0.77, recall 0.91
- [x] Handle LLM communication errors and limits — `llm.py` timeout, backoff on throttling, fallback, cache (#20); Haiku `eu.*` -> `global.*` -> gpt-oss (#29, ADR 0028); reprompt on malformed output, 80 s deadline, Bedrock errors -> `insufficient` (#27). Exercised for real: the #31 eval ran through the `eu.*` outage (130 of 192 calls answered by `global.*`, 0 errors)
- [x] At least one tool-calling mechanism — Converse tools `search`, `get_document`, `final_answer` (#27)

**Evaluation**
- [x] Own automated evaluation system — `eval/run.py` + `eval/metrics.py` in CodeBuild against the deployed system (#15, #26, #31, ADR 0027)
- [x] At least 40 test questions — 72: 30 HotpotQA (#26) + 42 Acme (#28)
- [x] Simple and multi-step questions — 11 simple, 23 multi-hop
- [x] Questions that need several documents linked — 15 multi-doc
- [x] Questions with no answer in the data — 11 unanswerable
- [x] Questions based on contradictory information — 12 contradictory
- [x] Quantitative evaluation of retrieval and answer quality — Recall@5/10, MRR, EM, F1, judge correctness, citation precision, abstention and contradiction P/R, cost, latency (llm-wiki/09 Results)
- [x] Compare at least two configurations — 6 retrieval (fixed/structured x dense/hybrid/mmr) and 3 answer configs (`agent`, `agent-structured`, `single-shot`) (#31)
- [x] Analysis, not only results: where the system fails, why, how to improve — EVALUATION.md (#36): failure classes with ids from the traces, improvement priorities, judge spot-check (6 of 10 agree, judge stricter), threats to validity

**Backend and user interface**
- [x] Python backend — Lambda handlers with a hand-written router (`handlers.py`, #21, #27)
- [x] Functional UI where the user adds and manages documents, asks questions and inspects the sources of answers — page at `GET /` (#17), document routes (#21), `POST /ask` (#27); walked through on the public URL 10-26: upload, update, delete, document view, question with cited chunks opened inline

### 3. Dataset
- [x] Use the attached dataset (extra public or synthetic data allowed) — HotpotQA from the list + synthetic Acme corpus (ADR 0006)
- [x] At least 50,000 documents or independent text records — 66,555 unique HotpotQA documents (#7, #24) + 70 Acme (6 of them injected, #42)
- [x] Find linked information across documents — Acme documents reference each other by id (#28); HotpotQA bridge questions
- [x] Keep and identify sources — `source`, title and document id on every chunk; `upload:` gold sources in the Acme questions (#28)
- [x] Handle incomplete and contradictory information — 14 planted contradictions, 6 gaps (#28), measured (#31, #32)
- [x] Repeatable evaluation — fixed question files, results committed, reruns served by `llm_cache` (#31)
- [x] Reproducible subset with justification — HotpotQA `distractor` validation split, dedup rules and counts in llm-wiki/05

### 4. Free hosting and deployment
- [x] Real deployment with a public URL — Lambda Function URL serves `/`, `/health`, documents and `/ask` (#21, #27)
- [x] Hosting and database integrated — `POST /ask` on the public URL searches Aurora (#27)
- [x] Data persists after an application restart — the corpus loaded on 10-25 is served after every redeploy since (#27-#32, each merge redeploys the Lambdas); Aurora has deletion protection (#10, #13)
- [x] API keys and other secrets protected — no LLM keys (IAM), no database password (IAM auth tokens, ADR 0021), GitHub token in SSM SecureString
- [x] Describe the deployment architecture — README DEPLOYMENT (#35), section 3 here, llm-wiki/07
- [x] Account for costs, resources and free-tier limits (sleep, request limits) — README (#35): Aurora resume, Haiku 10 requests/min, Cohere 20 requests/min, $100 credits, cost table, eval cost
- [x] Possible without buying paid infrastructure — AWS Free plan project, $100 credits, never upgraded (ADR 0011)

### 5. Technical quality
- [x] Clear, modular Python code — one module per stream (`parsers`, `chunking`, `index`, `search`, `rank`, `llm`, `agent`, `grounding`, `handlers`)
- [x] Proper separation of responsibilities — DB only in `db.py`, LLM only in `llm.py`, env only in `config.py`, shared contracts in `models.py`
- [x] Error handling — JSON errors from the router, LLM retry/fallback, failed ingest events in SQS + `make redrive-ingest` (#24)
- [x] Automated tests — pytest per module, `make check` in CI on every PR
- [x] Working integration with the database and external APIs — Aurora (IAM tokens), Bedrock (Haiku, Cohere, gpt-oss, Qwen), S3
- [x] Safe management of environment configuration — `config.py` the only env reader, `.env.example`, no secrets in code or env vars
- [x] Technical documentation — README (#35), llm-wiki (system as it is) + 32 ADRs
- [x] Understanding of performance and LLM costs — README (#35), EVALUATION.md (#36): ~$0.016 per question for `agent` vs ~$0.005 for `single-shot` (prompt-cache tokens priced since #37), p50/p95 10.3/45.6 s; bulk load of 66,555 documents ~65 min (llm-wiki/05; ~35-40 min was the estimate); one search from the Lambda 0.74 s, in Region mmr p50/p95 0.33/0.73 s, cold start p50 1.3 s, Aurora resume ~18.5 s (llm-wiki/07 Performance)

### 6. Bonus (does not replace the core)
- [x] Compare several LLMs or embedding models — EVALUATION.md section 8 (#43, ADR 0032): gpt-oss-120b vs Haiku 4.5 as the answering model (`agent-gpt-oss`: judge 0.89 vs 0.82, contradiction recall 0.92 vs 0.67, abstention recall 0.82 vs 0.91, $0.0024 vs $0.016 per question; Haiku kept); Cohere V4 prefixes at 1024/512/256 dimensions (exact Recall@10 0.92/0.89/0.88, truncation checked against Cohere's own output, cosine >= 0.9996; 1024 kept)
- [x] Multi-agent or agentic RAG — own agent loop with tools (#27), beats single-shot on multi-hop (0.87 vs 0.52)
- [ ] More advanced re-ranking — partial: weighted RRF + MMR (#5, #30); no cross-encoder reranker: Bedrock has no rerank model in eu-north-1, only in eu-central-1 and us-west-2 (ADR 0032)
- [x] Prompt-injection tests — #42: 6 injected Acme documents loaded, 8 `injection` questions, `metrics.injection_resisted` + canaries, `dropped_citations` in the grounding trace; `agent` resisted 8/8, judge 7/7, $0.09 (EVALUATION.md section 9; fencing unchanged after the audit)
- [x] Caching and performance optimization — `llm_cache` in Postgres, prompt caching, 96 texts per embedding request, partial HNSW per strategy (#20, #23, #24)
- [ ] Streaming answers — dropped: Python Lambda Function URLs do not stream
- [ ] Detailed monitoring and observability — CloudWatch dashboard `investigation-engine`: 35 built-in metrics (Lambda, Function URL, Aurora ACU, SQS, Bedrock per model) + Logs Insights tables over the per-request log line, 2 alarms without actions; no custom metrics, no X-Ray (#40, ADR 0033). **Left:** deployed by the merge, then open the dashboard and check every widget has data
- [x] Performance testing on large data — `scripts/load_test.py` in CodeBuild against the deployed system over the 66k-document corpus (#40): 200 GETs at 1/5/10 clients, p50 26 ms, no errors, ~50% 429 above 4 clients (reserved concurrency); cold start, Aurora resume and search latency from the Lambda measured (llm-wiki/07 Performance); bulk load timed, eval latency p50/p95

### 7. Deliverables
- [x] GitHub repository with full code and history
- [x] Live demo link — the Function URL
- [x] README: description, architecture, run instructions, justification of technical choices — README.md (#35)
- [x] Evaluation Report: methodology, metrics, results, analysis — EVALUATION.md (#36)
- [ ] AI Usage Report: which AI tools, what they helped with, what was changed by hand — AI_USAGE.md (#34). **Left:** the author confirms the tool list and writes "What I changed / decided myself" (TODOs)

### 8. Interview and code defense (without AI)
- [ ] Rehearse: explain the architecture, walk the RAG pipeline step by step, discuss any module in detail, find and fix a bug, add or change a feature live, justify the algorithms (rewrite RRF/MMR by hand) — day 6

## 2. Key decisions

Each decision has an ADR in [llm-wiki/adr/](llm-wiki/adr/) with context, cost and rejected alternatives.
[docs/SERVICES.md](docs/SERVICES.md) is an early draft, superseded.

| Area | Choice | Why / trade-off |
|---|---|---|
| Corpus (bulk) | HotpotQA `distractor` validation split (7,405 questions x 10 paragraphs), dedup by title+text | Gold supporting facts give free Recall@K/MRR/citation labels. Many paragraphs repeat across questions: dedup is real, not cosmetic. **Verify unique count >= 50k in phase 0**; if short, add part of `train`. |
| Corpus (investigation) | Synthetic "Acme Payments" org: ~60-100 docs (incident reports PDF, change logs MD, runbooks DOCX, status pages HTML) generated once by Claude Haiku in a CodeBuild job, committed | Matches the task's example question (March payment outage). Planted contradictions (two reports disagree on root cause/time) and gaps (unanswerable). HotpotQA has neither. |
| Vector DB | Aurora Serverless v2, PostgreSQL 17 + pgvector (`halfvec(1024)`, HNSW) + built-in full-text search; min 0 ACU (pauses when idle), max 2-4 ACU; **express configuration** (the only Aurora the Free plan creates): no VPC, internet access gateway, IAM auth tokens over TLS with `pg8000`, no password or secret | One store for docs, chunks, vectors, keyword index, CRUD, dedup hashes, LLM cache. Idle cost is ~storage only, so the credits last until the interview; no NAT, no secrets, no Data API limits. Trade-off: ~15 s resume after a pause, a public (IAM-only) endpoint, own connection handling. No local database. ADR 0015, ADR 0021. |
| Embeddings | Amazon Bedrock Cohere Embed V4 through the `eu.cohere.embed-v4:0` inference profile (EU Regions only), 1024 dimensions, `search_document` / `search_query` | 96 texts per request: the corpus loaded in ~65 min (estimated 35-40) within the pool's 20 requests/min (Titan V2, one text per request, throttled at ~1 request/s: ~18 h). ~$1.3 for the corpus, no model in the Lambda image, nothing on the laptop. Query embeddings share the pool with the bulk load. Fallback: the `global.*` profile (second pool, data may leave the EU). ADR 0016, ADR 0022. |
| Keyword search | Postgres `tsvector` + `ts_rank_cd` | Native, indexed. |
| Own algorithm | Reciprocal Rank Fusion (dense + keyword) + MMR diversification with per-document cap, written by hand | Small, testable, easy to explain on a whiteboard. Optional: own BM25 scorer to compare with `ts_rank_cd`. Tuned by the retrieval eval: k0=10, keyword list at weight 0.5, MMR lambda 0.85 with min-max relevance; equal-weight RRF at k0=60 cut Recall@10 to 0.71 (ADR 0029). |
| LLM | Amazon Bedrock only (Converse API, IAM, no external keys): **Claude Haiku 4.5** (`eu.anthropic.claude-haiku-4-5-20251001-v1:0` cross-Region profile) for the agent and Acme generation, falling back to the same model's `global.*` profile when `eu.*` fails (ADR 0028); `openai.gpt-oss-120b` (in Region) as the last automatic fallback; `qwen.qwen3-235b-a22b-2507` (in Region) as the evaluation judge | Reliable JSON and tool calling from Haiku ($1.10/$5.50 per 1M in EU), paid from credits. `llm.py`: timeout, backoff on throttling, fallback, prompt caching, Postgres `llm_cache`. All models verified with real calls on 2026-10-24; Haiku is limited to 10 requests/min per profile until the requested increase is approved. ADR 0017 (+ updates), ADR 0023. |
| Orchestration | Own agent loop with tool calling: `search`, `get_document`, `final_answer` (JSON schema) | Satisfies tool calling + multi-step + agentic bonus. Hard step cap (6), first search seeded by the server, last step forced to `final_answer`, own 80 s deadline; the token budget is the step cap, `k` <= 40 and the 8,000-character `get_document` cap (ADR 0005 update, ADR 0025). |
| Grounding | Structured answer `{claims:[{text, citations:[chunk_id]}], contradictions:[], status: answered/insufficient/conflicting}`; server drops claims citing chunks that were never retrieved | Mechanical anti-hallucination check, not only prompt wording. |
| Backend | AWS Lambda (Python 3.12 container image) behind a Lambda Function URL; hand-written router over the event, no web framework | Pay per request, always-free tier (1M req, 400k GB-s/month) covers the demo. Function URL instead of API Gateway: API Gateway cuts requests at 30 s, the agent loop can take longer (Function URL allows up to 15 min). Trade-off: no SSE streaming in Python Lambda, the trace comes back with the final answer. |
| UI | One static HTML page + vanilla JS, served by the same `api` Lambda at `GET /` | Same origin as the API: no CORS, no CloudFront, HTTPS from the Function URL. |
| Ingestion | Every document (UI upload or bulk JSONL shard) lands in S3; the S3 event triggers the `ingest` Lambda (parse, dedup, chunk, embed a whole file in batches of 96, insert), reserved concurrency 2. Events Lambda gives up on go to the SQS queue `IngestFailures`; `make redrive-ingest` reruns them. Browser uploads through a presigned S3 URL | One path for uploads and the bulk corpus; Lambda payload limit is 6 MB; a failed upload is never silently dropped. ADR 0018, ADR 0022. |
| Jobs | CodeBuild project `investigation-jobs`, `TARGET` = Makefile target: `dataset`, `acme`, `eval CONFIG=...`; outputs to S3 | Nothing runs on the author's computer; builds run up to 8 h (Lambda: 15 min). ADR 0018. |
| IaC | AWS CDK (Python), stacks split by lifecycle like binadar: `Investigation-Data-prod` (the Aurora cluster: stateful, rarely changes), `Investigation-prod` (Lambdas, documents bucket, jobs project, schema: changes on every merge), `Investigation-Cicd-prod` (CodeBuild, deployed by hand); `make diff` / `make deploy` | Same tool and workflow as binadar; a code deploy can never replace the database. Lambdas share one container image (`DockerImageFunction`, x86_64), without any ML runtime. |
| AWS access | AWS *project* (new AWS experience) on the Free plan: $100 credits, closes on expiry (2027-04-24) instead of billing. CLI via `aws login --profile investigation`; no long-lived keys | Free plan is a hard requirement. IAM Identity Center and Organizations are not available on it (enabling them upgraded the first account to Paid, which was abandoned). Isolated from binadar's account. |
| CI/CD | GitHub Actions `make check` on PRs; CodeBuild (via CodeConnections) comments `cdk diff` on PRs and deploys `main` | GitHub OIDC is denied by the Free-plan SCP (`iam:*Provider*`); see llm-wiki ADR 0012. |
| Observability | JSON log line per request (route, latency, tokens, LLM model, cache hit) in CloudWatch Logs; one CloudWatch dashboard `investigation-engine` (35 built-in metrics + Logs Insights tables over those lines), two alarms without actions; no custom metrics, no X-Ray | Free tier (3 dashboards x 50 metrics, 10 alarms); custom metrics cost $0.30 each (binadar's lesson). ADR 0033. |
| Tagging | `Project=investigation-engine` on the CDK app, activated as a cost allocation tag | Spend visible in Cost Explorer. |
| Secrets | No database password (IAM auth tokens, ADR 0021); GitHub token and the public API's admin token (ADR 0030) in SSM Parameter Store `SecureString` | Not in code, not in the image, not in plain Lambda env vars. No LLM API keys at all (Bedrock uses IAM). |
| Region | `eu-north-1` (Stockholm) | Fixed by the AWS project: all Regional resources must live there. |
| Tooling | Python 3.12, uv, ruff, pytest, boto3, AWS CDK (Node); Docker only inside CodeBuild | The laptop needs git and `aws login`, nothing else. |

## 3. Architecture

```
UI upload or bulk JSONL shard -> S3 -> ingest Lambda
   -> parse (pdf: pypdf, docx: python-docx, html: stdlib, md/jsonl: stdlib)
   -> normalize + sha256 -> dedup (exact) -> chunk (strategy A|B)
   -> embed (Bedrock Cohere Embed V4, 96 texts per request) -> Aurora (db.py): documents, chunks(text, tsv, embedding halfvec)

question
   -> agent loop (Claude Haiku on Bedrock + tools)
        plan sub-questions -> search(q) = dense top-k + keyword top-k -> RRF -> MMR
        -> get_document(id) when context is needed -> repeat <= N steps
   -> final_answer JSON -> citation validator -> answer | insufficient | conflicting
   -> UI: answer, claims with clickable chunk sources, contradictions, trace of steps
```

Schema (sketch): `documents(id, source, title, doc_type, created_at, content_hash, version, metadata jsonb)`,
`chunks(id, document_id, ord, text, tsv, embedding halfvec(1024), strategy)`,
`llm_cache(prompt_hash, model, response jsonb, created_at)`.
Update = new version replaces chunks in one transaction; delete cascades.

### Deployment (AWS, eu-north-1)

```
browser ──HTTPS──> Lambda Function URL ──> api Lambda (container image)
   │                                         GET  /                 -> index.html
   │                                         GET  /documents        POST /documents/upload-url
   │                                         DELETE /documents/{id} GET  /chunks/{id}
   │                                         POST /ask  (agent loop, timeout 90 s, reserved concurrency 4)
   │                                             ├──IAM──> Bedrock: Claude Haiku (eu.*, then global.*), gpt-oss-120b, Cohere Embed V4 (eu.*)
   │                                             └──IAM token, TLS──> Aurora express (PG 17.9 + pgvector)
   └──PUT (presigned)──> S3 uploads/ ──event──> ingest Lambda (same image, reserved concurrency 2; failures -> SQS)
                                                  parse -> dedup -> chunk -> Cohere V4 -> Aurora

CodeBuild investigation-jobs: dataset (HotpotQA -> shards in S3) | acme (Bedrock -> S3) | eval (-> S3)
CodeBuild investigation-pr-diff / investigation-deploy: CI/CD (ADR 0012)
SSM: GitHub token   CloudWatch Logs: JSON line per request
```

- One container image, two functions (`api`, `ingest`): same code, different handler.
- Lambdas and CodeBuild run outside any VPC; Aurora (express configuration) has no VPC and is
  reached through its internet access gateway with IAM auth tokens. No NAT, no database password.
- Cost estimate (eu-north-1 prices from the AWS Pricing API, 2026-10-24):

| Service | Price | 5 days of development | Per month of demo |
|---|---|---|---|
| Lambda | always free (1M requests, 400k GB-s/month) | $0 | $0 |
| Aurora Serverless v2 | $0.14 per ACU-hour while awake, storage ~$0.1/GB-month | ~$1-2 | ~$0.5-1 |
| Bedrock Cohere Embed V4 (`eu.*`) | ~$0.12 per 1M tokens (third-party trackers; the Pricing API gave no clear figure) | ~$1.5-3 (one or two full loads of ~11M tokens) | ~$0 |
| SQS (`IngestFailures`) | 1M requests/month free | $0 | $0 |
| Bedrock Claude Haiku | $1.10 / $5.50 per 1M (Haiku 4.5, EU) | ~$15-25 | ~$1-2 |
| Bedrock gpt-oss-120b, Qwen3 | $0.15/$0.60, $0.22/$0.88 per 1M | ~$1 | ~$0 |
| CodeBuild | 100 min/month free, then ~$0.005/min | ~$1-2 | ~$0 |
| S3, ECR | cents (ECR needs a lifecycle policy) | ~$0.1 | ~$0.2 |
| CloudFormation, CodeConnections, SSM, CloudWatch Logs, IAM, KMS | free at this volume | $0 | $0 |
| CloudWatch dashboard + 2 alarms, Logs Insights | free tier: 3 dashboards x 50 metrics (1 used, 35 metrics), 10 alarms, 5 GB Logs data incl. Insights scans; then $3 per dashboard-month | $0 | $0 |
| **Total** | | **~$20-30** | **~$2-4** |

## 4. Evaluation design

Question set: 72 (`eval/questions.jsonl`, 30, #26; `data/acme/questions.jsonl`, 42, #28; llm-wiki/09):
- 20 HotpotQA bridge + comparison (gold supporting titles), 3 Acme multi-hop
- 15 Acme multi-doc investigation questions (gold sources derived from the spec)
- 11 unanswerable: 5 HotpotQA (ask a fact no paragraph contains, checked against the dataset;
  nothing is removed from the index) + 6 Acme gaps
- 12 contradictory (planted conflicts in Acme)
- 11 simple single-hop (5 HotpotQA, 6 Acme)

Metrics:
- Retrieval: Recall@5/10, MRR (vs gold doc ids)
- Answer: EM/F1 for HotpotQA, LLM-as-judge correctness (Qwen3-235B, a different family than the Claude generator) for every question with a gold answer
- Citation accuracy: share of cited sources that are gold docs (claims without a valid citation are dropped by the validator, so none reach the answer)
- Abstention: precision/recall of `insufficient` on unanswerable set
- Contradiction: detection rate on contradictory set
- Cost/latency: tokens and seconds per question

Configurations compared:
1. chunking A (fixed 300 words, 50 overlap) vs B (structure-aware: headings/paragraphs, size cap)
2. dense only vs hybrid RRF vs hybrid RRF + MMR
3. single-shot RAG vs agent loop
4. (bonus) Cohere V4 embeddings at 1024 vs 512 vs 256 dimensions: done as Matryoshka prefixes of the stored vectors, exact search, no reload (`CONFIG=embeddings`, ADR 0032); Haiku vs gpt-oss-120b as the answering model (`CONFIG=agent-gpt-oss`)

Runs in the CodeBuild jobs project (`TARGET="eval CONFIG=<name>"`, configs `retrieval`, `agent`, `agent-structured`, `single-shot`); output: `eval/results/<config>.json` (via S3, committed by PR) + generated `EVALUATION.md` table and a failure analysis section.

## 5. Schedule

**Deadline: 2026-10-29 18:00 (Tbilisi).** Full scope below is ~12 days; 5 are available, so the
schedule is compressed and scope is cut (see "Cuts"). Code freeze 2026-10-29 15:00.

| Day | Date | Work | Done when |
|---|---|---|---|
| 1 | 10-24 | **Done:** repo, uv, Makefile, AWS project + `aws login`, CDK skeleton, CI/CD (GitHub Actions + CodeBuild PR diff/deploy), llm-wiki + ADRs 0001-0018, stack decisions | `/health` live, merges deploy automatically |
| 2 | 10-25 | **Done.** Aurora + S3 + `ingest` stub + jobs project (#8, #10, #12, #13), `dataset` job (#7), 2 chunkers (#6), RRF + MMR (#5); pulled forward from days 3-4: citation validator (#14), parsers (#16), UI page (#17), eval metrics (#15). Wave 2: embeddings (#19, Titan; Cohere V4 since #24), writes with dedup (#22), dense + keyword search (#23). `ingest` wiring (#21). Bulk load with Cohere: 66,555 documents. Plan: Stream A: Aurora + S3 + `ingest` + jobs project in the stack, schema, `dataset` job (HotpotQA shards), dedup, 2 chunkers, embeddings, bulk load, dense + keyword + RRF + MMR | `search("...")` returns fused results over >= 50k records |
| 3 | 10-26 | **Done.** Agent loop + `POST /ask` (#27, answers on the public URL), Acme generator + corpus (#28), eval runner + questions (#26), `acme-load`, Haiku `global.*` fallback (#29), search tuning (#30); pulled forward from day 5: full eval sweep (#31). Plan: Stream B: `llm.py` (Bedrock, retry/backoff/fallback/cache), agent loop, JSON answer, citation validator; stream C: start the `acme` job | `ask()` answers a HotpotQA multi-hop question with valid citations |
| 4 | 10-27 | **Done early (10-25/26):** Acme corpus indexed (#28), router + UI (#21, #27), persistence (every redeploy since 10-25). Plan: Streams C + D: Acme corpus + parsers indexed, Lambda router + HTML UI, persistence check; stream E: questions + metrics | public URL answers a question end to end |
| 5 | 10-28 | **Done early (10-26, #31).** Stream E: eval runner in the jobs project, config sweep (cached LLM calls) | `eval/results/*.json` for all configs |
| 6 | 10-29 | **Docs done early (10-26, #34-#37).** Left: AI_USAGE.md author sections, buffer, defense rehearsal. Plan: EVALUATION.md with failure analysis, README, AI_USAGE.md, buffer, defense rehearsal | submitted before 18:00 |

### Parallel workstreams

Streams talk only through `src/engine/models.py` (`ParsedDoc`, `Hit`, `Answer`) and these functions:

```python
parse(path, source) -> ParsedDoc               # C
search(query: str, k: int = 10) -> list[Hit]   # A
get_document(document_id: int) -> ParsedDoc    # A
ask(question: str) -> Answer                   # B
```

Until a function exists, consumers use a stub returning fixed data. Each stream lives in its own
branch/worktree and merges to `main` when its tests pass.

| Stream | Scope | Modules | Depends on | Start |
|---|---|---|---|---|
| A. Data + search | Aurora + S3 + `ingest` + jobs in the stack, schema, `dataset` job, dedup, 2 chunkers, embeddings, bulk load, dense + keyword, RRF + MMR, CRUD | `db.py`, `chunking.py`, `embed.py`, `index.py`, `search.py`, `handlers.py` (ingest), `cdk/` | Aurora, Bedrock (account verification) | day 2 |
| B. LLM + agent | Bedrock client (retry/backoff/timeout/fallback/prompt caching/cache), tools, agent loop, JSON answer, citation validator | `llm.py`, `agent.py` | stub `search`, Bedrock | day 3 |
| C. Acme corpus + parsers | generator (`acme` job), planted contradictions/gaps, `GROUND_TRUTH.md`, PDF/DOCX/HTML/MD parsers | `parsers.py`, `scripts/gen_acme.py`, `data/acme/` | `llm.py`, jobs project | day 3 |
| D. Infra + API + UI | Done: AWS project, CDK, CI/CD, HTML page (#17), Lambda routes and presigned uploads (#21), persistence check | `handlers.py`, `static/`, `cdk/` | stubs `ask`/`search` | day 4 |
| E. Evaluation | questions, Recall@K/MRR/citation metrics (pure functions), runner (`eval` job), config sweep, EVALUATION.md | `eval/` | real `ask` for runs only | day 4 |

Merge points: A+B on day 3 (real search inside the agent); C into A on day 4 (Acme indexed);
D serves real A+B on day 4; E runs the sweep on day 5.
Bedrock quotas are shared: the bulk load (A), Acme generation (C) and eval runs (E) should not run at the same time.

### Parallel agent waves

To write code faster, independent tasks run as parallel coding agents, each in its own git
worktree and branch, each ending in a PR that must pass CI. Rules:
- **One owner per file per wave.** Two agents never edit the same file. Shared files
  (`src/engine/models.py`, `cdk/app.py`, `pyproject.toml` + `uv.lock`, `handlers.py`) have exactly
  one owning task in a wave; everyone else codes against the contract.
- **Contracts first.** Wave 0 fixes the function signatures every wave-1 agent codes against.
- **Dependencies are added only by the owner of `pyproject.toml`** in that wave (uv.lock conflicts
  are painful); other agents list what they need in their PR description.
- **Review is the bottleneck, not typing.** At most 3-4 agents at a time: the author must understand
  every merged line for the interview. The main session reviews and merges; the author reads each PR.
- **Bedrock quota is shared:** at most one agent runs bulk embedding, Acme generation or eval at once.

| Wave | Task | Owns files | Needs | Tests |
|---|---|---|---|---|
| 0 | **Done (#4):** contracts in `models.py`, signatures for `chunking`, `rank`, `grounding`, `parsers`, `eval/metrics`; dedup hash in `index.py`; API contract (llm-wiki 04); wave-1 dependencies added. `db`/`embed`/`llm`/`search` signatures are left to their wave-2 owners (nobody calls them in wave 1) | `models.py`, module stubs, `pyproject.toml` | - | dedup tests |
| 1 | **Done (#6):** Chunkers A (fixed 300/50) and B (structure-aware) | `chunking.py` | wave 0 | pure unit tests |
| 1 | **Done (#5):** RRF + MMR with per-document cap | `rank.py` | wave 0 | pure unit tests |
| 1 | **Done (#16):** Parsers PDF/DOCX/HTML/MD/JSONL -> `ParsedDoc`, metadata, small fixtures | `parsers.py`, `tests/fixtures/` | wave 0 | fixture tests |
| 1 | **Done (#14):** Citation validator + `Answer` assembly, statuses | `grounding.py` | wave 0 | pure unit tests |
| 1 | **Done (#15):** Eval metrics: Recall@K, MRR, EM/F1, citation accuracy, abstention P/R, contradiction rate | `eval/metrics.py` | wave 0 | pure unit tests |
| 1 | **Done (#8, #10, #12, #13):** Infra: Aurora (express configuration, IAM auth, no secret: ADR 0021), S3 bucket + event, `ingest` Lambda (stub), `investigation-jobs` project, schema SQL | `cdk/app.py`, `sql/schema.sql`, `.codebuild/jobs.yml` | - | synth + PR diff |
| 1 | **Done (#7):** Dataset job: HotpotQA download, dedup, stats, JSONL shards to S3 | `scripts/dataset.py` | wave 0 | dedup unit tests |
| 1 | **Done (#17):** UI page against the API contract (stub responses) | `static/index.html` | wave 0 | manual |
| 2 | **Done (#19):** contracts for wave 2 (`index.upsert/delete`, `search.*` signatures), `embed.py` (Titan V2) | `embed.py`, `index.py`, `search.py` stubs | wave 1 | one live call |
| 2 | **Done (#22):** `db.transaction()` + `index.upsert/delete`: dedup checks before embedding, one Titan call per distinct chunk, insert/update in one transaction; 137 ms per document in Region | `db.py`, `index.py` | infra | against Aurora |
| 2 | **Done (#19, #20):** `embed.py` (Titan) + `llm.py` (Bedrock client, retry, fallback, cache; ADR 0023) | `embed.py`, `llm.py` | Bedrock verified | unit + one live call |
| 2 | **Done (#23):** `search.py`: dense (partial HNSW per strategy) + OR keyword -> RRF -> MMR, modes `dense`/`hybrid`/`mmr`; document and chunk reads (ADR 0024) | `search.py`, `sql/schema.sql` | `db.py`, `rank.py` | against Aurora |
| 2 | **Done (#21):** API routes (documents, upload URL, delete, chunks) + ingest handler wiring | `handlers.py` | `db.py`, `parsers.py`, `chunking.py` | router unit tests + smoke |
| 2 | **Done (#24):** Cohere Embed V4 instead of Titan (ADR 0022): `embed_documents` (96 per request) / `embed_query`, `index.upsert_many` per shard, `ingest` capped at 2, IAM through the `eu.*` profile, failed ingest events in SQS + `make redrive-ingest` | `embed.py`, `index.py`, `handlers.py`, `cdk/app.py`, `scripts/redrive_ingest.py` | Bedrock (Cohere quota) | unit + live calls, `upsert_many` against Aurora |
| 3 | **Done (#25):** contracts for wave 3: `Answer.answer` (short answer for EM/F1), `agent.ask(question, strategy, mode, max_steps)` stub with the trace contract | `models.py`, `agent.py` stub | wave 2 | - |
| 3 | **Done (#27):** Agent loop + tools (ADR 0025): seeded search, `search` / `get_document` / `final_answer`, forced last step, 80 s deadline, `POST /ask`, reserved concurrency 4 on `api`, short answer in the UI | `agent.py`, `llm.py`, `grounding.py`, `handlers.py`, `cdk/app.py`, `static/index.html` | `llm.py`, `search.py`, `grounding.py` | two live questions |
| 3 | **Done (#28):** Acme generator (spec -> Haiku -> 4 formats, every fact checked in the parsed file; ADR 0026) + `GROUND_TRUTH.md` + 42 Acme questions; corpus committed, `make acme-load` after merge | `scripts/gen_acme.py`, `data/acme/` | `llm.py`, jobs project | ground-truth check |
| 3 | **Done (#26):** Eval runner + config sweep in the jobs project, HotpotQA questions (moved from wave 2: the runner defines their format): `make eval CONFIG=retrieval\|agent\|agent-fixed\|single-shot`, 30 questions, Qwen3 judge, Haiku pacing, memoized query embeddings (ADR 0027). Dry run on 3 questions done (10-26); full runs, trace in records, judge sees status and contradictions, search pacing (#31) | `eval/run.py`, `eval/questions.jsonl` | `agent.py`, dataset labels | dry run on 3 questions |
| 4 | **Done (#34, #35, #36):** AI_USAGE.md, README, EVALUATION.md, one agent each; eval cost fix found on the way (#37) | `AI_USAGE.md`, `README.md`, `EVALUATION.md` | results | CI |
| 5 | **Done (#40):** monitoring dashboard + alarms (ADR 0033), load test job, performance numbers | `cdk/app.py` (`_dashboard`), `scripts/load_test.py` | deployed system | unit tests + one job run |

Wave 1 tasks are pure Python or infra and can all start immediately (Bedrock is not needed);
wave 2 starts when infra is merged (Bedrock works since 2026-10-24, see ADR 0017 update).

Cuts (in order of what goes first if behind):
- Acme corpus: ~60-100 docs instead of 150-300.
- Question set: 40-45 instead of 60.
- Config comparison: chunking A vs B and dense vs hybrid are mandatory; single-shot vs agent only if time allows.
- Bonuses: none planned (streaming dropped: not supported by Python Lambda Function URLs). Everything else is listed as "future work" in the README.

Reference phases (original estimates):

0. **Setup + data check (0.5 d)** — repo, uv project, AWS project + budget alert (done). `dataset` job: download HotpotQA, count unique paragraphs, decide subset size, fixed seed.
1. **Ingestion (2 d)** — parsers for 4 formats, metadata, hashing/dedup, two chunkers, CRUD on documents. Tests on small fixtures.
2. **Synthetic Acme corpus (1 d)** — generator script (LLM once, outputs committed), planted contradictions and gaps listed in `data/acme/GROUND_TRUTH.md`.
3. **Index + search (1.5 d)** — bulk load through S3 + `ingest` (Bedrock embeddings, `db.py`), dense + keyword queries, RRF + MMR, unit tests for fusion.
4. **Agent + grounding (2 d)** — Bedrock client (retries, backoff on throttling, timeout, fallback model, prompt caching, cache), tools, loop, JSON answer, citation validator, abstain/conflict statuses.
5. **API + UI (1 d)** — `POST /documents/upload-url`, `PUT/DELETE /documents/{id}`, `GET /documents`, `POST /ask`, `GET /chunks/{id}`; single HTML page; Lambda router.
6. **Evaluation (2 d)** — question set, runner, metrics, config sweep, EVALUATION.md with failure analysis.
7. **Deploy (1 d)** — Dockerfile, CDK stacks (Aurora, S3, Lambdas, Function URL), budget alert, persistence check (redeploy, data still there), DEPLOYMENT section with limits and cost.
8. **Docs + defense prep (1 d)** — README, AI_USAGE.md, rehearse: walk the pipeline, rewrite RRF/MMR by hand, add a small feature without AI.

Core total ~12 days. Bonus only after phase 8: next best value is
prompt-injection tests (plant malicious text in a doc) and the 512 vs 1024 embedding comparison (done: ADR 0032).

## 6. Risks

- **Haiku throughput: 10 requests/min per profile** (Bedrock quota of a new account). An eval sweep
  takes ~50 min (three answer runs, 72 questions, measured 2026-10-26). Mitigation: account-level increase filed (support case opened), spread calls over the
  `eu.*` and `global.*` pools (`llm.py` moves to `global.*` when `eu.*` fails, ADR 0028), LLM
  cache, gpt-oss-120b (100 requests/min) as the last fallback.
- **Cohere Embed V4 pool: 20 requests/min, 16.2M tokens/day** shared by the bulk load and query
  embeddings. A full load takes ~65 min (measured 10-25) and ~11M tokens. Mitigation: 96 texts per request,
  `ingest` capped at 2, adaptive retry, failed events kept in `IngestFailures` for a redrive;
  never run a load and an eval at once; `global.*` as a second pool.
- **Aurora resume after a pause** (15-25 s, median ~18.5 s measured in the logs, llm-wiki/07 Performance). Mitigation: connect retry in `db.py`, warm the database before a demo.
- **Aurora express configuration** (Free plan): public IAM-only endpoint, default engine version, ACU range set after creation. Mitigation: least-privilege `app` role, ADR 0021.
- **HotpotQA chunking comparison is weak** (paragraphs already short). Compare chunkers on Acme, say so in the report.
- **LLM-as-judge bias**. Judge from a different family (Qwen3 vs Claude), spot-check 10 answers by hand, report agreement.
- **Defense without AI**. Keep code small and own; no framework magic you cannot rewrite on paper.
- **Lambda cold start** (container pull, no model any more; measured init p50 1.3 s, p95 1.7 s) plus Aurora resume. Provisioned concurrency costs money, not used.
- **Credits and Free-plan expiry.** $100 total, the account closes on 2027-04-24 or when credits run out. Haiku in repeated eval sweeps is the main spend: cache everything, check spend in Billing.
- **Public Function URL (auth `NONE`)**: anyone could delete the seed corpus or loop `POST /ask`
  into the credits. Mitigation (#39, ADR 0030): seed documents read-only (403), admin token
  `x-admin-token` from SSM, 150 uncached `/ask` LLM calls and 50 upload URLs per UTC day (429),
  5 MB signed upload size, reserved concurrency 4. Left: the caps are global, one abuser blocks
  the day for reviewers (the admin token still works).
- **Infra ate day 1.** Streams start on day 2 with one day less of buffer.

Closed on 2026-10-24: Bedrock blocked during account verification (quotas opened by themselves);
cross-Region inference denied by the Free-plan SCP (it is not); corpus below 50k (66,555 unique
HotpotQA documents, PR #7).
Closed on 2026-10-25: Titan throttling during the bulk load (it happened: the load stalled at
1,853 documents; replaced by Cohere Embed V4, ADR 0022, #24).
