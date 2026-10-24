# AI Investigation Engine — MVP plan

Source: Upgaming Talent Growth Program, "Applied AI – AI Investigation Engine Task" ([docs/task.pdf](docs/task.pdf), Georgian).
Goal: multi-source investigation over 50k+ documents with cited, evidence-based answers that
abstain on missing data and flag contradictions. Not "chat with PDF".

Deliverables: GitHub repo (with real history), live demo URL, README, Evaluation Report,
AI Usage Report. Interview: explain architecture, walk the RAG pipeline, fix bugs and add
features live **without AI**. Every line here must be explainable — so no LangChain/LlamaIndex,
own small code instead.

## 1. Requirements checklist (from the task)

Ingestion
- [ ] >= 3 file formats (plan: PDF, DOCX, Markdown/HTML, JSONL)
- [ ] text + metadata extraction (source, title, date, doc type, service names)
- [ ] chunking, >= 2 strategies compared
- [ ] duplicate handling
- [ ] add / update / delete documents

Search
- [ ] vector DB, embeddings, semantic search
- [ ] hybrid search (semantic + keyword)
- [ ] >= 1 own ranking/search algorithm (not only library calls)

LLM / RAG
- [ ] RAG, multi-document synthesis, multi-step handling of complex questions
- [ ] answers grounded in evidence, sources + citations
- [ ] contradiction detection attempt
- [ ] abstain when information is insufficient
- [ ] LLM error/limit handling (timeouts, 429, malformed output)
- [ ] >= 1 tool-calling mechanism

Evaluation
- [ ] own automated eval, >= 40 questions: simple, multi-hop, multi-doc, unanswerable, contradictory
- [ ] retrieval + answer metrics: Recall@K, MRR, Answer Correctness, Citation Accuracy
- [ ] >= 2 configurations compared
- [ ] error analysis: where it fails, why, how to improve

Backend / UI
- [ ] Python backend, functional UI: upload/manage docs, ask, inspect sources

Dataset
- [ ] >= 50,000 documents/records, reproducible subset with justification
- [ ] cross-document linking, source identity preserved, incomplete/contradictory data, repeatable eval

Deployment
- [ ] public URL on free tier, DB integrated, data survives restart
- [ ] secrets protected, deployment architecture + free-tier limits documented

Quality
- [ ] modular code, error handling, automated tests, safe config, docs, perf + LLM cost notes

Bonus (only after core): LLM/embedding comparison, agentic RAG, reranker, prompt-injection tests,
caching, streaming, observability, load test.

## 2. Key decisions

Free service options per role (not final): [docs/SERVICES.md](docs/SERVICES.md).

