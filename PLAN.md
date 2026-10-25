# AI Investigation Engine — MVP plan

Source: Upgaming Talent Growth Program, "Applied AI – AI Investigation Engine Task" ([docs/task.pdf](docs/task.pdf), Georgian).
Goal: multi-source investigation over 50k+ documents with cited, evidence-based answers that
abstain on missing data and flag contradictions. Not "chat with PDF".

Deliverables: GitHub repo (with real history), live demo URL, README, Evaluation Report,
AI Usage Report. Interview: explain architecture, walk the RAG pipeline, fix bugs and add
features live **without AI**. Every line here must be explainable — so no LangChain/LlamaIndex,
own small code instead.

## 0. Status

**Updated 2026-10-25 (day 2 of 6).** Wave 0 and wave 1 merged (PRs #4-#17). Wave 2 in progress:
contracts and `embed.py` (#19), document writes (#22) merged; search, LLM client, API routes in review.
**Behind:** the day 2 goal (`search()` over >= 50k records) is not met: nothing is indexed yet,
`ingest` is a stub, `search.py`/`llm.py` are not merged.
Next: merge search (#23), LLM client (#20), API routes + ingest (#21), then the bulk load.

How status is kept (every PR that finishes or advances a task updates it in the same PR):
- this section: date, current day and wave, what is behind, what is next;
- the wave table in section 5: the row gets `**Done (#PR):**`; the day table: `**Done:**` or
  `**In progress:**` with what is left;
- the checklist below: `[x]` only when the requirement works end to end on the deployed system;
  otherwise `[ ]` with a `partial:` note naming the merged pieces (PR numbers) and what is missing.
  No note = not started.

## 1. Requirements checklist (from the task)

Ingestion
- [ ] >= 3 file formats (plan: PDF, DOCX, Markdown/HTML, JSONL) — partial: `parsers.py` (#16); not wired into `ingest`
- [ ] text + metadata extraction (source, title, date, doc type, service names) — partial: `ParsedDoc` metadata from parsers (#16); not stored
- [ ] chunking, >= 2 strategies compared — partial: fixed + structure-aware chunkers (#6); comparison needs the eval
- [ ] duplicate handling — partial: sha256 of normalized text (#4), HotpotQA deduplicated in the dataset job (#7), `index.upsert` skips same-hash documents (#22); `ingest` not wired
- [ ] add / update / delete documents — partial: `index.upsert/delete` (#22), checked live on Aurora; needs the API routes and `ingest` wiring

Search
- [ ] vector DB, embeddings, semantic search — partial: Aurora + pgvector schema deployed (#8, #10); no `embed.py`, nothing indexed
- [ ] hybrid search (semantic + keyword) — partial: `tsvector` column in the schema (#8); no `search.py`
- [ ] >= 1 own ranking/search algorithm (not only library calls) — partial: RRF + MMR with per-document cap (#5); not called by search yet

LLM / RAG
- [ ] RAG, multi-document synthesis, multi-step handling of complex questions
- [ ] answers grounded in evidence, sources + citations — partial: citation validator drops claims citing unretrieved chunks (#14); no agent
- [ ] contradiction detection attempt — partial: `conflicting` answer status (#14); no detection prompt
- [ ] abstain when information is insufficient — partial: `insufficient` answer status (#14); no agent
- [ ] LLM error/limit handling (timeouts, 429, malformed output) — needs `llm.py` (wave 2)
- [ ] >= 1 tool-calling mechanism — needs `agent.py` (wave 3)

Evaluation
- [ ] own automated eval, >= 40 questions: simple, multi-hop, multi-doc, unanswerable, contradictory
- [ ] retrieval + answer metrics: Recall@K, MRR, Answer Correctness, Citation Accuracy — partial: pure metric functions (#15); no judge, no runner
- [ ] >= 2 configurations compared
- [ ] error analysis: where it fails, why, how to improve

Backend / UI
- [ ] Python backend, functional UI: upload/manage docs, ask, inspect sources — partial: page served at `GET /` (#17), works only in `?stub` mode; API routes return 404

Dataset
- [ ] >= 50,000 documents/records, reproducible subset with justification — partial: dataset job, 66,555 unique HotpotQA documents as JSONL shards (#7); not indexed
- [ ] cross-document linking, source identity preserved, incomplete/contradictory data, repeatable eval — needs the Acme corpus (wave 3)

Deployment
- [ ] public URL on free tier, DB integrated, data survives restart — partial: Function URL serves `/` and `/health`, Aurora with deletion protection (#10, #13); app does not use the DB yet, persistence not checked
- [ ] secrets protected, deployment architecture + free-tier limits documented — partial: IAM auth tokens, no stored secrets (ADR 0021), `llm-wiki/07-infrastructure.md`; README DEPLOYMENT section not written

Quality
- [ ] modular code, error handling, automated tests, safe config, docs, perf + LLM cost notes — partial: module per stream, tests per module, CI; README, perf and LLM cost notes missing

Bonus (only after core): LLM/embedding comparison, agentic RAG, reranker, prompt-injection tests,
caching, streaming, observability, load test.

## 2. Key decisions

Each decision has an ADR in [llm-wiki/adr/](llm-wiki/adr/) with context, cost and rejected alternatives.
[docs/SERVICES.md](docs/SERVICES.md) is an early draft, superseded.

| Area | Choice | Why / trade-off |
|---|---|---|
| Corpus (bulk) | HotpotQA `distractor` validation split (7,405 questions x 10 paragraphs), dedup by title+text | Gold supporting facts give free Recall@K/MRR/citation labels. Many paragraphs repeat across questions: dedup is real, not cosmetic. **Verify unique count >= 50k in phase 0**; if short, add part of `train`. |
| Corpus (investigation) | Synthetic "Acme Payments" org: ~60-100 docs (incident reports PDF, change logs MD, runbooks DOCX, status pages HTML) generated once by Claude Haiku in a CodeBuild job, committed | Matches the task's example question (March payment outage). Planted contradictions (two reports disagree on root cause/time) and gaps (unanswerable). HotpotQA has neither. |
| Vector DB | Aurora Serverless v2, PostgreSQL 17 + pgvector (`halfvec(1024)`, HNSW) + built-in full-text search; min 0 ACU (pauses when idle), max 2-4 ACU; **express configuration** (the only Aurora the Free plan creates): no VPC, internet access gateway, IAM auth tokens over TLS with `pg8000`, no password or secret | One store for docs, chunks, vectors, keyword index, CRUD, dedup hashes, LLM cache. Idle cost is ~storage only, so the credits last until the interview; no NAT, no secrets, no Data API limits. Trade-off: ~15 s resume after a pause, a public (IAM-only) endpoint, own connection handling. No local database. ADR 0015, ADR 0021. |
| Embeddings | Amazon Bedrock Titan Text Embeddings V2 (`amazon.titan-embed-text-v2:0`), 1024 dimensions, in `eu-north-1` | ~$0.19 for the whole corpus, no model in the Lambda image, nothing on the laptop. One text per request: the bulk load is bound by the account's RPM quota. Bonus comparison: 512 vs 1024 dimensions. Fallback: fastembed `bge-small` in CodeBuild. ADR 0016. |
| Keyword search | Postgres `tsvector` + `ts_rank_cd` | Native, indexed. |
| Own algorithm | Reciprocal Rank Fusion (dense + keyword) + MMR diversification with per-document cap, written by hand | Small, testable, easy to explain on a whiteboard. Optional: own BM25 scorer to compare with `ts_rank_cd`. |
| LLM | Amazon Bedrock only (Converse API, IAM, no external keys): **Claude Haiku 4.5** (`eu.anthropic.claude-haiku-4-5-20251001-v1:0` cross-Region profile) for the agent and Acme generation; `openai.gpt-oss-120b` (in Region) as automatic fallback; `qwen.qwen3-235b-a22b-2507` (in Region) as the evaluation judge | Reliable JSON and tool calling from Haiku ($1.10/$5.50 per 1M in EU), paid from credits. `llm.py`: timeout, backoff on throttling, fallback, prompt caching, Postgres `llm_cache`. All models verified with real calls on 2026-10-24; Haiku is limited to 10 requests/min per profile until the requested increase is approved. ADR 0017 (+ update). |
| Orchestration | Own agent loop with tool calling: `search`, `get_document`, `final_answer` (JSON schema) | Satisfies tool calling + multi-step + agentic bonus. Hard step cap (e.g. 6), token budget per question. |
| Grounding | Structured answer `{claims:[{text, citations:[chunk_id]}], contradictions:[], status: answered/insufficient/conflicting}`; server drops claims citing chunks that were never retrieved | Mechanical anti-hallucination check, not only prompt wording. |
| Backend | AWS Lambda (Python 3.12 container image) behind a Lambda Function URL; hand-written router over the event, no web framework | Pay per request, always-free tier (1M req, 400k GB-s/month) covers the demo. Function URL instead of API Gateway: API Gateway cuts requests at 30 s, the agent loop can take longer (Function URL allows up to 15 min). Trade-off: no SSE streaming in Python Lambda, the trace comes back with the final answer. |
| UI | One static HTML page + vanilla JS, served by the same `api` Lambda at `GET /` | Same origin as the API: no CORS, no CloudFront, HTTPS from the Function URL. |
| Ingestion | Every document (UI upload or bulk JSONL shard) lands in S3; the S3 event triggers the `ingest` Lambda (parse, dedup, chunk, embed, insert), reserved concurrency ~5. Browser uploads through a presigned S3 URL | One path for uploads and the bulk corpus; Lambda payload limit is 6 MB. ADR 0018. |
| Jobs | CodeBuild project `investigation-jobs`, `TARGET` = Makefile target: `dataset`, `acme`, `eval CONFIG=...`; outputs to S3 | Nothing runs on the author's computer; builds run up to 8 h (Lambda: 15 min). ADR 0018. |
| IaC | AWS CDK (Python), stacks split by lifecycle like binadar: `Investigation-Data-prod` (the Aurora cluster: stateful, rarely changes), `Investigation-prod` (Lambdas, documents bucket, jobs project, schema: changes on every merge), `Investigation-Cicd-prod` (CodeBuild, deployed by hand); `make diff` / `make deploy` | Same tool and workflow as binadar; a code deploy can never replace the database. Lambdas share one container image (`DockerImageFunction`, x86_64), without any ML runtime. |
| AWS access | AWS *project* (new AWS experience) on the Free plan: $100 credits, closes on expiry (2027-04-24) instead of billing. CLI via `aws login --profile investigation`; no long-lived keys | Free plan is a hard requirement. IAM Identity Center and Organizations are not available on it (enabling them upgraded the first account to Paid, which was abandoned). Isolated from binadar's account. |
| CI/CD | GitHub Actions `make check` on PRs; CodeBuild (via CodeConnections) comments `cdk diff` on PRs and deploys `main` | GitHub OIDC is denied by the Free-plan SCP (`iam:*Provider*`); see llm-wiki ADR 0012. |
| Observability | JSON log line per request (route, latency, tokens, LLM model, cache hit) in CloudWatch Logs; no custom metrics | Free tier; custom metrics cost $0.30 each (binadar's lesson). Logs Insights for analysis. |
| Tagging | `Project=investigation-engine` on the CDK app, activated as a cost allocation tag | Spend visible in Cost Explorer. |
| Secrets | No database password (IAM auth tokens, ADR 0021); GitHub token in SSM Parameter Store `SecureString` | Not in code, not in the image, not in plain Lambda env vars. No LLM API keys at all (Bedrock uses IAM). |
| Region | `eu-north-1` (Stockholm) | Fixed by the AWS project: all Regional resources must live there. |
| Tooling | Python 3.12, uv, ruff, pytest, boto3, AWS CDK (Node); Docker only inside CodeBuild | The laptop needs git and `aws login`, nothing else. |

## 3. Architecture

```
UI upload or bulk JSONL shard -> S3 -> ingest Lambda
   -> parse (pdf: pypdf, docx: python-docx, html: stdlib, md/jsonl: stdlib)
   -> normalize + sha256 -> dedup (exact) -> chunk (strategy A|B)
   -> embed (Bedrock Titan V2) -> Aurora (db.py): documents, chunks(text, tsv, embedding halfvec)

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
   │                                         POST /ask  (agent loop, timeout 90 s)
   │                                             ├──IAM──> Bedrock: Claude Haiku (eu.*), gpt-oss-120b, Titan V2
   │                                             └──IAM token, TLS──> Aurora express (PG 17.9 + pgvector)
   └──PUT (presigned)──> S3 uploads/ ──event──> ingest Lambda (same image, reserved concurrency ~5)
                                                  parse -> dedup -> chunk -> Titan V2 -> Aurora

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
| Bedrock Titan Embeddings V2 | $0.021 per 1M tokens | ~$0.4 | ~$0 |
| Bedrock Claude Haiku | $1.10 / $5.50 per 1M (Haiku 4.5, EU) | ~$15-25 | ~$1-2 |
| Bedrock gpt-oss-120b, Qwen3 | $0.15/$0.60, $0.22/$0.88 per 1M | ~$1 | ~$0 |
| CodeBuild | 100 min/month free, then ~$0.005/min | ~$1-2 | ~$0 |
| S3, ECR | cents (ECR needs a lifecycle policy) | ~$0.1 | ~$0.2 |
| CloudFormation, CodeConnections, SSM, CloudWatch Logs, IAM, KMS | free at this volume | $0 | $0 |
| **Total** | | **~$20-30** | **~$2-4** |

## 4. Evaluation design

Question set (`eval/questions.jsonl`, >= 40, target 60):
- 20 HotpotQA bridge + comparison (gold supporting titles/sentences)
- 15 Acme multi-doc investigation questions (gold doc ids written by hand)
- 10 unanswerable (Acme + HotpotQA questions with gold paragraphs removed from the index)
- 10 contradictory (planted conflicts in Acme)
- 5 simple single-hop

Metrics:
- Retrieval: Recall@5/10, MRR (vs gold doc ids)
- Answer: EM/F1 for HotpotQA, LLM-as-judge correctness (Qwen3-235B, a different family than the Claude generator) for the rest
- Citation accuracy: share of cited chunks that belong to gold docs; share of claims with >= 1 valid citation
- Abstention: precision/recall of `insufficient` on unanswerable set
- Contradiction: detection rate on contradictory set
- Cost/latency: tokens and seconds per question

Configurations compared:
1. chunking A (fixed 300 tokens, 50 overlap) vs B (structure-aware: headings/paragraphs, size cap)
2. dense only vs hybrid RRF vs hybrid RRF + MMR
3. single-shot RAG vs agent loop
4. (bonus, cheap) Titan V2 embeddings at 512 vs 1024 dimensions

Runs in the CodeBuild jobs project (`TARGET=eval`); output: `eval/results/<config>.json` (via S3, committed by PR) + generated `EVALUATION.md` table and a failure analysis section.

## 5. Schedule

**Deadline: 2026-10-29 18:00 (Tbilisi).** Full scope below is ~12 days; 5 are available, so the
schedule is compressed and scope is cut (see "Cuts"). Code freeze 2026-10-29 15:00.

| Day | Date | Work | Done when |
|---|---|---|---|
| 1 | 10-24 | **Done:** repo, uv, Makefile, AWS project + `aws login`, CDK skeleton, CI/CD (GitHub Actions + CodeBuild PR diff/deploy), llm-wiki + ADRs 0001-0018, stack decisions | `/health` live, merges deploy automatically |
| 2 | 10-25 | **In progress.** Done: Aurora + S3 + `ingest` stub + jobs project (#8, #10, #12, #13), `dataset` job (#7), 2 chunkers (#6), RRF + MMR (#5); pulled forward from days 3-4: citation validator (#14), parsers (#16), UI page (#17), eval metrics (#15). Left: dedup in `ingest`, Titan embeddings, `db.py` writes, bulk load, dense + keyword search. Plan: Stream A: Aurora + S3 + `ingest` + jobs project in the stack, schema, `dataset` job (HotpotQA shards), dedup, 2 chunkers, Titan embeddings, bulk load, dense + keyword + RRF + MMR | `search("...")` returns fused results over >= 50k records |
| 3 | 10-26 | Stream B: `llm.py` (Bedrock, retry/backoff/fallback/cache), agent loop, JSON answer, citation validator; stream C: start the `acme` job | `ask()` answers a HotpotQA multi-hop question with valid citations |
| 4 | 10-27 | Streams C + D: Acme corpus + parsers indexed, Lambda router + HTML UI, persistence check; stream E: questions + metrics | public URL answers a question end to end |
| 5 | 10-28 | Stream E: eval runner in the jobs project, config sweep (cached LLM calls) | `eval/results/*.json` for all configs |
| 6 | 10-29 | EVALUATION.md with failure analysis, README, AI_USAGE.md, buffer, defense rehearsal | submitted before 18:00 |

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
| A. Data + search | Aurora + S3 + `ingest` + jobs in the stack, schema, `dataset` job, dedup, 2 chunkers, Titan embeddings, bulk load, dense + keyword, RRF + MMR, CRUD | `db.py`, `chunking.py`, `embed.py`, `index.py`, `search.py`, `handlers.py` (ingest), `cdk/` | Aurora, Bedrock (account verification) | day 2 |
| B. LLM + agent | Bedrock client (retry/backoff/timeout/fallback/prompt caching/cache), tools, agent loop, JSON answer, citation validator | `llm.py`, `agent.py` | stub `search`, Bedrock | day 3 |
| C. Acme corpus + parsers | generator (`acme` job), planted contradictions/gaps, `GROUND_TRUTH.md`, PDF/DOCX/HTML/MD parsers | `parsers.py`, `scripts/gen_acme.py`, `data/acme/` | `llm.py`, jobs project | day 3 |
| D. Infra + API + UI | Done: AWS project, CDK, CI/CD, HTML page (#17). Left: Lambda routes, presigned uploads, persistence check | `handlers.py`, `static/`, `cdk/` | stubs `ask`/`search` | day 4 |
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
| 2 | `embed.py` (Titan) + `llm.py` (Bedrock client, retry, fallback, cache) | `embed.py`, `llm.py` | Bedrock verified | unit + one live call |
| 2 | `search.py`: dense + keyword SQL -> `rank.py` | `search.py` | `db.py`, `rank.py` | against Aurora |
| 2 | API routes + ingest handler wiring | `handlers.py` | `db.py`, `parsers.py`, `chunking.py` | router unit tests + smoke |
| 3 | Agent loop + tools | `agent.py` | `llm.py`, `search.py`, `grounding.py` | one live question |
| 3 | Acme generator + `GROUND_TRUTH.md` + Acme questions | `scripts/gen_acme.py`, `data/acme/` | `llm.py`, jobs project | ground-truth check |
| 3 | Eval runner + config sweep in the jobs project, HotpotQA questions (moved from wave 2: the runner defines their format) | `eval/run.py`, `eval/questions.jsonl` | `agent.py`, dataset labels | dry run on 3 questions |
| 4 | EVALUATION.md, README, AI_USAGE.md | docs | results | - |

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
3. **Index + search (1.5 d)** — bulk load through S3 + `ingest` (Titan embeddings, `db.py`), dense + keyword queries, RRF + MMR, unit tests for fusion.
4. **Agent + grounding (2 d)** — Bedrock client (retries, backoff on throttling, timeout, fallback model, prompt caching, cache), tools, loop, JSON answer, citation validator, abstain/conflict statuses.
5. **API + UI (1 d)** — `POST /documents/upload-url`, `PUT/DELETE /documents/{id}`, `GET /documents`, `POST /ask`, `GET /chunks/{id}`; single HTML page; Lambda router.
6. **Evaluation (2 d)** — question set, runner, metrics, config sweep, EVALUATION.md with failure analysis.
7. **Deploy (1 d)** — Dockerfile, CDK stacks (Aurora, S3, Lambdas, Function URL), budget alert, persistence check (redeploy, data still there), DEPLOYMENT section with limits and cost.
8. **Docs + defense prep (1 d)** — README, AI_USAGE.md, rehearse: walk the pipeline, rewrite RRF/MMR by hand, add a small feature without AI.

Core total ~12 days. Bonus only after phase 8: next best value is
prompt-injection tests (plant malicious text in a doc) and the 512 vs 1024 embedding comparison.

## 6. Risks

- **Haiku throughput: 10 requests/min per profile** (Bedrock quota of a new account). An eval sweep
  takes ~2 h. Mitigation: account-level increase filed (support case opened), spread calls over the
  `eu.*` and `global.*` pools, LLM cache, gpt-oss-120b (100 requests/min) as fallback.
- **Titan throttling during the bulk load** (its quota is not visible in Service Quotas).
  Mitigation: reserved concurrency on `ingest`, backoff on `ThrottlingException`; fallback Cohere
  Embed V4 (96 texts per request).
- **Aurora resume after a pause** (~15 s). Mitigation: connect retry in `db.py`, warm the database before a demo, document first-request latency.
- **Aurora express configuration** (Free plan): public IAM-only endpoint, default engine version, ACU range set after creation. Mitigation: least-privilege `app` role, ADR 0021.
- **HotpotQA chunking comparison is weak** (paragraphs already short). Compare chunkers on Acme, say so in the report.
- **LLM-as-judge bias**. Judge from a different family (Qwen3 vs Claude), spot-check 10 answers by hand, report agreement.
- **Defense without AI**. Keep code small and own; no framework magic you cannot rewrite on paper.
- **Lambda cold start** (container pull, no model any more, ~1-2 s) plus Aurora resume. Document first-request latency. Provisioned concurrency costs money, not used.
- **Credits and Free-plan expiry.** $100 total, the account closes on 2027-04-24 or when credits run out. Haiku in repeated eval sweeps is the main spend: cache everything, check spend in Billing.
- **Infra ate day 1.** Streams start on day 2 with one day less of buffer.

Closed on 2026-10-24: Bedrock blocked during account verification (quotas opened by themselves);
cross-Region inference denied by the Free-plan SCP (it is not); corpus below 50k (66,555 unique
HotpotQA documents, PR #7).
