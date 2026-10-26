---
title: Cohere Embed V4 on Bedrock, batched, instead of Titan
status: accepted
date: 2026-10-25
supersedes: 0016 (the embedding model only; no model inside the Lambda image stays)
superseded_by: none
---

# ADR 0022: Cohere Embed V4 on Bedrock, batched, instead of Titan

## Context

ADR 0016 chose Titan Text Embeddings V2: one text per request, quota unknown. On 2026-10-25 the
bulk load of the 66,555 HotpotQA documents (134 shards through `ingest`, 5 concurrent Lambdas,
one Titan call per distinct chunk) stalled at **1,853 documents**:

- Titan on-demand answered `ThrottlingException` beyond ~1 request/s, ~60 documents/min overall.
  At that rate the corpus takes ~18 h; the deadline is 2026-10-29.
- Lambda's async retries (3 attempts per shard, 405 invocations) all hit throttling, and the
  events were dropped without a record of which shards failed.
- Titan's quota is not listed in Service Quotas, so it cannot be requested higher.
- Titan batch inference (`CreateModelInvocationJob`): "Your account is not authorized to perform
  this action. Please create a support case". A support case takes days.

Facts about Cohere Embed V4, verified with real calls the same day:
- Reachable from `eu-north-1` only through the inference profiles `eu.cohere.embed-v4:0` (routes
  to eu-north-1, eu-west-1, eu-west-3, eu-south-1, eu-south-2, eu-central-1) and `global.*`.
- Quotas per profile pool: 20 requests/min, 300k tokens/min, 16.2M tokens/day.
- Up to 96 texts per request; `input_type` `search_document` or `search_query`;
  `output_dimension` 1024 (the schema's `halfvec(1024)` stays); vectors come back unit length.
- 96 HotpotQA documents ("<title>\n\n<text>") = 15,180 input tokens (~158 per document),
  2.2-3.2 s per request. A query embedding takes ~0.3 s warm (Titan: 0.22 s).
- The corpus is ~10.5-11M tokens, ~$1.3 at ~$0.12 per 1M tokens (third-party price trackers;
  the Pricing API gave no clear figure). Both quotas cap the load at ~20 batches/min, which is
  ~35 min for the corpus on the `eu` pool.
- Through the new `embed.py`: 200 short texts in 3 requests took 3.5 s, 1024 floats each, norm
  1.0, the same text in two different batches got identical vectors. A Cohere query scored 0.59
  against its Cohere-embedded document and ~0.09 against Titan-embedded HotpotQA chunks: vectors
  of the two models do not mix.

## Decision

Embeddings come from **Cohere Embed V4 through the `eu.cohere.embed-v4:0` inference profile**,
1024 dimensions, float. `embed.embed_documents(texts)` sends 96 texts per request as
`search_document`; `embed.embed_query(text)` sends one as `search_query`. Only the `eu.*`
profile is used, so documents and questions stay in EU Regions; `global.*` (a second pool of the
same size) is a documented option, not used.

Ingestion batches across documents: `index.upsert_many(docs)` runs the dedup checks of a whole
shard first (no Bedrock call for `empty`, `unchanged`, `duplicate`), embeds the distinct inputs
of every document that must be written in one go, then writes each document in its own
transaction. `upsert(doc)` is `upsert_many([doc])[0]`, one code path for uploads and the bulk
load. `ingest` runs at most **2** concurrent Lambdas: two workers fill the ~20 requests/min.

The stall also showed that Lambda drops an async event after its retries without a trace, so a
failed upload would simply vanish. `ingest` gets an on-failure destination, the SQS queue
`IngestFailures` (14 days retention), and `make redrive-ingest` (CodeBuild `investigation-jobs`,
`TARGET=redrive-ingest`) re-invokes `ingest` with each stored event (llm-wiki/07). SQS is on the
Free plan list and costs nothing at this volume.

Every embedding is recomputed: the 1,853 Titan-embedded documents are deleted and the corpus is
reloaded after this deploy (vectors of two models are not comparable).

## Consequences

The bulk load is bound by ~20 requests/min of 96 texts instead of ~1 text/s: ~35-40 min
instead of ~18 h. Retrieval quality is expected to be better than Titan's, and documents and
queries are embedded asymmetrically, as the model is trained.
The costs:
- ~$1.3 for the corpus instead of ~$0.19, and ~11M of the 16.2M daily tokens: at most one full
  reload per day.
- Query embeddings share the 20 requests/min pool with the bulk load: search during a load (or
  an eval run) is throttled and slower. Bulk load and eval must not overlap.
- Text leaves `eu-north-1` for other EU Regions (cross-Region profile), and the profile is one
  more moving part in IAM (the profile plus the model in every EU Region, ADR 0017's pattern).
- A shard is embedded entirely before its first write: if Bedrock fails after the retries, the
  Lambda retry re-embeds the whole shard (tokens spent twice; nothing is half-written).
- A query costs ~0.3 s instead of ~0.2 s.

## Alternatives considered

**Keep Titan, slower and with more retries**: no code change, but ~18 h for the corpus, and the
throttling pattern already dropped events once. Right call only with a raised, visible quota.

**Titan batch inference**: half price, no per-minute quota, but the account is not authorized
for it; a support case takes days. Right call for a later, larger reload.

**Local `bge` (fastembed) in the Lambda or CodeBuild**: quota-free, but it puts the model back in
the image (cold start, the main point of ADR 0016 reversed), 384/768 dimensions mean a schema
change, and quality is lower.

**`global.cohere.embed-v4:0`, or both pools**: doubles the throughput, but text may be processed
outside the EU. Worth it if the `eu` pool proves too small.

## Update 2026-10-26

Measured: the full load of 66,555 documents took ~65 min (2026-10-25, 17:29-18:34 UTC by
document `created_at`, [05 Corpora](../05-corpora.md)), not the ~35-40 min estimated above.