| Area | Choice | Why / trade-off |
|---|---|---|
| Corpus (bulk) | HotpotQA `distractor` validation split (7,405 questions x 10 paragraphs), dedup by title+text | Gold supporting facts give free Recall@K/MRR/citation labels. Many paragraphs repeat across questions: dedup is real, not cosmetic. **Verify unique count >= 50k in phase 0**; if short, add part of `train`. |
| Corpus (investigation) | Synthetic "Acme Payments" org: ~150-300 docs (incident reports PDF, change logs MD, runbooks DOCX, status pages HTML) generated once, committed | Matches the task's example question (March payment outage). Planted contradictions (two reports disagree on root cause/time) and gaps (unanswerable). HotpotQA has neither. |
| Corpus (real, optional) | danluu/post-mortems README entries as records | Real incident flavor; cheap to parse. Skip if time is short. |
| Vector DB | AWS RDS Postgres 17 (`db.t4g.micro`, 20 GB gp3) + pgvector (`halfvec`) + built-in full-text search | One store for docs, chunks, vectors, keyword index, CRUD, dedup hashes, LLM cache; SQL is easy to defend. Publicly accessible with forced TLS (see Deployment for why). Local dev on `pgvector/pgvector:pg17` in Docker, same schema. Fallback: Neon free (same schema, `pg_dump`). |
| Embeddings | `fastembed` + `BAAI/bge-small-en-v1.5` (384d, ONNX, CPU) | Free, no rate limits, no torch. Bulk embedding done locally, query embedding inside the Lambda (model baked into the container image, loaded once per cold start). Bonus comparison: `e5-small` or Gemini embeddings on the eval subset. |
| Keyword search | Postgres `tsvector` + `ts_rank_cd` | Native, indexed. |
| Own algorithm | Reciprocal Rank Fusion (dense + keyword) + MMR diversification with per-document cap, written by hand | Small, testable, easy to explain on a whiteboard. Optional: own BM25 scorer to compare with `ts_rank_cd`. |
| LLM | Groq (`openai/gpt-oss-120b` main, smaller model for planning/judge), Amazon Bedrock (Nova Lite, from credits) as fallback | Free, fast, tool calling. Free limits (~8k tokens/min, ~1k req/day per model) are the real bottleneck: LLM calls cached in a Postgres table by prompt hash (Lambda has no persistent disk), eval spread across days/models. |
| Orchestration | Own agent loop with tool calling: `search`, `get_document`, `final_answer` (JSON schema) | Satisfies tool calling + multi-step + agentic bonus. Hard step cap (e.g. 6), token budget per question. |
| Grounding | Structured answer `{claims:[{text, citations:[chunk_id]}], contradictions:[], status: answered/insufficient/conflicting}`; server drops claims citing chunks that were never retrieved | Mechanical anti-hallucination check, not only prompt wording. |
| Backend | AWS Lambda (Python 3.12 container image) behind a Lambda Function URL; hand-written router over the event, no web framework | Pay per request, always-free tier (1M req, 400k GB-s/month) covers the demo. Function URL instead of API Gateway: API Gateway cuts requests at 30 s, the agent loop can take longer (Function URL allows up to 15 min). Trade-off: no SSE streaming in Python Lambda, the trace comes back with the final answer. |
| UI | One static HTML page + vanilla JS, served by the same `api` Lambda at `GET /` | Same origin as the API: no CORS, no CloudFront, HTTPS from the Function URL. |
| Uploads | Browser gets a presigned S3 URL, uploads directly; S3 event triggers the `ingest` Lambda | Lambda payload limit is 6 MB; ingestion runs async with its own timeout. S3 keeps originals for re-ingestion. |
| IaC | AWS SAM (`template.yaml`) | All infra in one reviewable file, `sam deploy` from the laptop. Less code than CDK, native for Lambda. |
| Secrets | SSM Parameter Store `SecureString` (free tier), read once per cold start | Not in code, not in the image, not in plain Lambda env vars. |
| Region | `eu-central-1` (Frankfurt) | Closest to Tbilisi. |
| Tooling | Python 3.12, uv, ruff, pytest, Docker, AWS CLI, SAM CLI | |

## 3. Architecture

```
upload / bulk loader
   -> parse (pdf: pypdf, docx: python-docx, html: bs4/stdlib, md/jsonl: stdlib)
   -> normalize + sha256 -> dedup (exact) -> chunk (strategy A|B)
   -> embed (fastembed) -> Postgres: documents, chunks(text, tsv, embedding halfvec)

question
   -> agent loop (LLM + tools)
        plan sub-questions -> search(q) = dense top-k + keyword top-k -> RRF -> MMR
        -> get_document(id) when context is needed -> repeat <= N steps
   -> final_answer JSON -> citation validator -> answer | insufficient | conflicting
   -> UI: answer, claims with clickable chunk sources, contradictions, trace of steps
```

Schema (sketch): `documents(id, source, title, doc_type, created_at, content_hash, version, metadata jsonb)`,
`chunks(id, document_id, ord, text, tsv, embedding halfvec(384), strategy)`,
`llm_cache(prompt_hash, model, response jsonb, created_at)`.
Update = new version replaces chunks in one transaction; delete cascades.

### Deployment (AWS, eu-central-1)

```
browser ──HTTPS──> Lambda Function URL ──> api Lambda (container image)
   │                                         GET  /                 -> index.html
   │                                         GET  /documents        POST /documents/upload-url
   │                                         DELETE /documents/{id} GET  /chunks/{id}
   │                                         POST /ask  (agent loop, timeout 90 s)
   │                                             │  └──HTTPS──> Groq API (fallback: Bedrock)
   │                                             └──TLS──> RDS Postgres + pgvector
   └──PUT (presigned)──> S3 bucket uploads/ ──event──> ingest Lambda (same image, timeout 5 min)
                                                         parse -> dedup -> chunk -> embed -> RDS

laptop: scripts/bulk_load.py (HotpotQA, fastembed) ──TLS──> RDS     eval runner ──> engine.ask() in-process
SSM Parameter Store: DB URL, Groq key      CloudWatch Logs: JSON logs per request      AWS Budgets: alert at $10
```

