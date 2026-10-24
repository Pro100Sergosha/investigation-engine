---
title: Serverless on AWS, Lambdas outside a VPC, publicly reachable RDS
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0007: Serverless on AWS, Lambdas outside a VPC, publicly reachable RDS

## Context

The whole system runs on AWS on a Free-plan project (ADR 0011). Request volume is a demo and an
evaluation run, so pay-per-request compute is nearly free. The Lambdas must reach Groq on the public
internet and Postgres. A Lambda inside a VPC needs a NAT Gateway (~$32/month) to reach the internet,
which alone would exceed the rest of the bill.

## Decision

Lambda for compute (`api` behind a Function URL, `ingest` triggered by S3 uploads), all **outside**
any VPC. RDS Postgres (`db.t4g.micro`, 20 GB gp3) is publicly accessible, with
`rds.force_ssl=1`, a long random password in SSM Parameter Store, and an application user without
superuser rights. Bulk loading and evaluation run from the laptop against the same database.

## Consequences

No NAT, no VPC to design, idle compute cost near zero; the laptop and Lambda use the same
connection code. Estimated ~$21/month (almost all RDS) from credits.
The cost: the database endpoint is reachable from the internet and protected by TLS and credentials
only. Lambda IPs are not fixed, so a security group cannot narrow it. README documents the
production path: VPC + RDS Proxy + NAT or VPC endpoints, IAM database auth.

## Alternatives considered

**Lambda in a VPC with NAT**: the textbook answer, rejected on cost.

**Neon free Postgres**: $0 and no public-RDS trade-off; the fallback if credits or the free plan
become a problem (same schema, `pg_dump`).

**Aurora Serverless v2 with Data API**: no VPC needed and scales to zero, but a second SQL dialect
path (Data API JSON) next to psycopg on the laptop.
