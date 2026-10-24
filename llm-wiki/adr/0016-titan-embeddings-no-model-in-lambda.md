---
title: Bedrock Titan Text Embeddings V2, no model inside the Lambda image
status: accepted
date: 2026-10-24
supersedes: 0009; the embedding-model part of 0003
superseded_by: none
---

# ADR 0016: Bedrock Titan Text Embeddings V2, no model inside the Lambda image

## Context

ADRs 0003 and 0009 put fastembed `bge-small-en-v1.5` inside the Lambda image and embedded the corpus
on the laptop. The project must not depend on the author's computer (ADR 0018), and the AWS credits
can pay for embeddings. The model was also the only reason the image was heavy (onnxruntime, numpy,
model weights) and cold starts slow.

## Decision

Embeddings come from Amazon Bedrock **Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`),
on-demand in `eu-north-1`, **1024 dimensions** stored as `halfvec(1024)`. The `ingest` Lambda embeds
chunks, the `api` Lambda embeds queries; both call Bedrock with their IAM role. The Lambdas keep one
shared container image (simple, already proven in CI), now without any ML runtime.

## Consequences

No model to ship, no local step, the corpus costs ~$0.19 to embed (~9M tokens at $0.021 per 1M).
Dimensions are configurable, which gives a free embedding comparison for the evaluation (512 vs
1024). The image is small and cold starts are shorter.
The cost: Titan takes one text per request, so the bulk load is ~60k calls and is bound by the
account's requests-per-minute quota (unknown until the new account finishes verification); every
query makes a network call (+50-150 ms); retrieval quality is below the best embedding models;
Bedrock is unavailable while the account is being verified.

## Alternatives considered

**fastembed `bge-small` (ADRs 0003, 0009)**: free and quota-free; would still be laptop-independent if
run in CodeBuild. Kept as the fallback if the Titan quota throttles the bulk load.

**Cohere Embed v3/v4**: better quality, 96 texts per request, but not offered on-demand in
`eu-north-1`.

**Titan batch inference**: half price, no per-minute quota, but asynchronous S3 jobs; only if the
quota blocks the bulk load.

**SageMaker endpoint**: any model, but an always-on instance.

**Zip packaging (binadar)**: possible again now that no ML runtime is needed; not worth changing a
working pipeline during the five days.

## Update 2026-10-24

The open risks above are closed. A new account starts with every Bedrock model quota at 0 and
calls fail with `ThrottlingException` ("Too many tokens per day"); a few hours after the account
was verified the quotas opened by themselves. Titan Text Embeddings V2 now answers in `eu-north-1`
with 1024-dimension vectors. Its quota does not appear in Service Quotas, so the bulk load must
still back off on throttling. While the quotas were at 0, Cohere Embed V4 (`eu.*`/`global.*`,
96 texts per request) was evaluated as a replacement; Titan stays, Cohere is the fallback if the
bulk load turns out to be throttled.
