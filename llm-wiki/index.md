---
title: Investigation Engine Knowledge Base
status: current
last_updated: 2026-10-24
owner: Pro100Sergosha
---

# Investigation Engine Knowledge Base

Read this file first. Then read only the documents relevant to your task.

This wiki is written for a reader with no memory of yesterday. It describes the system **as it
is**, not as it was planned; the plan and schedule live in [PLAN.md](../PLAN.md). If the code changed
and the document did not, the document is a bug.

Numbering follows binadar's wiki. A document is written when there is something real to describe,
so gaps in the numbers are deliberate: 03 Data model, 04 API contract, 05 Corpora, 09 Evaluation
and 10 Runbook appear with the streams that build them.

## What to read for what task

| If you are working on... | Read |
|---|---|
| Anything, first time | [02 Architecture](02-architecture.md), [CLAUDE.md](../CLAUDE.md), [PLAN.md](../PLAN.md) |
| CDK, AWS resources, deploys, CI | [07 Infrastructure](07-infrastructure.md), ADRs 0007-0013 |
| Search, ranking, embeddings | [02 Architecture](02-architecture.md), [ADR 0002](adr/0002-postgres-pgvector-single-store.md), [ADR 0003](adr/0003-hybrid-search-own-rrf-mmr.md) |
| LLM calls, the agent, citations | [ADR 0004](adr/0004-groq-llm-with-postgres-cache.md), [ADR 0005](adr/0005-agent-loop-with-citation-validation.md) |
| Datasets, Acme corpus | [ADR 0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md) |
| Shared types or stream interfaces | [ADR 0014](adr/0014-shared-contracts-parallel-streams.md), `src/engine/models.py` |
| Something does not work yet or is temporary | [14 Known gaps](14-known-gaps.md) |

## Document index

- [02 Architecture](02-architecture.md): components, data flow, and why each choice was made
- [07 Infrastructure](07-infrastructure.md): AWS project, CDK stacks, CI/CD, deploying, cost
- [14 Known gaps](14-known-gaps.md): what does not work yet, or works on a temporary arrangement

## Architecture decisions

[ADR index](adr/). Numbered, immutable once accepted. A reversal is a new ADR that supersedes the
old one, and the old one gets `status: superseded` and `superseded_by: 00XX`. Template:
[0000](adr/0000-template.md).

| ADR | Decision |
|---|---|
| [0001](adr/0001-own-code-no-rag-frameworks.md) | Own small code, no RAG or web frameworks |
| [0002](adr/0002-postgres-pgvector-single-store.md) | Postgres with pgvector as the single store |
| [0003](adr/0003-hybrid-search-own-rrf-mmr.md) | Hybrid search with hand-written RRF and MMR |
| [0004](adr/0004-groq-llm-with-postgres-cache.md) | Groq as the LLM, Bedrock fallback, one cached client |
| [0005](adr/0005-agent-loop-with-citation-validation.md) | Own agent loop with tool calling and server-side citation validation |
| [0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md) | HotpotQA for scale and labels, synthetic Acme corpus for investigation |
| [0007](adr/0007-serverless-lambda-no-vpc-public-rds.md) | Serverless on AWS, Lambdas outside a VPC, publicly reachable RDS |
| [0008](adr/0008-function-url-not-api-gateway.md) | Lambda Function URL instead of API Gateway, UI served by the same Lambda |
| [0009](adr/0009-one-container-image-for-all-lambdas.md) | One container image for all Lambdas, x86_64 |
| [0010](adr/0010-cdk-single-production-environment.md) | CDK in Python, production as the only environment |
| [0011](adr/0011-free-plan-aws-project.md) | A Free-plan AWS project in eu-north-1, accessed with `aws login` |
| [0012](adr/0012-codebuild-cicd-via-codeconnections.md) | CD runs in CodeBuild, triggered by GitHub through CodeConnections |
| [0013](adr/0013-branch-pr-workflow-and-ci.md) | Branches and pull requests, CI on PRs, deploy on main |
| [0014](adr/0014-shared-contracts-parallel-streams.md) | Shared dataclass contracts and parallel workstreams |