- One container image, two functions (`api`, `ingest`): same code, different handler.
- **Lambdas run outside the VPC, RDS is publicly accessible.** A Lambda inside a VPC needs a
  NAT Gateway (~$32/month) to reach Groq. Mitigations: `rds.force_ssl=1`, long random password
  in SSM, dedicated DB user with no superuser rights, reserved concurrency 5 on `api` (caps DB
  connections and runaway cost). Production path, written in README: VPC + RDS Proxy + NAT or
  VPC endpoints, IAM DB auth.
- Bulk load and eval run from the laptop: no Lambda timeouts, no payload limits, LLM cache shared via RDS.
- Cost estimate: RDS ~$15 + storage ~$2.5 + public IPv4 ~$3.6 = ~$21/month; Lambda, S3, SSM,
  CloudWatch within free tier; ECR ~$0.1. Credits ($100 + up to $100 from onboarding tasks)
  cover ~5-9 months. Stop the RDS instance when not needed (auto-restarts after 7 days).

## 4. Evaluation design

Question set (`eval/questions.jsonl`, >= 40, target 60):
- 20 HotpotQA bridge + comparison (gold supporting titles/sentences)
- 15 Acme multi-doc investigation questions (gold doc ids written by hand)
- 10 unanswerable (Acme + HotpotQA questions with gold paragraphs removed from the index)
- 10 contradictory (planted conflicts in Acme)
- 5 simple single-hop

Metrics:
- Retrieval: Recall@5/10, MRR (vs gold doc ids)
- Answer: EM/F1 for HotpotQA, LLM-as-judge correctness (different model than generator) for the rest
- Citation accuracy: share of cited chunks that belong to gold docs; share of claims with >= 1 valid citation
- Abstention: precision/recall of `insufficient` on unanswerable set
- Contradiction: detection rate on contradictory set
- Cost/latency: tokens and seconds per question

Configurations compared:
1. chunking A (fixed 300 tokens, 50 overlap) vs B (structure-aware: headings/paragraphs, size cap)
2. dense only vs hybrid RRF vs hybrid RRF + MMR
3. single-shot RAG vs agent loop

Output: `eval/results/<config>.json` + generated `EVALUATION.md` table and a failure analysis section.

## 5. Schedule

**Deadline: 2026-10-29 18:00 (Tbilisi).** Full scope below is ~12 days; 5 are available, so the
schedule is compressed and scope is cut (see "Cuts"). Code freeze 2026-10-29 15:00.

| Day | Date | Work | Done when |
|---|---|---|---|
| 1 | 10-24/25 | Phases 0, 1, 3 + infra: repo, local Docker Postgres, AWS account + budget + SAM skeleton with RDS, HotpotQA subset, parsers, 2 chunkers, dedup, bulk embed + load, hybrid search with RRF + MMR | `search("...")` returns fused results over >= 50k records |
| 2 | 10-26 | Phase 4 + start 2: LLM client (retry/backoff/fallback/cache), agent loop, JSON answer, citation validator; kick off Acme generation | CLI answers a HotpotQA multi-hop question with valid citations |
| 3 | 10-27 | Phases 2, 5, 7: Acme corpus finished, Lambda router + HTML UI, deploy real code to AWS (infra already up from day 1), persistence check | public URL answers a question end to end |
| 4 | 10-28 | Phase 6: 40-45 questions, runner, metrics, config sweep (cached LLM calls) | `eval/results/*.json` for all configs |
| 5 | 10-29 | Phase 8: EVALUATION.md with failure analysis, README, AI_USAGE.md, buffer, defense rehearsal | submitted before 18:00 |

### Parallel workstreams

Streams talk only through `src/engine/models.py` (`ParsedDoc`, `Hit`, `Answer`) and these functions:

```python
parse(path) -> ParsedDoc                       # C
search(query: str, k: int = 10) -> list[Hit]   # A
get_document(document_id: int) -> ParsedDoc    # A
ask(question: str) -> Answer                   # B
```

Until a function exists, consumers use a stub returning fixed data. Each stream lives in its own
branch/worktree and merges to `main` when its tests pass.

