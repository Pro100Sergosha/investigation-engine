---
title: Model and embedding comparison by the eval; keep 1024 dimensions, no Bedrock reranker
status: accepted
date: 2026-10-27
supersedes: none
superseded_by: none
---

# ADR 0032: Model and embedding comparison by the eval; keep 1024 dimensions, no Bedrock reranker

## Context

The task's bonus list asks for a comparison of LLMs or embedding models and for more advanced
re-ranking (PLAN.md section 1, "6. Bonus"). Neither was measured: Titan was replaced by Cohere
Embed V4 for throughput (ADR 0022), not compared on quality, and ranking ends at our own weighted
RRF + MMR (ADR 0029). The budget for this work was at most $4 of Bedrock credit, and nothing may
change prod tables (no new columns or indexes) or run on the laptop (ADR 0018).

Three questions, each answered with the existing eval runner (ADR 0027) on the same 72 questions:
1. **LLM.** Is gpt-oss-120b, already in `llm.py` as the last fallback and ~7x cheaper per token
   than Haiku, good enough to answer instead of Haiku?
2. **Embedding size.** Cohere Embed V4 offers 256, 512, 1024 and 1536 dimensions. Would a smaller
   vector (half the storage and index size) lose recall?
3. **Reranker.** Can a Bedrock rerank model (Cohere Rerank 3.5, Amazon Rerank 1.0) be added after
   RRF/MMR?

Facts checked on 2026-10-26:
- **Matryoshka.** Cohere's Embed v4 changelog lists "Matryoshka Embeddings in the following
  dimensions: [256, 512, 1024, 1536]"; the Bedrock parameter page lists the same
  `output_dimension` values but says nothing about truncation. Neither page says in so many words
  that the first 512 numbers of a 1024 vector *are* the 512 vector, so the eval measures it: for
  every eval question it asks Cohere for the 512 and 256 query embeddings and compares them with
  the cut 1024 one. Mean cosine 1.0000 for both, minimum 0.9998 (512) and 0.9996 (256), over 61
  questions. Cutting a stored vector is therefore the same as embedding at the smaller size.
- **Rerank models.** `aws bedrock list-foundation-models --region eu-north-1` lists no rerank
  model, and `list-inference-profiles` has no `eu.*` or `global.*` profile for one. Both
  `cohere.rerank-v3-5:0` and `amazon.rerank-v1:0` are listed in eu-central-1 and us-west-2 only.

## Decision

1. **Two eval configurations, no new abstraction.** `agent.ask` takes `model` (default
   `llm.HAIKU`); the eval config `agent-gpt-oss` is `agent` with `model=llm.GPT_OSS`. In
   `llm.converse` gpt-oss has no fallback, its answers go to `llm_cache` under their own key, and
   the runner counts a call by another model than the configuration's as a fallback. The config
   `embeddings` (no LLM) runs exact dense search on fixed chunks with the first 1024 / 512 / 256
   numbers of the stored vectors (`search.dense_prefix`, `subvector()` in SQL) and the same cut of
   one 1024 query embedding. Production search is unchanged.
2. **Keep 1024 dimensions.** Exact search, 61 answerable questions:

   | vectors | Recall@5 | Recall@10 | MRR | HotpotQA R@10 | Acme R@10 | scan p50 |
   |---|---|---|---|---|---|---|
   | 1024, HNSW (production `fixed/dense`) | 0.80 | 0.89 | 0.86 | 0.86 | 0.91 | - |
   | 1024, exact | 0.81 | 0.92 | 0.88 | 0.90 | 0.94 | 0.62 s |
   | 512, exact | 0.81 | 0.89 | 0.87 | 0.90 | 0.88 | 0.56 s |
   | 256, exact | 0.82 | 0.88 | 0.85 | 0.90 | 0.87 | 0.53 s |

   512 loses 0.03 Recall@10 against exact 1024, all of it on Acme (0.94 -> 0.88; HotpotQA is
   equal), which is the corpus the investigation questions are about. Three questions lose gold
   documents: `acme-004` and `acme-027` one of two, `acme-029` both (the two sides of a planted
   contradiction). Storage is not a
   constraint (Aurora storage is cents), so the smaller vector buys nothing we need.
