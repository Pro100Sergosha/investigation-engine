---
title: Own small code, no RAG or web frameworks
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0001: Own small code, no RAG or web frameworks

## Context

The task (Upgaming Talent Growth Program, `docs/task.pdf`) ends with an interview where the author
explains the architecture, walks the RAG pipeline, and fixes bugs or adds features live **without
AI**. Code that nobody in the room can rewrite on paper fails that interview regardless of how well
it works.

## Decision

No LangChain, LlamaIndex, Haystack, ORMs or web frameworks. Chunkers, dedup, RRF, MMR, the agent
loop, the citation validator, the Lambda router and the metrics are hand-written, short and
readable. Libraries only where writing it by hand is unreasonable: file parsers (pypdf,
python-docx), the Postgres driver (psycopg), the embedding runtime (fastembed), CDK.

## Consequences

Every line is explainable and small enough to change live. Fewer dependencies, smaller image.
The cost: features a framework gives for free (streaming helpers, retries, document loaders,
OpenAPI docs) are written or skipped, and own code can have bugs a mature library fixed years ago.
Tests carry more weight because there is no library to trust.

## Alternatives considered

**LangChain/LlamaIndex**: fastest path to a demo, and the reasonable pick for a product team. Lost
because the defence is about understanding, and their abstractions hide exactly the parts the
interview asks about.

**FastAPI**: would be the default backend. Lost once the backend became a Lambda (ADR 0007): a
router over `(method, rawPath)` is ~20 lines and needs no adapter.
