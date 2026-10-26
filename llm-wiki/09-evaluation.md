---
title: Evaluation
status: current
last_updated: 2026-10-25
owner: Pro100Sergosha
---

# 09 Evaluation

The question set, the metrics, the configurations and how a run works. Why it is built this way:
[ADR 0027](adr/0027-eval-runner-retrieval-sweep-qwen-judge.md). Metric functions:
`eval/metrics.py`; the runner: `eval/run.py`. No results yet: the first runs come after the agent
merges (PLAN.md section 0).

## Question set

One JSON object per line, the same format in both files:

```json
{"id": "hp-5adf8c375542995534e8c7dd", "question": "...", "type": "multi_hop",
 "answer": "1972", "gold_sources": ["hotpotqa:1965 World Series", "hotpotqa:Sandy Koufax"]}
```

- `type`: `simple | multi_hop | multi_doc | unanswerable | contradictory`.
- `gold_sources`: document sources as stored (`hotpotqa:<title>`, `upload:acme-....pdf`), not
  database ids (they change on every reload). Empty exactly when the type is `unanswerable`.
- `answer`: the short gold answer; `null` for `unanswerable` (and allowed for a `contradictory`
  question that has no single answer).

The runner reads `eval/questions.jsonl` and, if it exists, `data/acme/questions.jsonl` (written by
the Acme stream). Every line is validated (fields present, unique ids across both files, known
type, the gold rules above); a bad line stops the run with `file:line: problem` before any call.

`eval/questions.jsonl` (committed, fixed): 30 HotpotQA questions.

| type | count | how chosen |
|---|---|---|
| `multi_hop` | 20 (14 bridge, 6 comparison) | from the dataset job's labels `s3://<bucket>/jobs/dataset/questions.jsonl` (7,405 questions): sort by `sha256(_id)` hex, take the first 14 `bridge` and the first 6 `comparison` (~ the 80/20 split of the dev set, a bit more comparison). Every dev-distractor question is `level: hard`, so there is no level mix to choose. Text, answer and supporting titles are copied verbatim; id `hp-<_id>` |
| `simple` | 5 (`hp-simple-1..5`) | written by hand: one fact from one paragraph, the paragraph's source is the gold |
| `unanswerable` | 5 (`hp-unanswerable-1..5`) | written by hand: about an entity that has a paragraph in the corpus, asking a fact that paragraph does not contain (cost, price, birthplace, length) |

For the 10 hand-written questions the entities were checked against the HotpotQA dev file (the
same bytes as the corpus, SHA256 checked): each name (and the other names a question uses, e.g.
"MBK Northwest", "Zalman King") appears in exactly one paragraph, its own. So a simple question
has exactly one gold document, and an unanswerable one cannot be answered from another paragraph
either.

HotpotQA labels are kept as they are, including their noise: `hp-5a7e36815542995ed0d166d4` asks
about WrestleMania IX but its gold paragraph is WrestleMania XXIV; `hp-5a8ae0ae55429950cd6afbc2`
has the answer "AeroflotRussian Airlines". EM undercounts on such rows; the judge sees the gold
answer too. Failure analysis should call them out rather than fix them.

The Acme file adds `multi_doc`, `contradictory` and Acme `unanswerable` questions (PLAN.md
section 4); the runner needs no change for it.

## Metrics

Per question, then averaged per run. A mean skips `None` (not applicable); errors are counted and
left out of every score.

| Metric | How | Over |
|---|---|---|
| Recall@5, Recall@10 | `metrics.recall_at_k` on the sources of the first 5 / 10 chunk hits (a document hit twice takes two positions) vs `gold_sources` | answerable questions, retrieval run |
| MRR | mean of `metrics.reciprocal_rank` on the same list | same |
| EM, F1 | `metrics.exact_match` / `f1` of `Answer.answer` (the short answer) vs `answer` | ids starting `hp-` with a gold answer |
| Judge correctness | Qwen3-235B (`llm.QWEN`) gets question, gold answer, system answer and claims, replies `{"correct": bool, "reason": ...}`; the JSON object is taken from the first `{` to the last `}`. An `insufficient` answer to an answerable question is `false` without a call. A failed call or unreadable reply is `None` and counted in `judge_failures` | questions with a gold answer |
| Citation precision | `metrics.citation_precision`: distinct sources of the cited chunks (claims and contradictions, mapped with `search.get_chunks`) that are gold; `None` when nothing is cited | answerable questions |
| Abstention P/R | `metrics.abstention_precision_recall`: predicted = status `insufficient`, actual = type `unanswerable` | the whole run |
| Contradiction P/R | `metrics.contradiction_precision_recall`: predicted = status `conflicting`, actual = type `contradictory` | the whole run |
| Cost, tokens, latency | tokens from the trace's `"step": "llm"` entries; cost from uncached calls only, EU prices per 1M in/out: Haiku $1.10/$5.50, gpt-oss $0.15/$0.60, Qwen $0.22/$0.88 (judge included); p50/p95 of seconds per `ask` (nearest rank) | answer runs |
| Fallback share | share of answers with any LLM step not answered by Haiku | answer runs |

