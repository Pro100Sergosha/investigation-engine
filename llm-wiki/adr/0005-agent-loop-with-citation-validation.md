---
title: Own agent loop with tool calling and server-side citation validation
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0005: Own agent loop with tool calling and server-side citation validation

## Context

The task requires multi-step handling of complex questions, at least one tool-calling mechanism,
answers grounded in evidence with citations, abstention when information is missing, and an attempt
at contradiction detection. Prompt wording alone does not prevent hallucinated citations.

## Decision

A hand-written loop: the LLM can call `search(q)`, `get_document(id)` and `final_answer(json)`,
with a hard step cap (6) and a token budget per question. The final answer is structured
(`Answer` in `models.py`): claims with chunk-id citations, contradictions, and a status
`answered | insufficient | conflicting`. The server drops every claim that cites a chunk never
returned by a tool call in this run; if no claim survives, the status becomes `insufficient`.

## Consequences

Anti-hallucination is mechanical and testable, not a prompt promise. The trace of steps is returned
for the UI and for debugging. Abstention is a first-class outcome.
The cost: more LLM calls per question than single-shot RAG (rate limits, latency up to tens of
seconds, which is why the API is a Function URL, ADR 0008); the loop and its JSON parsing are ours
to keep robust against malformed output.

## Alternatives considered

**Single-shot RAG**: one call, cheaper, kept as the baseline configuration in the eval.

**Framework agents (LangGraph etc.)**: rejected by ADR 0001.

## Update 2026-10-26

Built in `agent.py`; the details are in [ADR 0025](0025-agent-loop-seeded-forced-deadline.md).
Two points refine the text above without changing the decision:
- "Returned by a tool call in this run" also covers the search the server runs on the question
  before the first LLM call (the seed), and `get_document` returns chunk ids, so its passages
  are citable too.
- The "token budget per question" is not a token counter: it is the step cap (6), k <= 40 per
  search and an 8,000-character cap on `get_document`.
