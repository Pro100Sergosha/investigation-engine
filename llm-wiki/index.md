---
title: Investigation Engine Knowledge Base
status: current
last_updated: 2026-10-25
owner: Pro100Sergosha
---

# Investigation Engine Knowledge Base

Read this file first. Then read only the documents relevant to your task.

This wiki is written for a reader with no memory of yesterday. It describes the system **as it
is**, not as it was planned; the plan, schedule and progress (what is done and what is not:
section 0) live in [PLAN.md](../PLAN.md). If the code changed and the document did not, the
document is a bug.

Numbering follows binadar's wiki. A document is written when there is something real to describe,
so gaps in the numbers are deliberate: 03 Data model, 05 Corpora, 09 Evaluation
and 10 Runbook appear with the streams that build them.

## What to read for what task

| If you are working on... | Read |
|---|---|
| Anything, first time | [02 Architecture](02-architecture.md), [CLAUDE.md](../CLAUDE.md), [PLAN.md](../PLAN.md) |
| CDK, AWS resources, deploys, CI | [07 Infrastructure](07-infrastructure.md), ADRs 0010-0013, 0015, 0018, 0019 |
| Search, ranking, embeddings, the database | [02 Architecture](02-architecture.md), [03 Data model](03-data-model.md), ADRs [0002](adr/0002-postgres-pgvector-single-store.md), [0003](adr/0003-hybrid-search-own-rrf-mmr.md), [0015](adr/0015-aurora-serverless-data-api.md), [0016](adr/0016-titan-embeddings-no-model-in-lambda.md), [0022](adr/0022-cohere-embed-v4-batched.md), [0024](adr/0024-partial-hnsw-per-strategy-or-keyword-query.md) |
| LLM calls, the agent, citations | [ADR 0017](adr/0017-bedrock-claude-haiku-llm.md), [ADR 0023](adr/0023-llm-client-own-retry-fallback-cache.md), [ADR 0005](adr/0005-agent-loop-with-citation-validation.md) |
| Datasets, Acme corpus, ingestion, jobs | [05 Corpora](05-corpora.md), [ADR 0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md), [ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md), [ADR 0022](adr/0022-cohere-embed-v4-batched.md) |
| Shared types or stream interfaces | [02 Architecture](02-architecture.md#contracts), [ADR 0014](adr/0014-shared-contracts-parallel-streams.md), `src/engine/models.py` |
| The UI, HTTP routes | [04 API contract](04-api-contract.md) |
| Evaluation: questions, metrics, the runner, results | [09 Evaluation](09-evaluation.md), [ADR 0027](adr/0027-eval-runner-retrieval-sweep-qwen-judge.md), `eval/metrics.py` |
| Something does not work yet or is temporary | [14 Known gaps](14-known-gaps.md) |

## Document index

- [02 Architecture](02-architecture.md): components, data flow, and why each choice was made
- [03 Data model](03-data-model.md): tables, indexes, write paths, how to change the schema
- [04 API contract](04-api-contract.md): HTTP routes, JSON shapes, upload/update/delete flow
- [05 Corpora](05-corpora.md): HotpotQA source, dedup rules, real counts, S3 shard layout
- [07 Infrastructure](07-infrastructure.md): AWS project, CDK stacks, CI/CD, deploying, cost
- [09 Evaluation](09-evaluation.md): question set and format, metrics, configurations, how to run, cost
- [14 Known gaps](14-known-gaps.md): what does not work yet, or works on a temporary arrangement

## Architecture decisions

[ADR index](adr/). Numbered, immutable once accepted. A reversal is a new ADR that supersedes the
old one, and the old one gets `status: superseded` and `superseded_by: 00XX`. Template:
[0000](adr/0000-template.md).

| ADR | Decision |
|---|---|
| [0001](adr/0001-own-code-no-rag-frameworks.md) | Own small code, no RAG or web frameworks |
| [0002](adr/0002-postgres-pgvector-single-store.md) | Postgres with pgvector as the single store (hosting part replaced by 0015) |
| [0003](adr/0003-hybrid-search-own-rrf-mmr.md) | Hybrid search with hand-written RRF and MMR (embedding model replaced by 0016) |
| [0004](adr/0004-groq-llm-with-postgres-cache.md) | Groq as the LLM, Bedrock fallback, one cached client. **Superseded by 0017** |
| [0005](adr/0005-agent-loop-with-citation-validation.md) | Own agent loop with tool calling and server-side citation validation |
| [0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md) | HotpotQA for scale and labels, synthetic Acme corpus for investigation |
| [0007](adr/0007-serverless-lambda-no-vpc-public-rds.md) | Serverless on AWS, Lambdas outside a VPC, publicly reachable RDS. **Superseded by 0015** |
| [0008](adr/0008-function-url-not-api-gateway.md) | Lambda Function URL instead of API Gateway, UI served by the same Lambda |
| [0009](adr/0009-one-container-image-for-all-lambdas.md) | One container image for all Lambdas, x86_64. **Superseded by 0016** |
| [0010](adr/0010-cdk-single-production-environment.md) | CDK in Python, production as the only environment (stack layout replaced by 0020) |
| [0011](adr/0011-free-plan-aws-project.md) | A Free-plan AWS project in eu-north-1, accessed with `aws login` |
| [0012](adr/0012-codebuild-cicd-via-codeconnections.md) | CD runs in CodeBuild, triggered by GitHub through CodeConnections |
| [0013](adr/0013-branch-pr-workflow-and-ci.md) | Branches and pull requests, CI on PRs, deploy on main |
| [0014](adr/0014-shared-contracts-parallel-streams.md) | Shared dataclass contracts and parallel workstreams |
| [0015](adr/0015-aurora-serverless-data-api.md) | Aurora Serverless v2 with the Data API instead of a public RDS instance (default-VPC part replaced by 0019, Data API part by 0021) |
| [0016](adr/0016-titan-embeddings-no-model-in-lambda.md) | Bedrock Titan Text Embeddings V2, no model inside the Lambda image (embedding model replaced by 0022) |
| [0017](adr/0017-bedrock-claude-haiku-llm.md) | All LLM calls on Amazon Bedrock, Claude Haiku as the main model |
| [0018](adr/0018-cloud-only-ingestion-and-jobs.md) | Nothing runs on the author's computer: S3-triggered ingestion and CodeBuild jobs |
| [0019](adr/0019-isolated-vpc-schema-custom-resource.md) | Aurora in its own isolated VPC, schema applied by a custom resource on deploy (replaces the default-VPC part of 0015; VPC and schema runner replaced by 0021) |
| [0020](adr/0020-data-stack-split-by-lifecycle.md) | Stacks split by lifecycle: VPC, Aurora, secret and schema in a separate data stack (replaces the stack layout of 0010; schema location replaced by 0021) |
| [0021](adr/0021-aurora-express-iam-auth.md) | Aurora express configuration (Free plan), IAM-authenticated Postgres connections instead of the Data API, no VPC, no secret |
| [0022](adr/0022-cohere-embed-v4-batched.md) | Cohere Embed V4 on Bedrock (`eu.*` profile), 96 texts per request and whole shards per call, instead of Titan; failed ingest events kept in an SQS queue |
| [0023](adr/0023-llm-client-own-retry-fallback-cache.md) | One LLM client with its own retry loop, Haiku-only fallback and a Postgres cache |
| [0024](adr/0024-partial-hnsw-per-strategy-or-keyword-query.md) | A partial HNSW index per chunking strategy, and OR semantics for keyword search |
| [0027](adr/0027-eval-runner-retrieval-sweep-qwen-judge.md) | Own eval runner: retrieval sweep without an LLM, Qwen3 judge, Haiku pacing, results via S3 |