Every metric is also reported per question type (`by_type`).

## Configurations

`python -m eval.run --config NAME [--limit N] --bucket B`. Names are the contract with PLAN.md
section 4.

| `CONFIG` | What | LLM |
|---|---|---|
| `retrieval` | every answerable question through `search.search(q, k=10, strategy, mode)` for strategy `fixed`, `structured` x mode `dense`, `hybrid`, `mmr`: the chunking A vs B and dense vs hybrid vs MMR comparisons | none (one Cohere query embedding per question: `embed_query` is memoized) |
| `agent` | `agent.ask(q)`: structured chunks, mmr, 6 steps | Haiku + judge |
| `agent-fixed` | the same with fixed chunks | Haiku + judge |
| `single-shot` | `max_steps=1`: one search, one forced answer (RAG without the loop) | Haiku + judge |

## Running

In CodeBuild, never on the laptop ([ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md)). The
whole value is one `TARGET` (the buildspec splits it into a target and variables):

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override "name=TARGET,value=eval CONFIG=agent LIMIT=3"
# full runs: value=eval CONFIG=retrieval | agent | agent-fixed | single-shot
```

Do not run an eval while a bulk load or the Acme generation runs: they share the Cohere and Haiku
quotas (PLAN.md section 5). The retrieval run needs the full Cohere-embedded corpus.

Outputs: `eval/results/<config>.json` in the build and `s3://$BUCKET/jobs/eval/<config>.json`
(`<config>-limit<N>.json` for a dry run, so it never overwrites a full run): `{config, settings,
question_counts, summary, records}`. Records keep the answer, claims with their sources, cited
sources, models and call counts, tokens, cost, seconds and every metric; retrieval records keep
the ranked sources per strategy/mode. The build log ends with the summary as Markdown tables.
Results are downloaded from S3 and committed through a PR (ADR 0018).

## Pacing and cost

Haiku allows 10 requests/min per profile. After each question the runner sleeps
`max(0, 6 s x uncached Haiku calls - elapsed)`, so a run never bursts past the quota and
`llm.py` does not silently fall back to gpt-oss. Both Haiku profiles (`eu.*`, `global.*`,
ADR 0028) count as Haiku for pacing and the fallback share; `global.*` is priced at
$1.00/$5.00 per 1M. After an `ask` that raised, it assumes
`max_steps` calls. Cached calls are free and unpaced; the judge (Qwen, 100 requests/min) is not
paced.

Estimates for the 30 HotpotQA questions (25 answerable), before the Acme questions are added
(roughly double with them):

| `CONFIG` | Time | Cost |
|---|---|---|
| `retrieval` | ~3-5 min (25 embeddings, 150 searches) | ~$0 (Cohere, a few thousand tokens) |
| `agent`, `agent-fixed` | ~10-20 min (3-6 Haiku calls per question at 6 s) | ~$0.5-1 (~$0.02-0.035 per question) |
| `single-shot` | ~3-4 min | ~$0.15 |
| judge | in the runs above | ~$0.0001 per question (~250 tokens, measured) |

A rerun of the same configuration with the same prompts is served by `llm_cache`: free and fast.
CodeBuild adds ~1-2 min of setup per build.

## Known limits

- **Judge bias.** One model's opinion; Qwen3 is from a different family than the Claude
  generator, which removes self-preference but not leniency. Spot-check ~10 verdicts by hand and
  report agreement in EVALUATION.md. Measured once (2026-10-25): "Joseph L. Mankiewicz" against
  gold "Joseph Leo Mankiewicz" -> `{"correct": true, ...}`, a clean JSON object, 197 in / 36 out.
- **HotpotQA chunking comparison is weak.** Paragraphs average 532 characters, so both chunkers
  mostly keep a paragraph whole; the chunking comparison is meaningful on Acme.
- **Small set.** 25 answerable HotpotQA questions: one question moves Recall by 0.04. Differences
  below ~0.1 are noise.
- **Recall depends on the dense candidate list** (`hnsw.ef_search` 40, 14 Known gaps).
- **EM is strict** on HotpotQA's long or noisy gold answers; read it together with F1 and the
  judge.
