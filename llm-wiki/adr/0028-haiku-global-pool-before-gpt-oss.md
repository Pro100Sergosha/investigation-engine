---
title: Haiku's global pool before gpt-oss, and a bounded client for query embeddings
status: accepted
date: 2026-10-26
supersedes: 0023 (fallback order only)
superseded_by: none
---

# ADR 0028: Haiku's global pool before gpt-oss, and a bounded client for query embeddings

## Context

On 2026-10-26 the `eu.anthropic.claude-haiku-4-5-*` inference profile answered
`ServiceUnavailableException` ("Bedrock is unable to process your request") to every call for
at least 15 minutes, while the same model through `global.anthropic.claude-haiku-4-5-*` answered
at once. With ADR 0023's chain (Haiku `eu.*` with three retries, then gpt-oss-120b) every call
spent ~10 s on retries that could not succeed and was then answered by gpt-oss: the eval dry run
had a fallback share of 1.0 and one question ran out of the agent's 80 s deadline. An eval in
that state measures gpt-oss, not the system as designed, and nothing from it is cached.

Separately, the agent's deadline (ADR 0025) bounded LLM calls but not search: `embed_query`
shared the bulk client (adaptive retries, up to 10 attempts, 60 s read timeout), so a throttled
query embedding could push `POST /ask` past the api Lambda's 90 s.

## Decision

- `llm.converse` tries, for Haiku: `eu.*` once, then `global.*` with the usual retries
  (1, 2, 4 s), then gpt-oss-120b with retries. `eu.*` gets no retries of its own: any retryable
  error (throttling or unavailability) moves straight to the second pool, which also spreads a
  burst over two 10 requests/min quotas. Other models (gpt-oss, the Qwen judge) keep their single
  model with retries.
- An answer from `global.*` is cached under the Haiku key: same model, temperature 0. A gpt-oss
  answer is still not cached. Both Haiku profiles get the Claude `cachePoint`s (checked live).
- IAM (`_allow_profile` in `cdk/app.py`) grants the `global.*` Haiku profile in addition to
  `eu.*`; a global profile's model ARN has no Region (`arn:aws:bedrock:::foundation-model/...`),
  allowed only through the profile.
- The eval runner counts both Haiku profiles as Haiku (pacing, the fallback share) and prices
  `global.*` at $1.00/$5.00 per 1M (no EU surcharge).
- `embed_query` uses its own client: 2 attempts, 2 s connect and 4 s read timeout (~13 s worst
  case with backoff), close to the ~10 s the agent leaves for a search after its last non-final
  LLM call, inside the handler's margin. A failure raises a botocore error and the agent abstains.

## Consequences

Haiku answers as long as either pool works, and an outage of the EU pool costs one failed
request instead of ~10 s per call. The cost: a question may be processed outside the EU when
`eu.*` fails. The corpus is public HotpotQA plus synthetic Acme data, so nothing sensitive leaves;
a deployment with real customer data would drop `global.*` from the chain. The answering model is
still recorded per call in the trace (`model`), so the eval reports which pool answered. A
throttled query embedding now fails the question as "insufficient" instead of waiting.

## Alternatives considered

**Keep retrying `eu.*`**: right for short throttling, useless for an outage, and it ate the
agent's deadline. **Only `global.*`**: simpler, but always sends data out of the EU and loses the
second quota pool. **Wait for `eu.*` to recover**: the eval and the demo depend on Haiku; an
outage of unknown length near the deadline is the risk this removes. **Pass the deadline into
`search.search`**: more plumbing through `search.py` for the same effect as two timeouts.
