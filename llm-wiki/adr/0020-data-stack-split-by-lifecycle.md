---
title: Stacks split by lifecycle, a separate data stack
status: accepted
date: 2026-10-24
supersedes: the stack layout of 0010
superseded_by: 0021 (schema location only)
---

# ADR 0020: Stacks split by lifecycle, a separate data stack

## Context

ADR 0010 put the whole application in one stack, `Investigation-prod`, which CodeBuild deploys on
every merge to `main`. Before Aurora is deployed for the first time (ADR 0015, 0019), that stack
would hold the database next to code that changes every few hours. A code deploy must never be able
to replace the database: one wrong property (an engine setting, a subnet group, a renamed construct)
turns into a replacement, and the PR diff does not warn about it, because `make diff-pr` uses
`cdk diff --method=template` (the PR role may not create change sets) and a template diff does not
show replacements. Deletion protection and the `SNAPSHOT` removal policy limit the damage, but a
failed replacement in the middle of a merge still blocks every following deploy. binadar splits its
stacks by lifecycle for the same reason.

## Decision

Three stacks in `cdk/app.py`:

- `Investigation-Data-prod` (`DataStack`): what holds data and rarely changes. The isolated VPC,
  the Aurora Serverless v2 cluster (deletion protection, `RemovalPolicy.SNAPSHOT`), its generated
  secret, and the schema custom resource (`SchemaFn` + provider, ADR 0019).
- `Investigation-prod` (`AppStack`): what changes with the code. The `api` and `ingest` Lambdas,
  the Function URL, the documents bucket **and its S3 notifications**, the `investigation-jobs`
  project, and every IAM grant (Data API, secret, Bedrock, S3).
- `Investigation-Cicd-prod`: unchanged, deployed by hand.

`AppStack` receives the cluster object; CDK turns the cluster ARN and secret ARN into
CloudFormation exports of the data stack and `Fn::ImportValue` in the app stack. Reference strength
is set to `strong` in `cdk/cdk.json`: CloudFormation then refuses to delete an export that is still
imported. The Makefile targets `diff`, `diff-pr`, `deploy` and `verify` cover both stacks, data
first; `.codebuild/deploy.yml` calls those targets, so the merge deploy needs no change.

## Consequences

- A merge that touches only code cannot change the cluster, and a change to the database shows up
  as a separate stack in the diff, where it is easy to notice.
- Exports are a contract between the stacks. Never remove an export that the app stack still
  imports in the same deploy; CloudFormation rejects it ("cannot be deleted as it is in use"). A
  removal is two deploys: first stop importing, then remove.
- The bucket stays in the app stack together with its notifications: a bucket in the data stack
  notifying `ingest` in the app stack, with `ingest` reading the bucket name, makes the two stacks
  depend on each other (a cycle CDK refuses to synthesize). The bucket is `RETAIN`, so losing it in
  a bad deploy is still not possible.
- Grants stay with the grantees (app stack), so the data stack has no reference to anything in the
  app stack; dependencies point one way only.
- Two stacks to deploy, diff and verify. CDK deploys them in dependency order; the first deploy of
  the data stack (cluster + writer, 10-20 min) and the image build share one CodeBuild run and its
  30-minute timeout (tracked in 14 Known gaps).

## Alternatives considered

**One stack, as in ADR 0010**: fewer moving parts and no exports, but a code merge can replace the
database and the template diff would not show it. Acceptable only for stateless stacks.

**Weak references (`Fn::GetStackOutput`)**: no export lock-in, the producer can change freely, but
nothing stops a data-stack deploy from breaking the app stack's references. Right call once
resources are renamed often; here the two ARNs do not change.

**SSM parameters instead of exports**: decouples deploys completely, but adds parameters to manage
and loses CloudFormation's check that an imported value still exists.

**Bucket in the data stack too**: it holds data, but its notifications must point at `ingest`, which
creates the cycle above. Splitting the notifications into a custom resource was more code for a
bucket that is already `RETAIN`.
