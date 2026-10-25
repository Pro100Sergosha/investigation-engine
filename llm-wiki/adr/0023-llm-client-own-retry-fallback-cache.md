---
title: One LLM client with its own retry loop, Haiku-only fallback, portable turns and a fail-open cache
status: accepted
date: 2026-10-25
supersedes: none
superseded_by: none
---

# ADR 0023: One LLM client with its own retry loop, Haiku-only fallback, portable turns and a fail-open cache

## Context

ADR 0017 says every LLM call goes through `llm.py` with retry, fallback to gpt-oss-120b, prompt
caching and the `llm_cache` table, but not how. The consumers are the agent loop (up to 6 calls
per question inside the `api` Lambda's 90 s) and the evaluation judge in CodeBuild. Haiku 4.5
allows only 10 requests/min, so throttling is the normal failure, not the rare one. Facts
measured on 2026-10-25 (ADR 0017 update): gpt-oss-120b returns `reasoningContent` blocks without
a signature and Claude rejects them in history; gpt-oss and Qwen3 answer a `cachePoint` with
AccessDeniedException; Haiku 4.5 caches only prompts of 4,096 tokens or more.

## Decision

`llm.converse(system, messages, tools=None, model=HAIKU, max_tokens=2048, use_cache=True)` is
the only public function. Converse format in and out; it returns the assistant message, stop
reason, usage, the model that answered and whether the answer came from the cache.

- **Own retry loop, botocore retries off.** botocore makes one attempt (connect 5 s, read 30 s);
  `llm.py` retries ThrottlingException, ServiceUnavailable, InternalServer, ModelNotReady,
  ModelTimeout, read timeouts and connection errors after 1, 2, 4 s (+ up to 1 s jitter each,
  at most 10 s of waiting per model). Anything else (ValidationException, AccessDenied) raises at
  once. The loop must be ours because only it knows when retries are exhausted and the fallback
  should start.
- **Fallback only from Haiku.** After the last Haiku retry fails with a retryable error the same
  request goes to gpt-oss-120b (with its own retries). The judge (Qwen3) and explicit gpt-oss calls
  have no fallback: the judge must stay one model family.
- **Portable turns.** `reasoningContent` blocks are removed from every returned message, so the
  agent can append it to the history and send the next turn to either model.
- **One `cachePoint`, Claude only,** after the system prompt. Claude renders tools before the
  system prompt, so it covers both (measured: a 5,030-token tool list with a two-word system
  prompt was written and then read from the cache).
- **Postgres cache key** = sha256 of canonical JSON (sorted keys) of requested model, system,
  messages, tools, max_tokens and temperature (always 0). Read before the call, `INSERT ... ON
  CONFLICT DO NOTHING` after. A fallback answer is not stored: the key names Haiku, and a rerun
  should ask Haiku again.
- **The cache fails open.** Any error reading or writing `llm_cache` is logged in one line and
  the model is called anyway: the cache saves money, it is not a source of truth.

## Consequences

Throttling costs at most ~10 s before gpt-oss answers, and the trace shows which model answered.
Mixed-model conversations work. Reruns of the evaluation are free once cached.
The costs: gpt-oss loses its own reasoning between turns (it re-reasons each step; output tokens
are cheap). Under sustained Haiku throttling (an evaluation sweep at more than 10 requests/min)
answers silently mix models; the eval runner has to pace itself or read `model`. The prompt
cache does nothing for today's ~1.3k-token agent prompt (below Haiku's 4,096 minimum); it is kept
because below the minimum it costs nothing and raises no error. A broad `except` around the cache
hides a broken cache except for the log line. No `toolChoice`, no streaming: added when the agent
needs them.

## Alternatives considered

**botocore adaptive retries (as `embed.py`)**: less code, but the caller cannot tell "retries
exhausted" from "bad request" without re-classifying errors itself, and the waits are not bounded
for the 90 s Lambda.

**Keep `reasoningContent` and strip it only when the next turn goes to Claude**: gpt-oss keeps its
reasoning, but the history then depends on which model answers next; one rule is simpler.

**Cache fallback answers too**: fewer calls on rerun, but a throttled minute would pin gpt-oss
answers under Haiku's key forever.

**Cache point after the last message** (caches the growing agent history, which passes 4,096
tokens after a few search results): real savings on steps 2-6; left for the agent PR, where the
history shape is known and can be measured.
