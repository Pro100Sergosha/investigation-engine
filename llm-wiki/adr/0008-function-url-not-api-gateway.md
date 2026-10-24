---
title: Lambda Function URL instead of API Gateway, UI served by the same Lambda
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0008: Lambda Function URL instead of API Gateway, UI served by the same Lambda

## Context

`POST /ask` runs the agent loop (ADR 0005): several LLM calls, often more than 30 seconds.
API Gateway HTTP API cuts every integration at 30 seconds. Lambda's synchronous payload limit is
6 MB, too small for document uploads.

## Decision

The `api` Lambda is exposed through a Function URL (auth `NONE`, HTTPS included), timeout 90 s.
It also serves the single HTML page at `GET /`, so UI and API share an origin: no CORS, no
CloudFront. Uploads go browser -> S3 via a presigned URL; the S3 event triggers the `ingest` Lambda.

## Consequences

Long agent runs complete; one URL for everything; nothing to configure for CORS or TLS.
The cost: no SSE streaming for Python on Function URLs, so the trace arrives with the final answer
and the streaming bonus is dropped. No throttling or auth layer in front: protection is reserved
concurrency on `api` (quota is 400 on this project) plus the budget alert. No custom domain.

## Alternatives considered

**API Gateway HTTP API**: what binadar uses, cheaper per request than REST and has throttling, but
the 30 s limit breaks `/ask`. Would win if `/ask` became asynchronous (job + polling).

**CloudFront + S3 for the UI**: better caching, more resources and a second origin for no benefit
at demo scale.