| Stream | Scope | Modules | Depends on | Start |
|---|---|---|---|---|
| A. Data + search | HotpotQA subset, schema, dedup, 2 chunkers, bulk embed, load, dense + keyword, RRF + MMR, CRUD | `data/`, `db.py`, `chunking.py`, `index.py`, `search.py` | local Docker Postgres (RDS for the final load) | day 1 |
| B. LLM + agent | Groq client (retry/backoff/timeout/fallback/cache), tools, agent loop, JSON answer, citation validator | `llm.py`, `agent.py` | stub `search` | day 1 |
| C. Acme corpus + parsers | generator, planted contradictions/gaps, `GROUND_TRUTH.md`, PDF/DOCX/HTML/MD parsers | `parsers.py`, `scripts/gen_acme.py`, `data/acme/` | Groq key | day 1 |
| D. Infra + API + UI | AWS account, budget alert, SAM template (RDS, S3, 2 Lambdas, Function URL, SSM), Lambda router, HTML page, Dockerfile, persistence check | `handlers.py`, `static/`, `Dockerfile`, `template.yaml` | stubs `ask`/`search` | day 1 (infra), day 2 (API/UI) |
| E. Evaluation | questions, Recall@K/MRR/citation metrics (pure functions), runner, config sweep, EVALUATION.md | `eval/` | real `ask` for runs only | day 2 |

Merge points: A+B on day 2 (real search inside the agent); C into A on day 3 (Acme indexed);
D deploys with real A+B on day 3; E runs the sweep on day 4.
Groq limits are shared: C (generation) and E (runs) must not run at the same time as heavy B testing.

Cuts (in order of what goes first if behind):
- danluu/post-mortems corpus — dropped.
- Acme corpus: ~60-100 docs instead of 150-300.
- Question set: 40-45 instead of 60.
- Config comparison: chunking A vs B and dense vs hybrid are mandatory; single-shot vs agent only if time allows.
- Bonuses: none planned (streaming dropped: not supported by Python Lambda Function URLs). Everything else is listed as "future work" in the README.

Reference phases (original estimates):

0. **Setup + data check (0.5 d)** — repo, uv project, local Docker Postgres, AWS account + budget alert, Groq key. Download HotpotQA, count unique paragraphs, decide subset size. Commit subset script with fixed seed.
1. **Ingestion (2 d)** — parsers for 4 formats, metadata, hashing/dedup, two chunkers, CRUD on documents. Tests on small fixtures.
2. **Synthetic Acme corpus (1 d)** — generator script (LLM once, outputs committed), planted contradictions and gaps listed in `data/acme/GROUND_TRUTH.md`.
3. **Index + search (1.5 d)** — bulk embed locally, load into Postgres (local, then RDS), dense + keyword queries, RRF + MMR, unit tests for fusion.
4. **Agent + grounding (2 d)** — LLM client (retries, backoff on 429, timeout, fallback model, cache), tools, loop, JSON answer, citation validator, abstain/conflict statuses.
5. **API + UI (1 d)** — `POST /documents/upload-url`, `PUT/DELETE /documents/{id}`, `GET /documents`, `POST /ask`, `GET /chunks/{id}`; single HTML page; Lambda router.
6. **Evaluation (2 d)** — question set, runner, metrics, config sweep, EVALUATION.md with failure analysis.
7. **Deploy (1 d)** — Dockerfile, SAM template (RDS, S3, Lambdas, Function URL, SSM), budget alert, persistence check (redeploy, data still there), DEPLOYMENT section with limits and cost.
8. **Docs + defense prep (1 d)** — README, AI_USAGE.md, rehearse: walk the pipeline, rewrite RRF/MMR by hand, add a small feature without AI.

Core total ~12 days. Bonus only after phase 8: next best value is
prompt-injection tests (plant malicious text in a doc) and embedding-model comparison.

## 6. Risks

- **Groq free limits** stall eval runs. Mitigation: cache, smaller model for judge/planning, run configs on different days, keep agent step cap low.
- **RDS storage/RAM** (20 GB disk is plenty; 1 GB RAM limits HNSW build and `shared_buffers`). Mitigation: `halfvec`, build HNSW once after bulk load with raised `maintenance_work_mem`, measure query latency early in phase 3.
- **HotpotQA chunking comparison is weak** (paragraphs already short). Compare chunkers on Acme + post-mortems, say so in the report.
- **LLM-as-judge bias**. Use a different model than the generator, spot-check 10 answers by hand, report agreement.
- **Defense without AI**. Keep code small and own; no framework magic you cannot rewrite on paper.
- **Lambda cold start** (container pull + ONNX model load, ~3-6 s). Model baked into the image, loaded at module level; document first-request latency. Provisioned concurrency costs money, not used.
- **Public RDS endpoint.** Accepted for the demo to avoid NAT cost; mitigations and production path in Deployment.
- **AWS credits / free plan expiry.** Budget alert at $10; account closes when credits run out or after 6 months unless upgraded; the demo must live until the interview.
- **Infra eats coding time.** SAM template written on day 1 in parallel with A/B/C; deploy a hello-world Lambda + RDS first, real code later.
