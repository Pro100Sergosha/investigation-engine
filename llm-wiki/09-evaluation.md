---
title: Evaluation
status: current
last_updated: 2026-10-26
owner: Pro100Sergosha
---

# 09 Evaluation

The question set, the metrics, the configurations and how a run works. Why it is built this way:
[ADR 0027](adr/0027-eval-runner-retrieval-sweep-qwen-judge.md). Metric functions:
`eval/metrics.py`; the runner: `eval/run.py`. Results of the full runs: [Results](#results),
files in `eval/results/`.

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
| Judge correctness | Qwen3-235B (`llm.QWEN`) gets question, gold answer, the system's status, answer, claims and contradictions (a gold answer starting `conflicting:` is matched only by an answer that reports the disagreement with its values), replies `{"correct": bool, "reason": ...}`; the JSON object is taken from the first `{` to the last `}`. An `insufficient` answer to an answerable question is `false` without a call. A failed call or unreadable reply is `None` and counted in `judge_failures` | questions with a gold answer |
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
| `agent` | `agent.ask(q)`: fixed chunks, mmr, 6 steps (the defaults, [ADR 0029](adr/0029-weighted-rrf-min-max-mmr-fixed-chunks.md)) | Haiku + judge |
| `agent-structured` | the same with structured chunks | Haiku + judge |
| `single-shot` | `max_steps=1`: one search, one forced answer (RAG without the loop) | Haiku + judge |

## Running

In CodeBuild, never on the laptop ([ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md)). The
whole value is one `TARGET` (the buildspec splits it into a target and variables):

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override "name=TARGET,value=eval CONFIG=agent LIMIT=3"
# full runs: value=eval CONFIG=retrieval | agent | agent-structured | single-shot
```

A search that fails (the query-embedding client gives up within seconds when the Cohere pool
is throttled, ADR 0028) is retried twice after 20 s; only then is it recorded as an error.

The fusion weights, `k0` and MMR lambda were tuned on this question set ([ADR 0029](adr/0029-weighted-rrf-min-max-mmr-fixed-chunks.md)),
so retrieval numbers are optimistic; the ADR has the offline sweep.

Do not run an eval while a bulk load or the Acme generation runs: they share the Cohere and Haiku
quotas (PLAN.md section 5). The retrieval run needs the full Cohere-embedded corpus.

Outputs: `eval/results/<config>.json` in the build and `s3://$BUCKET/jobs/eval/<config>.json`
(`<config>-limit<N>.json` for a dry run, so it never overwrites a full run): `{config, settings,
question_counts, summary, records}`. Records keep the answer, claims with their sources, cited
sources, models and call counts, the number of searches, tokens, cost, seconds, every metric and
the agent's `trace` (searches with their chunk ids, documents read, LLM calls, reprompts, grounding
drops: what the failure analysis reads); retrieval records keep
the ranked sources per strategy/mode. The build log ends with the summary as Markdown tables.
Results are downloaded from S3 and committed through a PR (ADR 0018).

## Pacing and cost

Haiku allows 10 requests/min per profile, and every agent search embeds its query in the Cohere
pool (20 requests/min). After each question the runner sleeps
`max(0, max(6 s x uncached Haiku calls, 3 s x searches) - elapsed)`, so a run never bursts past
either quota and `llm.py` does not silently fall back to gpt-oss. The search term matters for a
rerun from the cache: with no uncached Haiku calls it would not pause at all, and on 2026-10-26
such a rerun lost six questions to Cohere `ThrottlingException` before the term was added. Both Haiku profiles (`eu.*`, `global.*`,
ADR 0028) count as Haiku for pacing and the fallback share; `global.*` is priced at
$1.00/$5.00 per 1M. After an `ask` that raised, it assumes
`max_steps` calls and searches. Cached calls are free and unpaced; the judge (Qwen, 100 requests/min) is not
paced.

