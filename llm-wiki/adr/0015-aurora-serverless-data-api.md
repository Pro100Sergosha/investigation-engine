---
title: Aurora Serverless v2 with the Data API instead of a public RDS instance
status: accepted
date: 2026-10-24
supersedes: 0007; the hosting part of 0002
superseded_by: 0021 (Data API part)
---

# ADR 0015: Aurora Serverless v2 with the Data API instead of a public RDS instance

## Context

ADR 0007 chose RDS `db.t4g.micro` with a public endpoint, loaded and evaluated from the laptop.
Two things changed:
- The project must not depend on the author's computer: bulk loading, corpus generation and
  evaluation run in the cloud (ADR 0018). The laptop-side psycopg path that made a second access
  method look like a cost is gone.
- The $100 credits are the whole budget until the Free-plan account closes, and the demo has to
  survive until the interview. RDS costs about $18/month while idle (instance $0.016/h, public IPv4
  $0.005/h, gp3 storage), which spends the credits in ~5.5 months.

## Decision

Aurora Serverless v2, PostgreSQL 17 with pgvector, minimum capacity **0 ACU** (pauses after 5 idle
minutes), maximum 2-4 ACU for bulk loading and the HNSW build. All access goes through the **RDS Data
API** (HTTPS, IAM-authorized, credentials in a Secrets Manager secret). The cluster sits in the
default VPC with no public access; Lambdas and CodeBuild stay outside any VPC and need no NAT.
Schema and SQL stay as in ADR 0002 (`halfvec` + HNSW, `tsvector` + GIN, `llm_cache`). All database
access goes through `db.py`, which retries `DatabaseResumingException`.

## Consequences

Idle cost is storage only (~$0.1/month at ~1 GB) plus $0.40/month for the secret; active time costs
$0.14 per ACU-hour ($0.07/h at 0.5 ACU). No public database endpoint and no connection-pool problem
from concurrent Lambdas. SQL, ranking and schema are unchanged.
The cost: the first request after a pause waits ~15 s for resume (warm the database before a demo);
Data API limits apply: 1 MB per result, 45 s per statement (long `CREATE INDEX` uses
`continueAfterTimeout`), no `COPY`, so bulk inserts go through `BatchExecuteStatement`; vectors are
sent as text and cast (`'[...]'::halfvec`). The Data API exists only on Aurora, so `db.py` is the
only module that knows about it. There is no local database: pure logic is unit-tested, database
code is exercised against Aurora.

## Alternatives considered

**RDS `db.t4g.micro` (ADR 0007)**: plain Postgres, `COPY`, no resume delay, ~$18/month idle and a
public endpoint.

**RDS with an EventBridge stop/start schedule**: cheaper, but RDS restarts itself after 7 days and
IPv4 and storage are billed anyway; the database may be off when the demo is opened.

**OpenSearch Serverless**: hybrid search built in, $175+/month minimum.

**S3 Vectors + DynamoDB**: almost free, no keyword search, no transactions; an inverted index would
have to be built from scratch.

**Aurora DSQL**: serverless Postgres-compatible, but no pgvector.

**Neon free tier**: $0 and plain Postgres, but not AWS.
