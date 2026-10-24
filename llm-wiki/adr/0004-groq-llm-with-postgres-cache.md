---
title: Groq as the LLM, Bedrock fallback, all calls through one cached client
status: superseded
date: 2026-10-24
supersedes: none
superseded_by: 0017
---

# ADR 0004: Groq as the LLM, Bedrock fallback, all calls through one cached client

## Context

The agent, Acme corpus generation and LLM-as-judge evaluation all call an LLM. The budget is zero.
Free tiers are rate limited (Groq: roughly 8k tokens/min and 1k requests/day per model), and the
eval runs 40+ questions across several configurations. Lambda has no persistent disk.

## Decision

Groq (`openai/gpt-oss-120b` main; a smaller model for planning and the judge) with Amazon Bedrock
(Nova Lite, from AWS credits) as fallback. Every call goes through `llm.py`: timeout, retry with
backoff on 429/5xx, fallback model, and a Postgres table `llm_cache(prompt_hash, model, response)`.
Nothing calls a provider directly.

## Consequences

Free, fast, tool calling supported; repeated eval runs and re-deploys hit the cache instead of the
rate limit; one place to handle errors and log tokens. The judge uses a different model than the
generator.
The cost: answers depend on two external providers; cached responses hide prompt changes unless the
prompt is part of the hash (it is); Bedrock spends credits.

## Alternatives considered

**Gemini free tier as fallback**: also free, but Bedrock keeps the fallback inside the AWS account
and its credentials, no second API key.

**Bedrock only**: simplest on AWS, but every eval run spends credits.

**Disk cache**: fine locally, useless in Lambda.
