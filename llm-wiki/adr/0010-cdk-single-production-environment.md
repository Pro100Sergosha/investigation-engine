---
title: CDK in Python, production as the only environment
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: 0020 (stack layout only)
---

# ADR 0010: CDK in Python, production as the only environment

## Context

All infrastructure must be reproducible and reviewable, and explained at the interview. The team is
one person with five days. binadar already runs on CDK (Python) with a Makefile and a single
production stage, so the tool and workflow are known.

## Decision

AWS CDK v2 in Python, all infrastructure in `cdk/app.py`: `Investigation-Cicd-prod` (CodeBuild
projects, ADR 0012) and `Investigation-prod` (the application). `make diff` before every deploy,
`make deploy` to apply. There is no dev or staging stage: a merge to `main` deploys to production
(ADR 0013). Every resource is tagged `Project=investigation-engine`.

## Consequences

Infrastructure is code in the same language as the backend, diffable in review, and one command to
reproduce. One environment means nothing to keep in sync.
The cost: every merge is a production change, so `main` must always be deployable and the smoke
check after deploy is the only safety net after the tests. Stateful resources (RDS) need explicit
removal/retention policies so a bad deploy cannot drop data.

## Alternatives considered

**AWS SAM**: less code for Lambda-only stacks; lost because CDK is already known from binadar and
handles RDS, S3 and IAM equally well.

**Terraform**: provider-neutral, but a second language and state backend to manage.

**A staging stage**: doubles RDS cost, not worth it for a five-day MVP.
