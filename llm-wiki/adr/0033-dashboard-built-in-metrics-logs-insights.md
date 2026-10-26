---
title: One CloudWatch dashboard from built-in metrics and Logs Insights, no custom metrics or tracing
status: accepted
date: 2026-10-26
supersedes: none
superseded_by: none
---

# ADR 0033: One CloudWatch dashboard from built-in metrics and Logs Insights, no custom metrics or tracing

## Context

The task lists "detailed monitoring and observability" as a bonus. Until now the system had one
JSON log line per request (`handlers.api`: method, route, status, ms; for `POST /ask` the answer
status, LLM steps, models, tokens and cache hits) and one per ingested file, read by hand in Logs
Insights. Nobody could see at a glance whether the api throttles, whether Aurora is awake, or
whether a Bedrock pool is throttling.

Constraints: the account is a Free-plan project with $100 credits (ADR 0011); CLAUDE.md forbids
custom CloudWatch metrics (binadar's lesson: $0.30 per metric per month, and every dimension value
is a new metric); everything must be explainable without AI, so no instrumentation library that
patches boto3 behind the code's back.

What AWS already emits for free: Lambda (`Invocations`, `Errors`, `Throttles`, `Duration`,
`ConcurrentExecutions`, and for the Function URL `UrlRequestCount`, `Url4xxCount`, `Url5xxCount`,
`UrlRequestLatency`), Aurora (`ServerlessDatabaseCapacity`, `DatabaseConnections`), SQS
(`ApproximateNumberOfMessagesVisible`) and Bedrock per `ModelId`, inference profiles included
(`Invocations`, `InvocationThrottles`, `InvocationServerErrors`, `InvocationLatency`, token
counts). Checked with `list-metrics` on 2026-10-26: all of them exist for this account.

## Decision

One dashboard, `investigation-engine`, in `Investigation-prod` (it changes with the code; CDK
`_dashboard` in `cdk/app.py`):

- 35 built-in metrics: api and ingest Lambda counts, duration p50/p95/max and concurrency; Aurora
  ACU (0 = paused) and connections; `IngestFailures` depth; Bedrock invocations, throttles,
  server errors, p95 latency and Haiku tokens per model or profile.
- Logs Insights tables over the existing log lines: requests and p50/p95/max per route, responses
  by status, `POST /ask` per day (questions, latency, tokens, cached calls, estimated USD at Haiku
  EU prices), cold starts and memory from Lambda's `REPORT` lines, recent 5xx, recent ingested
  files, requests outside `/ask` slower than 3 s (Aurora resumes). No change to the log lines was
  needed.
- Two alarms without actions (no SNS topic): api `Url5xxCount >= 1` in 5 min and `IngestFailures`
  visible messages `>= 1`. They only turn red on the dashboard.
- Load testing is a stdlib script (`scripts/load_test.py`, the `load-test` job), its numbers in
  llm-wiki/07, Performance.

## Consequences

- Cost $0: the free tier has 3 dashboards of up to 50 metrics each (this is the only dashboard,
  35 metrics) and 10 alarm metrics (2 used). Logs Insights scans count against the 5 GB/month of
  free Logs data; the api log group holds ~0.3 MB, so a dashboard view scans ~1 MB.
- A 36th-50th metric is free; past 50, or a fourth dashboard, costs $3 per dashboard-month.
- Nobody is notified: an alarm is only visible to whoever opens the dashboard. Fine for a demo
  with one operator; an SNS e-mail subscription (supported on the Free plan) is the next step.
- Bedrock metrics are account-wide: eval and Acme jobs show up next to the api's calls.
- The estimated `/ask` cost ignores prompt-cache writes (not logged) and prices gpt-oss as Haiku;
  the eval's cost (llm-wiki/09) stays the precise number.
- No per-step latency inside a request on the dashboard: the `/ask` trace (returned to the
  caller) has LLM step times, searches are timed only by the load test and the eval.

## Alternatives considered

- **Custom metrics (EMF lines, `put_metric_data`, metric filters)**: route and status as metric
  dimensions would give alarms per route. Every name x dimension combination is a $0.30/month
  metric, and CLAUDE.md forbids them. Logs Insights answers the same questions from the logs
  already written. Right call when an alarm per route or a percentile over weeks is needed.
- **AWS X-Ray (Lambda active tracing)**: on the Free-plan list and 100k traces/month free, so
  cost is not the reason. Active tracing alone shows only the Lambda segment; segments for
  Bedrock and Aurora need the X-Ray SDK or the ADOT layer, which patch boto3 and pg8000 at
  import: a dependency and magic the author would have to explain. The `/ask` trace already
  records each LLM step's time. Right call when requests fan out over several services.
- **CloudWatch Lambda Insights, Application Signals**: an extension layer per function that emits
  custom metrics (billed) or needs ADOT. Rejected for the same reasons.
- **Amazon Managed Grafana**: not supported on the Free plan (the supported-services list puts it
  under "not supported"); enabling it is the kind of change that upgrades the plan.
- **No dashboard, Logs Insights by hand**: what existed. Free, but throttles, a paused database
  and Bedrock errors were invisible until someone thought to query.
- **Synthetics canary for uptime**: billed per run (~$0.0012) plus its own Lambda and S3 bucket;
  `make smoke` after every deploy and the load test cover the demo.
