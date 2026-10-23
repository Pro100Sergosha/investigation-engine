# AI Investigation Engine — MVP plan

Source: Upgaming Talent Growth Program, "Applied AI – AI Investigation Engine Task" (PDF, Georgian).
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

| Area | Choice | Why / trade-off |
|---|---|---|
| Corpus (bulk) | HotpotQA `distractor` validation split (7,405 questions x 10 paragraphs), dedup by title+text | Gold supporting facts give free Recall@K/MRR/citation labels. Many paragraphs repeat across questions: dedup is real, not cosmetic. **Verify unique count >= 50k in phase 0**; if short, add part of `train`. |
| Corpus (investigation) | Synthetic "Acme Payments" org: ~150-300 docs (incident reports PDF, change logs MD, runbooks DOCX, status pages HTML) generated once, committed | Matches the task's example question (March payment outage). Planted contradictions (two reports disagree on root cause/time) and gaps (unanswerable). HotpotQA has neither. |
| Corpus (real, optional) | danluu/post-mortems README entries as records | Real incident flavor; cheap to parse. Skip if time is short. |
| Vector DB | Neon Postgres + pgvector (`halfvec`) + built-in full-text search | One store for docs, chunks, vectors, keyword index, CRUD and dedup hashes; SQL is easy to defend. Free 0.5 GB: ~60k chunks x ~4.5 KB ~ 270 MB, `halfvec` halves vector size. Fallback: Supabase (same schema) or Qdrant Cloud 1 GB. |
| Embeddings | `fastembed` + `BAAI/bge-small-en-v1.5` (384d, ONNX, CPU) | Free, no rate limits, no torch. Bulk embedding done locally, query embedding on server. Bonus comparison: `e5-small` or Gemini embeddings on the eval subset. |
| Keyword search | Postgres `tsvector` + `ts_rank_cd` | Native, indexed. |
| Own algorithm | Reciprocal Rank Fusion (dense + keyword) + MMR diversification with per-document cap, written by hand | Small, testable, easy to explain on a whiteboard. Optional: own BM25 scorer to compare with `ts_rank_cd`. |
| LLM | Groq (`openai/gpt-oss-120b` main, smaller model for planning/judge), Gemini as fallback | Free, fast, tool calling. Free limits (~8k tokens/min, ~1k req/day per model) are the real bottleneck: disk cache of LLM calls by prompt hash, eval spread across days/models. |
| Orchestration | Own agent loop with tool calling: `search`, `get_document`, `final_answer` (JSON schema) | Satisfies tool calling + multi-step + agentic bonus. Hard step cap (e.g. 6), token budget per question. |
| Grounding | Structured answer `{claims:[{text, citations:[chunk_id]}], contradictions:[], status: answered/insufficient/conflicting}`; server drops claims citing chunks that were never retrieved | Mechanical anti-hallucination check, not only prompt wording. |
| Backend | FastAPI | Async, OpenAPI docs for free, SSE streaming. |
| UI | One static HTML page + vanilla JS served by FastAPI | Task values function over design; no second process, nothing to build. |
| Hosting | Hugging Face Spaces (Docker, free CPU, 16 GB RAM) | RAM for the embedding model; secrets via Space secrets. Sleeps after 48 h idle (documented). Render free (512 MB) too tight. Oracle VM possible but shared with Minecraft + kb-agent. |
| Tooling | Python 3.12, uv, ruff, pytest | |

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
`chunks(id, document_id, ord, text, tsv, embedding halfvec(384), strategy)`.
Update = new version replaces chunks in one transaction; delete cascades.

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

## 5. Phases

Deadline unknown — estimates in focused working days.

0. **Setup + data check (0.5 d)** — repo, uv project, Neon project, Groq key. Download HotpotQA, count unique paragraphs, decide subset size. Commit subset script with fixed seed.
1. **Ingestion (2 d)** — parsers for 4 formats, metadata, hashing/dedup, two chunkers, CRUD on documents. Tests on small fixtures.
2. **Synthetic Acme corpus (1 d)** — generator script (LLM once, outputs committed), planted contradictions and gaps listed in `data/acme/GROUND_TRUTH.md`.
3. **Index + search (1.5 d)** — bulk embed locally, load into Neon, dense + keyword queries, RRF + MMR, unit tests for fusion.
4. **Agent + grounding (2 d)** — LLM client (retries, backoff on 429, timeout, fallback model, cache), tools, loop, JSON answer, citation validator, abstain/conflict statuses.
5. **API + UI (1 d)** — `POST/PUT/DELETE /documents`, `GET /documents`, `POST /ask` (SSE), `GET /chunks/{id}`; single HTML page.
6. **Evaluation (2 d)** — question set, runner, metrics, config sweep, EVALUATION.md with failure analysis.
7. **Deploy (1 d)** — Dockerfile, HF Space, secrets, persistence check (restart, data still there), DEPLOYMENT section with free-tier limits.
8. **Docs + defense prep (1 d)** — README, AI_USAGE.md, rehearse: walk the pipeline, rewrite RRF/MMR by hand, add a small feature without AI.

Core total ~12 days. Bonus only after phase 8: streaming is already in phase 5; next best value is
prompt-injection tests (plant malicious text in a doc) and embedding-model comparison.

## 6. Risks

- **Groq free limits** stall eval runs. Mitigation: cache, smaller model for judge/planning, run configs on different days, keep agent step cap low.
- **Neon 0.5 GB** fills with 60k chunks + HNSW. Mitigation: `halfvec`, measure early in phase 3, trim payload, fallback Qdrant.
- **HotpotQA chunking comparison is weak** (paragraphs already short). Compare chunkers on Acme + post-mortems, say so in the report.
- **LLM-as-judge bias**. Use a different model than the generator, spot-check 10 answers by hand, report agreement.
- **Defense without AI**. Keep code small and own; no framework magic you cannot rewrite on paper.
- **HF Space cold start** (model load + Neon wake-up). Warm-up on startup, document expected first-request latency.
