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
