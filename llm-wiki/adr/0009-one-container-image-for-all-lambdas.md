---
title: One container image for all Lambdas, x86_64
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0009: One container image for all Lambdas, x86_64

## Context

Query embedding runs inside the `api` Lambda (fastembed + onnxruntime + numpy + the bge-small
model). Together they sit close to the 250 MB unzipped limit of zip deployments. binadar builds
zip bundles with uv cross-platform ARM64 wheels and no Docker, but carries no ML runtime.

## Decision

One Docker image (`Dockerfile`, base `public.ecr.aws/lambda/python:3.12`, dependencies from
`uv.lock`) shared by every function; each function picks its handler through `cmd` in the CDK
stack. Architecture x86_64. The embedding model is baked into the image and loaded at module level,
once per cold start.

## Consequences

10 GB image limit instead of 250 MB, one build for all functions, identical code paths.
The cost: cold starts of a few seconds (image pull + model load), documented as expected
first-request latency; Docker is required to build (CI has it; local builds need Docker Desktop);
x86_64 is about 20% more expensive than ARM64, irrelevant inside the free tier.

## Alternatives considered

**Zip + uv cross-platform wheels (binadar)**: no Docker, smaller cold start, but no room for the ML
runtime.

**ARM64 image**: cheaper, but building ARM images on Windows/x86 CI runs under emulation and is slow.

**Bedrock Titan embeddings instead of a local model**: removes the model from Lambda, but the
60k-chunk corpus would be embedded through a rate-limited per-text API and every eval query costs
credits.