Measured on the full set (72 questions, 61 answerable), first uncached runs, 2026-10-26:

| `CONFIG` | Build time | Cost (Haiku + judge) |
|---|---|---|
| `retrieval` | ~5 min | ~$0 (Cohere, a few thousand tokens) |
| `agent` | 22 min | $0.41 (~$0.006 per question) |
| `agent-structured` | 19 min | $0.56 |
| `single-shot` | 9 min | $0.37 |
| judge | in the runs above | ~$0.0001 per question (~250 tokens) |

A rerun of the same configuration with the same prompts is served by `llm_cache`: cheap and fast,
but its cost and latency columns are not the system's, and a few answers can differ: near-tied
search hits can swap places between runs, which changes the prompt and misses the cache
([ADR 0027](adr/0027-eval-runner-retrieval-sweep-qwen-judge.md) update).
CodeBuild adds ~1-2 min of setup per build.

## Results

Full runs of 2026-10-26 on the deployed system (66,619 documents: 66,555 HotpotQA + 64 Acme), 72
questions (61 answerable). Files: `eval/results/{retrieval,agent,agent-structured,single-shot}.json`.
All three answer runs: 0 errors, 0 judge failures, fallback share 0.00 (every answer from Haiku,
`eu.*` or `global.*`).

Retrieval (`retrieval`, k=10, 61 answerable questions; tuned on this set, ADR 0029):

| strategy/mode | Recall@5 | Recall@10 | MRR |
|---|---|---|---|
| fixed/dense | 0.80 | 0.89 | 0.86 |
| fixed/hybrid | 0.83 | 0.89 | 0.79 |
| fixed/mmr (agent default) | 0.82 | 0.89 | 0.79 |
| structured/dense | 0.71 | 0.81 | 0.78 |
| structured/hybrid | 0.73 | 0.81 | 0.77 |
| structured/mmr | 0.74 | 0.83 | 0.78 |

Answers:

| config | EM | F1 | judge | citation P | abstain P/R | conflict P/R | cost | p50/p95 s |
|---|---|---|---|---|---|---|---|---|
| `agent` (fixed, 6 steps) | 0.52 | 0.73 | 0.82 | 0.94 | 0.77/0.91 | 1.00/0.67 | $0.38 | 10.3/45.6 |
| `agent`, prompt of #31 | 0.48 | 0.73 | 0.74 | 0.94 | 0.77/0.91 | 0.75/0.25 | $0.41 | 13.4/40.0 |
| `agent-structured` | 0.52 | 0.73 | 0.70 | 0.93 | 0.83/0.91 | 0.80/0.33 | $0.56 | 6.7/22.8 |
| `single-shot` (1 step) | 0.32 | 0.53 | 0.62 | 0.94 | 0.48/0.91 | 0.75/0.25 | $0.37 | 5.8/11.4 |

Judge correctness by type:

| type | n | `agent` | `agent`, #31 | `agent-structured` | `single-shot` |
|---|---|---|---|---|---|
| simple | 11 | 1.00 | 1.00 | 1.00 | 1.00 |
| multi_hop | 23 | 0.78 | 0.87 | 0.74 | 0.52 |
| multi_doc | 15 | 0.93 | 0.87 | 0.93 | 0.93 |
| contradictory | 12 | 0.58 | 0.08 | 0.08 | 0.08 |

`agent` is the current prompt (one contradiction per conflict citing both sides, check every
document on the event; [ADR 0025](adr/0025-agent-loop-seeded-forced-deadline.md) update), run
uncached on 2026-10-26: `eval/results/agent.json`. `agent-structured` and `single-shot` ran with
the prompt of #31, so compare them with the "`agent`, prompt of #31" row (its file is
`eval/results/agent.json` at commit `5cfbd5d`). That row's quality columns come from a rerun
mostly served by `llm_cache`; its cost and latency from the first, uncached run, during the
`eu.*` outage (ADR 0028): 130 of 192 calls were answered by `global.*` after a failed `eu.*`
attempt. The current `agent` run had a fallback share of 0.03 (acme-010 and acme-012 got one
gpt-oss call each, both still correct) and two questions abstained on
`ServiceUnavailableException` from Bedrock (hp-5ac1b134..., hp-5a8e3ea9...).

