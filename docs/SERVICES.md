# Free services — options by role

Status: **draft, not decided.** Limits below are from memory (knowledge up to mid-2026) and
are marked `verify` — check each on signup before committing to it.

Key constraint beyond raw limits: reviewers may open the demo 1-3 weeks after submission,
so **behavior after inactivity** matters as much as quotas.

## 1. Storage: documents, chunks, vectors, keyword index

| Option | Free tier (verify) | After inactivity | Notes |
|---|---|---|---|
| **Neon Postgres + pgvector** (current pick) | 0.5 GB per project, compute autosuspend | Compute sleeps, wakes on first query (~1-2 s) | One store for CRUD, dedup, `tsvector`, vectors; hybrid search in one SQL. 0.5 GB is tight: estimate 250-350 MB for ~74k chunks with `halfvec(384)` + HNSW — measure early. |
| Supabase + pgvector | 500 MB DB | **Project paused after ~7 days, manual restore** | Same schema as Neon, but pausing is a demo killer. |
| Qdrant Cloud | 1 GB cluster | Suspended after inactivity, later deleted (verify terms) | Best pure vector DB here; keyword side via sparse vectors / payload filters. Docs/CRUD need another store. |
| Pinecone Starter | ~2 GB serverless (verify) | Indexes may be paused/archived when idle (verify) | Hybrid via sparse-dense; closed source, harder to defend internals. |
| Weaviate Cloud | Sandbox cluster expires after ~14 days | Deleted | Not viable for a demo that must outlive grading. |
| Zilliz Cloud (Milvus) | Free cluster (verify size) | Suspended when idle (verify) | Alternative to Qdrant. |
| MongoDB Atlas M0 + Vector Search | 512 MB | Stays up | Vector + Atlas Search (keyword) on one free cluster; less natural for SQL-style joins. |
| Chroma (self-hosted, in the app container) | Free, local | Dies with HF Space disk | Ephemeral disk on HF Spaces = data lost on restart unless persistent storage (paid). Local dev only. |
| Postgres on own Oracle VM | Always Free VM | Stays up | Full control, no size cap, but shared with other services and adds ops work. |

## 2. Embeddings

| Option | Free tier (verify) | Notes |
|---|---|---|
| **fastembed + `BAAI/bge-small-en-v1.5`** (current pick) | Free, local CPU, 384d | No rate limits; bulk-embed 74k chunks locally (~20-40 min). Same model embeds queries on the server. |
| fastembed + `intfloat/multilingual-e5-small` / `snowflake-arctic-embed-s` | Free, local | Candidates for the bonus "embedding model comparison". |
| fastembed + `bge-base-en-v1.5` (768d) | Free, local | Better quality, 2x storage — pressure on Neon 0.5 GB. |
| sentence-transformers | Free, local | Pulls in torch: heavy Docker image. fastembed avoids it. |
| Gemini embeddings API | Free tier with RPM/RPD limits | 74k chunks will hit limits; fine for query-time or eval-subset comparison. |
| Mistral `mistral-embed` | Free experiment tier (verify) | Option for API comparison. |
| Jina embeddings API | Free token allowance on signup | One-off comparison only. |
| Voyage AI | Free token allowance (verify) | Strong retrieval models; one-off comparison. |
| Cohere embed | Trial key, rate-limited, non-commercial | Comparison only. |

## 3. LLM (generation, agent, tool calling)

