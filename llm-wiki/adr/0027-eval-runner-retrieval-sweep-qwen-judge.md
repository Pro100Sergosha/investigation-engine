---
title: Own eval runner: an LLM-free retrieval sweep, a Qwen3 judge, Haiku pacing, results via S3
status: accepted
date: 2026-10-25
supersedes: none
superseded_by: none
---

# ADR 0027: Own eval runner: an LLM-free retrieval sweep, a Qwen3 judge, Haiku pacing, results via S3

## Context

The task demands an own automated evaluation with retrieval and answer metrics and at least two
configurations compared (PLAN.md sections 1 and 4). The metric functions exist (`eval/metrics.py`);
something has to run the question set against the deployed index and agent. The forces:

- **Haiku is the budget and the bottleneck**: $100 of credits, 10 requests/min per profile
  (ADR 0017). Above that `llm.py` retries and silently falls back to gpt-oss-120b (ADR 0023),
  which would mix models into a result labelled "Haiku".
- **Most comparisons do not need an LLM**: chunking A vs B and dense vs hybrid vs MMR are
  retrieval questions.
- HotpotQA gold answers are short spans ("1972"), Acme answers are not, and some questions have
  no gold answer at all (unanswerable, contradictory).
- Long jobs run in CodeBuild, never on the laptop (ADR 0018); explainable code, no frameworks
  (ADR 0001).

## Decision

One file, `eval/run.py`, run as `make eval CONFIG=<name>` in CodeBuild `investigation-jobs`:
pure functions (loading and validation, scoring, judge parsing, pacing, cost, aggregation) around
one I/O loop.

- **`retrieval` is a sweep without an LLM.** Every answerable question goes through
  `search.search(k=10)` in all 2 strategies x 3 modes; Recall@5/10 and MRR on the documents'
  sources. `embed.embed_query` is memoized (`functools.lru_cache`, 256 entries), so the six
  searches of a question cost one Cohere request.
- **Answer configurations run the agent**: `agent` (structured, mmr, 6 steps), `agent-fixed`,
  `single-shot` (`max_steps=1`). Per question: answer, claims with their sources, models, tokens,
  cost, seconds and every metric.
- **EM/F1 on `Answer.answer`**, the short direct answer (ADR 0005 contract, PR #25), only for
  HotpotQA questions; the claims are not compared token by token.
- **Correctness by an LLM judge from another family: Qwen3-235B** (`llm.QWEN`, in Region,
  100 requests/min, $0.22/$0.88 per 1M) through `llm.converse`, so it is cached and retried but
  never falls back. Strict JSON verdict `{"correct", "reason"}`, read from the first `{` to the last
  `}`. A judge failure is `None` and counted, never a crash. An abstention on an answerable
  question is `false` without a call.
- **Pacing**: after each question, sleep `max(0, 6 s x uncached Haiku calls - elapsed)`, from the
  trace's `llm` entries (`model`, `cached`, `usage`: the `agent.ask` contract). Cached calls and the
  judge are not paced.
- **One question failing does not fail the run**: an exception from `ask` or a search is recorded
  in its record and counted in the summary.
- **Results**: `eval/results/<config>.json` uploaded to `s3://$BUCKET/jobs/eval/`, then
  downloaded and committed by a PR; the build log prints the summary as Markdown. `--limit N`
  writes `<config>-limit<N>.json`, so a dry run never overwrites a full run.

## Consequences

The required comparisons (chunking, retrieval mode) cost nothing but CodeBuild minutes and can be
rerun freely. Answer runs cost ~$0.02-0.035 per question (Haiku), the judge ~$0.0001; reruns are
free through `llm_cache` as long as prompts do not change. Pacing makes an agent run slow by design
(~25-35 s per question, ~10-20 min for 30 questions) but keeps the results single-model, and the
`fallback_share` column shows when that failed.

The costs: a judge is one model's opinion and its bias is unmeasured until a hand spot-check
(PLAN.md risk list); HotpotQA labels are taken verbatim, noise included; with ~25 answerable
HotpotQA questions a single question moves Recall by 0.04. Memoized query vectors are shared lists:
callers must not mutate them, and the `api` Lambda keeps up to ~8 MB of them while warm. Results
pass through S3 and a PR before the repository sees them (ADR 0018).

## Alternatives considered

**RAGAS, DeepEval or another eval framework**: ready-made faithfulness and relevance metrics, but
LangChain-style dependencies and metrics the author cannot rewrite on a whiteboard (ADR 0001); the
metrics needed here are a few lines each.

**Haiku (or any Claude) as the judge**: one model family fewer to explain, but a judge grading its
own family's answers is known to be lenient with them. gpt-oss-120b as judge: cheaper, but it is
the agent's fallback, so it would sometimes grade its own answers.

**Retrieval metrics from the agent's own searches**: no extra runs, but the agent reformulates
queries, so chunking and mode effects would be mixed with the agent's behaviour, and every
retrieval number would cost Haiku calls.

**No pacing, let `llm.py` handle throttling**: faster, but answers silently come from gpt-oss under
throttling, and a sweep would measure the fallback, not Haiku.

**EM/F1 on the claims text**: no extra field needed, but a long claim against "1972" scores near 0
even when correct.
