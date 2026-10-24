---
title: Nothing runs on the author's computer: S3-triggered ingestion and CodeBuild jobs
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0018: Nothing runs on the author's computer: S3-triggered ingestion and CodeBuild jobs

## Context

The first plan bulk-loaded HotpotQA, generated the Acme corpus and ran the evaluation from the
laptop. That makes the system unreproducible without one specific machine and its local state. The
deployed system should be able to rebuild its data and its evaluation from the repository alone.

## Decision

- **Ingestion has one path.** Every document, whether uploaded in the UI or part of the bulk corpus,
  lands in the S3 bucket and triggers the `ingest` Lambda: parse -> sha256 dedup -> chunk -> Titan
  embeddings -> Data API insert. The bulk corpus arrives as JSONL shards of ~500 records. Reserved
  concurrency on `ingest` (~5) protects the Bedrock quota and the database.
- **One-off and long jobs run in CodeBuild project `investigation-jobs`**, started with
  `aws codebuild start-build --project-name investigation-jobs` and a `TARGET` variable that names a
  Makefile target: `dataset` (download HotpotQA, dedup, write shards to S3), `acme` (generate the
  Acme corpus with Bedrock, write it to S3), `eval CONFIG=...` (run the question set, write results
  to S3). CodeBuild allows up to 8 h per build; Lambda stops at 15 min.
- The laptop is needed only for git and `aws login`. Generated artifacts that belong in the repo
  (Acme corpus, evaluation results) are downloaded from S3 and committed through a normal PR.

## Consequences

Data and evaluation are rebuilt from the repository by starting builds; uploads and bulk loading
exercise the same code; long runs have no Lambda timeout.
The cost: a third CodeBuild project and its role; CodeBuild minutes beyond the 100 free per month
bill from credits (~$0.005/min on small); feedback is slower than a local run; artifacts go through
S3 before reaching the repo.

## Alternatives considered

**Laptop scripts (first plan)**: fastest to write, not reproducible without the author's machine.

**A Lambda per job**: no new project type, but the 15-minute limit breaks the evaluation sweep and
large downloads.

**Step Functions**: good for fan-out and retries, more resources and JSON to explain for jobs that
run a handful of times.

**Bedrock batch inference for the bulk load**: cheaper per token, asynchronous, more moving parts.
