---
title: Shared dataclass contracts and parallel workstreams
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0014: Shared dataclass contracts and parallel workstreams

## Context

Twelve days of planned work have to fit into five, so independent parts must progress at the same
time (data and search, LLM and agent, Acme corpus and parsers, API/UI/infra, evaluation) without
blocking on each other.

## Decision

Streams communicate only through `src/engine/models.py` (`ParsedDoc`, `Hit`, `Claim`, `Answer`,
plain `@dataclass`) and four functions: `parse(path)`, `search(query, k)`,
`get_document(document_id)`, `ask(question)`. Until a function exists its consumers use a stub with
fixed data. Each stream works on its own branch/worktree and merges when its tests pass. Changing a
contract updates every user in the same commit.

## Consequences

Streams can start on day 1; merge points are known (PLAN.md section 5).
The cost: contracts fixed early may be wrong and need a coordinated change; parallel work is limited
by the author's ability to review and explain every stream, realistically two or three at once;
Groq rate limits are shared between streams.

## Alternatives considered

**Pydantic models**: validation for free, but a dependency and more magic than four dataclasses need.

**Sequential phases**: simpler, does not fit the deadline.