| Option | Free tier (verify) | Notes |
|---|---|---|
| **Groq** (current pick, `openai/gpt-oss-120b`) | Per-model RPM/TPM/RPD limits (~1k req/day, low TPM) | Fast, tool calling. TPM is the real bottleneck for agent loops and eval. |
| Cerebras Inference | Free daily token quota (verify) | Fast; Llama / Qwen / gpt-oss models. Fallback candidate. |
| Mistral La Plateforme | Free "experiment" tier (verify) | Generous limits historically; different model family — good for judge. |
| Google Gemini API | Free tier, **daily limits cut in late 2025** (verify) | Was the planned fallback; check current RPD before relying on it. |
| OpenRouter `:free` models | ~50 req/day without credits (verify) | Many models behind one API; low daily cap. |
| GitHub Models | Free with GitHub account, low RPD | GPT/Llama/Mistral via one token; prototyping-level limits. |
| Cloudflare Workers AI | Daily free neuron allowance | Small open models; OK as last-resort fallback. |
| HF Inference Providers | Small monthly free credit | Not enough for eval runs. |
| SambaNova Cloud | Free tier (verify) | Llama models, fast. |
| NVIDIA NIM (build.nvidia.com) | Free credits on signup (verify) | Many open models; credits run out. |
| Ollama / llama.cpp on Oracle VM | Free, ARM CPU | Slow for 120B-class; small model only (judge/planner). |

LLM-as-judge: use a **different model family** than the generator (e.g. Groq gpt-oss generates, Mistral judges).

## 4. Reranker (bonus)

| Option | Free tier (verify) | Notes |
|---|---|---|
| fastembed cross-encoder (`BAAI/bge-reranker-base`, `jina-reranker-v1-tiny`) | Free, local | CPU cost per query; fine for top-20. |
| Jina Reranker API | Free token allowance | Comparison only. |
| Cohere Rerank | Trial key | Comparison only. |
| LLM-as-reranker (Groq) | Uses LLM quota | Expensive on TPM. |

## 5. Hosting (app: FastAPI + UI + query embedding)

| Option | Free tier (verify) | After inactivity | Notes |
|---|---|---|---|
| **HF Spaces, Docker, CPU basic** (current pick) | 2 vCPU, 16 GB RAM, ephemeral disk | Sleeps after 48 h, wakes on visit (~1 min cold start) | RAM fits the embedding model; Space secrets for keys. Data lives in external DB. |
| Render free web service | 512 MB RAM | Spins down after 15 min, ~1 min cold start | fastembed + onnxruntime in 512 MB is borderline. |
| Koyeb free | 512 MB RAM (verify) | Scales to zero | Same RAM problem as Render. |
| Oracle Cloud Always Free VM | ARM up to 4 OCPU / 24 GB | Always on | Most resources; shared with Minecraft + kb-agent, needs own TLS/reverse proxy. |
| Google Cloud Run | Free monthly requests/CPU-seconds | Scales to zero | Needs billing account (card) — conflicts with "no paid infrastructure" spirit. |
| Vercel (Python functions) | Hobby tier | Serverless | Function size/time limits; embedding model won't fit well. Static UI only. |
| Streamlit Community Cloud | Free, ~1 GB RAM | Sleeps after inactivity | Would force Streamlit UI and still need a separate API. |
| Fly.io / Railway | No real free tier anymore (trial credits) | — | Skip. |

## 6. Supporting services

| Role | Options (free) | Notes |
|---|---|---|
| Dataset download | HF Hub parquet (no account needed), GitHub for danluu/post-mortems | Fixed-seed subset script committed. |
| Secrets | HF Space secrets, local `.env` (gitignored) | Never commit keys. |
| CI | GitHub Actions (ruff + pytest) | Free for public repos. |
| Observability (bonus) | Langfuse Cloud Hobby, Arize Phoenix (self-hosted), Helicone free tier, or own token/latency log in DB | Own log table is enough for core; Langfuse if time allows. |
| Uptime / keep-warm (optional) | UptimeRobot / cron-job.org free pings | Can keep HF Space and Neon warm during grading window; check HF ToS. |

## 7. Current lean (to confirm)

Neon (storage) · fastembed bge-small (embeddings) · Groq (main LLM) · Mistral or Cerebras
(fallback + judge) · HF Spaces Docker (hosting) · GitHub Actions (CI).

Open questions for tomorrow:
1. Verify current free limits: Neon, Groq, Mistral, Cerebras, Gemini, HF Spaces.
2. Fallback LLM: Mistral vs Cerebras.
3. Neon size after first load — stay, trim corpus, or move vectors to Qdrant.