3. **Haiku stays the answering model; gpt-oss-120b stays the last fallback (ADR 0028).** Full
   runs, 72 questions each, same prompt and settings:

   | model | judge | citation P | abstain P/R | conflict P/R | per question | p50/p95 s |
   |---|---|---|---|---|---|---|
   | Haiku 4.5 (`agent`) | 0.82 | 0.94 | 0.77/0.91 | 1.00/0.67 | ~$0.016 | 10.3/45.6 |
   | gpt-oss-120b (`agent-gpt-oss`) | 0.89 | 0.93 | 0.75/0.82 | 0.92/0.92 | ~$0.0024 | 3.4/10.3 |

   gpt-oss wins clearly on cost (~7x), latency and contradictions (11 vs 7 of 12). On the other
   answerable questions it is a tie (50 vs 51 once Haiku's two Bedrock-error abstentions and one
   flipped judge verdict are set aside), and it answered one unanswerable question (`acme-034`)
   with a cause no document states. The system is judged on abstaining rather than guessing, the
   prompt was tuned for Haiku, and one run per model is all the cache allows (a rerun replays
   `llm_cache`). So the default does not change two days before the code freeze.
4. **No reranker.** The only Bedrock rerank models are in eu-central-1 and us-west-2 with no
   cross-Region profile. Calling them would be a direct cross-Region call, which CLAUDE.md forbids
   (one Region; only the existing `eu.*`/`global.*` inference profiles). Nothing is built.

## Consequences

- The bonus "compare LLMs or embedding models" is measured with the same runner, questions and
  judge as everything else, for well under $1: the embedding run makes ~180 Cohere query calls
  (a few thousand tokens) and ~180 exact scans (~0.6 s each, a few ACU-minutes); the full
  gpt-oss run cost $0.17 with the judge (~$0.0024 per question against ~$0.016 for Haiku).
- Keeping Haiku keeps its costs: ~7x the price per question, the 10 requests/min quota that
  paces every eval, and the `eu.*` outages of ADR 0028. Switching later is one argument
  (`agent.ask(model=...)` in `handlers.py`); what would justify it: the contradiction gain and the
  abstention behaviour confirmed on questions the prompt was not tuned on.
- A side result: the HNSW index loses 0.03 Recall@10 against exact search at the same 1024
  dimensions (0.89 vs 0.92). `acme-004` is the clearest case: exact search finds both gold
  documents, HNSW none (the partial index and `hnsw.ef_search` = 40 return HotpotQA paragraphs
  first). Raising `ef_search` (or `iterative_scan`) is the cheap fix; it is not part of this
  change (14 Known gaps).
- `search.dense_prefix` is eval-only code in a production module: a full scan of every chunk of a
  strategy, ~0.6 s per query on the deployed cluster. Nothing in the api calls it.
- The `embeddings` config measures dense search only; hybrid and MMR at 512 dimensions were not
  run, and 1536 cannot be measured without re-embedding (the stored vectors have 1024).
- Re-ranking stays our own RRF + MMR. The bonus item remains "partial".
- The comparison is on a small set that was used for tuning (EVALUATION.md 4.11, section 6): 0.03
  Recall@10 is three questions, at the edge of the noise.

## Alternatives considered

- **Re-embed the corpus at 512 dimensions.** A second `halfvec(512)` column and index, or a full
  reload: ~11M tokens (~$1.3), ~65 min of the Cohere pool, and a schema change on prod tables, to
  learn what the prefix scan shows for free. Rejected; truncation was verified to be exact.
- **A reranker in eu-central-1 through a client pinned to that Region.** Cohere Rerank 3.5 is the
  reranker a reasonable engineer would pick, at ~$2 per 1,000 queries. Rejected: it breaks the
  one-Region rule of this Free-plan project and sends query and passage text to another Region.
  Right call if AWS publishes a rerank model in eu-north-1 or an `eu.*` rerank profile: then a
  `rerank.py` after RRF, behind a config flag, measured as one more `retrieval` configuration.
- **An LLM as reranker (Haiku scoring the 40 candidates).** One more Haiku call per search against
  a 10 requests/min quota that already paces every eval; it would roughly double the agent's
  calls. Rejected for cost and quota.
- **A small cross-encoder inside the Lambda.** ADR 0016 keeps ML runtimes out of the image (cold
  starts, image size); rejected for the same reasons.
- **Make gpt-oss-120b the answering model now.** The option the numbers favour: cheaper, faster,
  in Region, better on contradictions. Rejected for the submission because of the missed
  abstention, the single run and the Haiku-tuned prompt (Decision 3); the right call once a
  held-out question set shows the same picture.
- **Compare against Titan V2.** The corpus is embedded with Cohere only; a Titan comparison needs
  a full second embedding (~18 h at Titan's throughput, ADR 0022). Rejected.
