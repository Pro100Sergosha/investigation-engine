---
title: All LLM calls on Amazon Bedrock, Claude Haiku as the main model
status: accepted
date: 2026-10-24
supersedes: 0004
superseded_by: none
---

# ADR 0017: All LLM calls on Amazon Bedrock, Claude Haiku as the main model

## Context

ADR 0004 chose Groq's free tier with Bedrock as fallback. The project has $100 of AWS credits, Groq
needs an external API key and limits the free tier to roughly 8k tokens per minute, which stalls
the evaluation. Instruction following and reliable JSON/tool calling matter more for the agent than
a few dollars.

Available in `eu-north-1` (checked 2026-10-24): on-demand in Region `openai.gpt-oss-120b/20b`,
`qwen.qwen3-235b-a22b-2507`, `amazon.nova-lite-v1:0` and others; Claude only through the `eu.*`
cross-Region inference profiles (Haiku 4.5 and 5.5, routed across six EU Regions).

## Decision

| Role | Model | Price per 1M tokens (in / out, EU) |
|---|---|---|
| Agent and Acme corpus generation | **Claude Haiku** via `eu.anthropic.claude-haiku-*` (4.5 or 5.5, picked by a test after verification) | Haiku 4.5: $1.10 / $5.50, cache read $0.11 |
| Fallback | `openai.gpt-oss-120b-1:0`, in Region | $0.15 / $0.60 |
| Evaluation judge | `qwen.qwen3-235b-a22b-2507-v1:0`, in Region | $0.22 / $0.88 |

Every call goes through `llm.py` (Bedrock Converse API): timeout, retry with backoff on
`ThrottlingException`, automatic fallback to gpt-oss-120b, prompt caching on the system prompt and
tool definitions, and the Postgres `llm_cache` by prompt hash. No external API keys.

## Consequences

Better instruction following and JSON for the agent; one provider and one credential model (IAM);
no free-tier token cap. The judge is from a different model family than the generator.
The cost: Haiku is ~7x the price of gpt-oss-120b. Estimate: ~$0.02-0.035 per agent question, a full
evaluation sweep (45 questions x 4 configurations) ~$4-6, ~$15-25 over the project, inside the
credits; the cache and prompt caching keep reruns cheap. **Open risk:** the Free-plan SCP may deny
cross-Region inference; if Haiku is denied, gpt-oss-120b becomes the main model and the judge stays
Qwen3. Bedrock quotas of the new account are unknown until verification completes.

## Alternatives considered

**gpt-oss-120b as the main model**: in Region, 7x cheaper; a reasoning model that spends output
tokens on reasoning and sometimes breaks strict JSON. It is the fallback.

**Claude Sonnet**: best quality, ~$3/$15 per 1M, too expensive for repeated evaluation sweeps.

**Qwen3-235B or DeepSeek V3.2 as main**: strong and in Region; then the judge must come from yet
another family.

**Nova Lite as main**: cheapest, weaker at multi-step reasoning.

**Groq free tier (ADR 0004)**: $0, but an external key and an 8k tokens/min cap.
