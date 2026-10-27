# Performance

Measured latency, throughput, load test and cold starts. Back to the [README](../README.md).

| What | Number | Source |
|---|---|---|
| Bulk load of 66,555 HotpotQA documents | ~65 min, measured: documents created between 17:29 and 18:34 UTC on 2026-10-25. Bound by the Cohere pool (~700 requests of 96 texts); the estimate beforehand was ~35-40 min | [llm-wiki/05](../llm-wiki/05-corpora.md), [ADR 0022](../llm-wiki/adr/0022-cohere-embed-v4-batched.md) |
| Database write | ~0.03 s per document | [llm-wiki/05](../llm-wiki/05-corpora.md) |
| Eval build time (72 questions) | `retrieval` ~5 min, `agent-structured` 19 min, `single-shot` 9 min; `agent` with the current prompt not recorded (22 min with the prompt of #31) | [llm-wiki/09](../llm-wiki/09-evaluation.md#pacing-and-cost) |
| Prompt cache | steps 3-6 of a run read the history from the cache, ~35% cheaper per question | [llm-wiki/14](../llm-wiki/14-known-gaps.md) |

`ask` latency per configuration, seconds, 72 questions
([llm-wiki/09](../llm-wiki/09-evaluation.md#results)):

| Config | p50 | p95 |
|---|---|---|
| `agent` (fixed chunks, 6 steps, current prompt) | 10.3 | 45.6 |
| `agent`, prompt of #31 (first uncached run, during the `eu.*` outage) | 13.4 | 40.0 |
| `agent-structured` | 6.7 | 22.8 |
| `single-shot` (1 step) | 5.8 | 11.4 |

Quality in one line (the full analysis is in [EVALUATION.md](../EVALUATION.md)): `agent` judge
correctness 0.82, citation precision 0.94, abstention precision/recall 0.77/0.91, contradiction
precision/recall 1.00/0.67; the loop beats single-shot on multi-hop questions, 0.87 vs 0.52 with
the same prompt; fixed/mmr retrieval Recall@10 0.89.

Load test (`make load-test` in CodeBuild, same Region, 200 GETs per level over `/health`,
`/documents` and `/documents/{id}`; details in
[llm-wiki/07](../llm-wiki/07-infrastructure.md#performance)):

| Concurrent clients | Succeeded / 429 / other errors | p50 / p95 / p99 ms |
|---|---|---|
| 1 | 200 / 0 / 0 | 26 / 48 / 52 |
| 5 | 104 / 96 / 0 | 24 / 77 / 1,556 (new instances starting) |
| 10 | 97 / 103 / 0 | 27 / 60 / 74 |

| What | Number |
|---|---|
| `api` cold start | init p50 1.29 s, p95 1.74 s (55 cold starts in the production logs) |
| Aurora resume from 0 ACU | 15-25 s, median ~18.5 s (12 resumes in the production logs) |
| One search from the Lambda (`/ask` rerun served by `llm_cache`) | 0.74 s end to end |
| Search in Region (retrieval eval) | mmr p50 0.33 s, p95 0.73 s; hybrid SQL alone p50 0.13 s |

What limits throughput: the `api` reserved concurrency of 4 (the 5th concurrent request gets 429,
nothing else failed); for `POST /ask`, the Bedrock quotas (Haiku 10 requests/min per profile,
Cohere 20/min) long before Lambda or Aurora (max 4 ACU, not moved by the test). Aurora does not
pause while warm `api` instances hold their connection. Monitoring: one CloudWatch dashboard of
built-in metrics and Logs Insights tables ([ADR 0033](../llm-wiki/adr/0033-dashboard-built-in-metrics-logs-insights.md)).

Not measured:

- `POST /ask` under concurrent load (deliberately: it spends Bedrock credits).
- The judge's agreement with a human is not measured yet.