What the runs show (the failure analysis for EVALUATION.md starts here):
- **The loop pays off on multi-hop**: 0.87 vs 0.52 judge (same prompt). `single-shot` abstains on 9 of 23
  multi-hop questions (abstention precision 0.48): it cannot search again for the bridge entity
  the first hits name.
- **Chunking**: fixed beats structured on retrieval (R@10 0.89 vs 0.83); on answers the gap
  (0.74 vs 0.70) is within the noise of this set.
- **Contradictions were the weak spot and a prompt fix moved them most** (recall 0.25 -> 0.67,
  precision 0.75 -> 1.00, judge 0.08 -> 0.58), although retrieval found both sides from the
  start (contradictory R@10 0.96 for fixed/mmr). Two causes in the #31 traces: (1) the model
  wrote each side of a conflict as its own `contradictions` entry with one citation, and the
  validator, which wants >= 2 distinct citations per entry, dropped all of them (5 of 12:
  acme-020, 022, 025, 027, 030); (2) the agent stopped at the first source that answered (9 of
  12 cited fewer than 2 documents). With one entry per conflict asked for, no contradiction was
  dropped. Still missed: acme-019, 021, 023, 026 answer from one document (an incident report
  against a status page or a later report); acme-020 reports the conflict but its short answer
  takes one side. No answerable question was flagged `conflicting` by mistake.
- **Multi-hop moved 0.87 -> 0.78 with the new prompt**: two questions. One abstained on a
  Bedrock `ServiceUnavailableException`; in the other (hp-5a8c493e...) the uncached model chose
  different sub-queries and found the wrong John Ruskin. Run-to-run variance, not the
  contradiction rules: a question moves this type by 0.04.
- **Malformed `final_answer`**: 16 of 72 `agent` answers needed a reprompt with the #31 prompt,
  5 with the current one; Haiku puts `claims` in as a string with tool-call markup
  (`<parameter name="text">...`) instead of a list.
- **The citation validator never dropped a claim** (0 in 288 answers): claims cite retrieved
  chunks; citation precision 0.93-0.94.
- **EM undercounts**: short answers carry extra words ("two monks" for "two", "Honolulu County"
  for "Honolulu"); EM 0.52 vs F1 0.73 vs judge 0.82.

## Known limits

- **Judge bias.** One model's opinion; Qwen3 is from a different family than the Claude
  generator, which removes self-preference but not leniency. Spot-check ~10 verdicts by hand and
  report agreement in EVALUATION.md. Seen in the 2026-10-26 runs: `acme-024` in `agent` reported
  the conflict with both times in its contradiction and was judged wrong, while `single-shot`'s
  answer with an empty short answer was judged right; `acme-004` was judged wrong for an answer
  that matches the gold. Measured once (2026-10-25): "Joseph L. Mankiewicz" against
  gold "Joseph Leo Mankiewicz" -> `{"correct": true, ...}`, a clean JSON object, 197 in / 36 out.
- **HotpotQA chunking comparison is weak.** Paragraphs average 532 characters, so both chunkers
  mostly keep a paragraph whole; the chunking comparison is meaningful on Acme.
- **Small set.** 25 answerable HotpotQA questions: one question moves Recall by 0.04. Differences
  below ~0.1 are noise.
- **Recall depends on the dense candidate list** (`hnsw.ef_search` 40): measured end to end it is
  enough (fixed/dense Recall@10 0.89); raise it inside `db.transaction()` if a corpus change drops it.
- **EM is strict** on HotpotQA's long or noisy gold answers; read it together with F1 and the
  judge.
