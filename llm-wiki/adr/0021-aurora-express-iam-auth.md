---
title: Aurora express configuration, IAM-authenticated Postgres connections instead of the Data API
status: accepted
date: 2026-10-24
supersedes: the Data API part of 0015; the VPC and schema-runner parts of 0019; the schema location in 0020
superseded_by: none
---

# ADR 0021: Aurora express configuration, IAM-authenticated Postgres connections instead of the Data API

## Context

The first deploy of `Investigation-Data-prod` (2026-10-24) failed creating the cluster:

> To use Aurora clusters with free plan accounts you need to set WithExpressConfiguration. To
> remove all limitations, upgrade your account plan.

Upgrading the plan is not an option (ADR 0011). An Aurora cluster with *express configuration*
(checked in the Aurora User Guide, "Create with express configuration") differs from the cluster in
ADR 0015 and 0019:

- It is **not in any VPC**. It is reached through an *internet access gateway*: the PostgreSQL wire
  protocol over TLS on port 5432, from anywhere, managed by AWS. It cannot be turned off.
- The master user logs in **only with IAM database authentication** (a token signed from an IAM
  role, valid 15 minutes). No master password, no Secrets Manager secret.
- The **Data API** can be enabled after creation, but not for the master user: it needs a separate
  database user with a password, which can only be created by connecting over the wire first.
- The engine version is the default (17.9 on 2026-10-24, so pgvector 0.8 and `halfvec` are there),
  and the cluster creates its own serverless writer. CloudFormation has the create-only property
  `WithExpressConfiguration`; the CDK L2 `DatabaseCluster` cannot express it.

So the Data API would need a password user, a secret, and wire-protocol bootstrap code anyway: two
ways into the database instead of one.

## Decision

**Express cluster, every caller connects over the wire with an IAM token.**

- `DataStack` holds one `CfnDBCluster` (`WithExpressConfiguration`, identifier `investigation`,
  database `investigation`, deletion protection, `DeletionPolicy: Snapshot`). No VPC, no secret.
  It exports the writer endpoint and the cluster resource id.
- `engine.db` (`pg8000`, pure Python) signs a token with
  `boto3.client("rds").generate_db_auth_token(host, 5432, user)` and opens a TLS connection with it
  as the password. The connection is kept per Lambda container and reopened once if it died.
  Statements use `:name` parameters (`pg8000.native`), never formatted values.
- Two database users. `postgres` (the master) is used only by the schema custom resource, which owns
  the tables. `app` (`LOGIN`, `rds_iam`, `SELECT/INSERT/UPDATE/DELETE` only) is what `api`, `ingest`
  and the jobs log in as. `sql/schema.sql` creates `app` and its grants idempotently.
- IAM: `rds-db:connect` on `arn:aws:rds-db:...:dbuser:<cluster resource id>/app` for `api`, `ingest`
  and `investigation-jobs`; on `.../postgres` for `SchemaFn` only.
- The schema custom resource moves to `Investigation-prod`: `SchemaFn` runs the app image
  (`engine.handlers.schema`) and `engine.db`. It runs the whole `schema.sql` in one call (pg8000
  uses the simple query protocol without parameters), so the file is one implicit transaction.

## Consequences

- No secrets at all: the database login is an IAM token, issued only to roles that hold
  `rds-db:connect` for that user. No password to leak or rotate.
- The Data API limits are gone (1 MB per result, 45 s per statement, no `COPY`, one statement per
  call). Bulk loads can use multi-row inserts or `COPY`; types like `halfvec` behave as in any
  Postgres.
- `app` cannot create, alter or drop tables: an injected statement cannot destroy the schema.
- The cost: the database endpoint is reachable from the internet. Authentication is IAM-only (no
  password exists to guess) and TLS is enforced by the gateway, but the attack surface is a public
  endpoint, not a private one. Accepted on the Free plan, which allows nothing else.
- The cost: connection handling is our code. A paused cluster (0 ACU) resumes on the first
  connection (~15 s); `connect` retries for about a minute. A statement that fails because its
  socket died is retried once on a new connection, so writes must be idempotent.
- The cost: a new runtime dependency (`pg8000`, plus `scramp`). Hand-writing the Postgres wire
  protocol and SCRAM is not reasonable.
- The data stack changes even less (one resource), but the schema now changes with the app stack.
  The cluster itself still cannot be replaced by a code deploy, which is what ADR 0020 is for.
- Capacity: express sets its own ACU range at creation; the 0-4 ACU range is applied by a later
  update of the same resource, once the default is known.
- `make schema` (repair by hand through the jobs project) is gone: the jobs log in as `app`, which
  may not change the schema. A repair is a deploy that changes `schema.sql`.

## Alternatives considered

**Express cluster + Data API**: keeps the `db.py` design of ADR 0015, but needs a password user
created over the wire with an IAM token, a Secrets Manager secret ($0.40/month) for it, and still
carries the Data API limits. Two access paths for the same database.

**Upgrade the account plan** to create a regular cluster in a private VPC: forbidden (ADR 0011).

**RDS for PostgreSQL (not Aurora) or another database service**: not checked against the Free
plan, and none scales to zero like Aurora Serverless v2. Not worth re-planning the storage layer
five days before the deadline.

## Update 2026-10-24

The first deploy with this decision failed: "the express configuration feature doesn't support
creating an initial database. Remove the database-name parameter". The Aurora User Guide's settings
table says the initial database name and deletion protection can be set "during or after the
creation"; the database name cannot. The cluster is therefore created with only its identifier and
`WithExpressConfiguration`, and uses the default database `postgres`. Deletion protection (likely
affected the same way, not tested at create) and the 0-4 ACU range are applied by a later update of
the same resource. Until then the cluster is protected only by `DeletionPolicy: Snapshot`.

The create with only the identifier succeeded. Express chose 0-4 ACU with auto-pause after 300 s,
backups for 1 day, IAM auth, `VPCNetworkingEnabled: false`, `InternetAccessGatewayEnabled: true`,
engine 17.9, writer `investigation-instance-1`, and no deletion protection. Deletion protection and
the (unchanged) capacity range are now set by an update of the same resource.
