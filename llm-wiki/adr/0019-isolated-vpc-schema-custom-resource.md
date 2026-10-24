---
title: Aurora in its own isolated VPC, schema applied by a custom resource on deploy
status: accepted
date: 2026-10-24
supersedes: the default-VPC part of 0015
superseded_by: none
---

# ADR 0019: Aurora in its own isolated VPC, schema applied by a custom resource on deploy

## Context

Stream A adds the data path to `Investigation-prod`: Aurora Serverless v2 (ADR 0015), the documents
bucket, the `ingest` Lambda and the `investigation-jobs` project (ADR 0018). Three questions had no
answer yet:

- **Where the cluster lives.** An Aurora cluster must be in a VPC with subnets in two AZs, even
  though nothing connects to it over the network: Lambdas and CodeBuild use the Data API (HTTPS) and
  stay outside any VPC. ADR 0015 said "the default VPC". Rule: no NAT Gateway, ever.
- **How the schema gets into the database.** `main` must be deployable with zero manual steps, so
  the first deploy has to create the tables. Constraints (checked in the AWS docs): the Data API runs
  **one statement per call** (multi-statements are rejected), 45 s per statement, and a paused
  cluster answers `DatabaseResumingException` for ~15 s. The deploy CodeBuild role lives in
  `Investigation-Cicd-prod`, which only the owner deploys by hand, and has no database access.
- **CORS on the bucket.** The browser `PUT`s uploads straight to S3 with a presigned URL from the
  `api` Lambda, so the bucket must answer the CORS preflight from the Function URL origin.

## Decision

**A new VPC with two isolated subnets** (`PRIVATE_ISOLATED`, `nat_gateways=0`, eu-north-1a/b): no
internet gateway, no route out, no NAT. It costs nothing. The cluster's security group has no
ingress rules; the Data API does not need any.

**Schema: a CloudFormation custom resource in the same stack.** `sql/schema.sql` holds the whole
schema, every statement idempotent (`IF NOT EXISTS`). `scripts/schema.py` splits it on `;` and
runs the statements one by one through `rds-data:ExecuteStatement`, retrying every error for up to
~3 minutes (resume, a cluster that just became available). The CDK app inlines that file as the code
of a small Python 3.12 Lambda (`SchemaFn`, behind a `cr.Provider`) and passes the SQL text as a
property of the `Schema` custom resource, which depends on the cluster and its writer. CloudFormation
therefore runs it on the first deploy and again whenever the file changes; Delete does nothing (the
data outlives the resource). `make schema` runs the same code by hand, for repairs, in the jobs
project.

**CORS: `PUT` from any origin (`*`).** CORS tells a *browser* which pages may make the call; it is
not access control (curl ignores it). What authorizes the upload is the presigned URL's signature
(the `api` role, `s3:PutObject` on `uploads/*` only, 5 minutes). Pinning the Function URL origin
would be a circular reference in one stack (the bucket would need the URL, the `api` function
already needs the bucket name) or a second deploy, for no security gain.

## Consequences

- The stack is self-contained: no dependency on a default VPC existing, no VPC lookup, and the DB
  subnets have no internet route even by accident. CDK still validates the two AZs against the
  Region (an AZ lookup), so `cdk/cdk.context.json` is committed: CI synthesizes without credentials.
- The schema is part of the deploy: a merge that changes `sql/schema.sql` changes the database,
  and a broken statement fails the deploy (CloudFormation rolls the stack back; the statements
  that already ran stay, which is safe because all are idempotent). The deploy role
  needs no new permission and `Investigation-Cicd-prod` does not change.
- The cost: three more Lambdas in the stack (`SchemaFn`, the Provider framework, CDK's bucket
  notifications handler) and their log groups. Only *additive* changes work through this path:
  `CREATE TABLE IF NOT EXISTS` never alters an existing table, so a column change needs an explicit
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, and any new index over a loaded table may exceed the
  45 s statement limit (the HNSW index is created while the table is empty for that reason). A real
  SQL error fails the deploy only after the ~3 minute retry window.
- If a Lambda ever has to go *into* the VPC, it gets no internet and needs VPC endpoints (still no
  NAT). Nothing planned needs that.
- Any web page can make a browser `PUT` to the bucket, but only with a valid presigned URL, which
  only the `api` Lambda issues.

## Alternatives considered

**Default VPC via `Vpc.from_lookup`**: no VPC resources in the stack, but a lookup result to commit,
a hidden dependency on the account's default VPC, and DB subnets that route to an internet gateway.
Right call if the account had a shared VPC that other systems use.

**`AwsCustomResource` calling `rds-data:ExecuteStatement`**: no own Lambda code, but one resource
per statement (six and counting), the SQL duplicated into the template statement by statement, and
no retry on `DatabaseResumingException`, so any schema change after the first pause fails the deploy.

**`make schema` in `.codebuild/deploy.yml` after `make deploy`**: no custom resource, but the deploy
role in `Investigation-Cicd-prod` would need Data API and secret access, which only the owner can add
by hand (`make deploy-cicd`), and it would run on every deploy instead of on change.

**A migrations tool** (Alembic, Flyway): versioned up/down migrations, but a dependency and a
framework for a schema of three tables; revisit if the schema starts changing destructively.

**CORS limited to the Function URL origin**: same security, needs the URL domain before the bucket,
so either a second deploy or a hard-coded value that breaks when the function is replaced.
