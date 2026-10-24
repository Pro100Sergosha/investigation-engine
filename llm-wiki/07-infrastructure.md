---
title: Infrastructure
status: current
last_updated: 2026-10-24
owner: Pro100Sergosha
---

# 07 Infrastructure

## AWS project

| | |
|---|---|
| Account | `988277499209`, an AWS *project* (new AWS experience) on the **Free plan** |
| Region | `eu-north-1` (Stockholm), fixed by the project. Only CloudFront, WAF and their logs may use `us-east-1` |
| Credits | $100, plan expires 2027-04-24; then the account closes instead of billing |
| Lambda concurrency quota | 400 |
| CLI access | `aws login --profile investigation` (12 h, renews up to 90 days). Profile in `~/.aws/config`, region set |

Why this account and not binadar's or the first one: [ADR 0011](adr/0011-free-plan-aws-project.md).
Staying on the Free plan is a hard requirement. Before adding a service, check the
[supported services list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html);
IAM Identity Center and Organizations are **not** supported and enabling them upgrades the plan.
Check the plan any time:

    PYTHONUTF8=1 aws freetier get-account-plan-state --region us-east-1 --profile investigation

## Stacks

| Stack | Contents | Deployed by | State |
|---|---|---|---|
| `CDKToolkit` | CDK bootstrap (S3 assets bucket, ECR repo, `cdk-hnb659fds-*` roles), qualifier `hnb659fds` | `make bootstrap`, once | **deployed** 2026-10-24 |
| `Investigation-Cicd-prod` | CodeBuild projects `investigation-pr-diff` and `investigation-deploy`, their roles and log groups (1 month) | `make deploy-cicd`, by hand only | **deployed** 2026-10-24 |
| `Investigation-prod` | the application, see [below](#application-stack) | CodeBuild on push to `main` | **deployed** (`api` only); the data path below deploys with its PR |

Outside CloudFormation, created once with the CLI:
- CodeConnections connection `investigation-github`
  (`arn:aws:codeconnections:eu-north-1:988277499209:connection/f4261920-...`), confirmed in the
  console (Developer Tools > Settings > Connections > Update pending connection).
- CodeBuild account-level source credential for GitHub pointing at that connection
  (`aws codebuild import-source-credentials --server-type GITHUB --auth-type CODECONNECTIONS
  --token <connection-arn>`). The projects inherit it.
- Gotcha: CodeBuild checks the project role's access to the connection while creating the project
  and its webhook. CDK's role `DefaultPolicy` is created in parallel with the project (no
  `DependsOn`), so the first deploys failed with "not authorized to access connection". The
  connection and `sts:AssumeRole` permissions are therefore inline in the role itself.
- SSM SecureString `/investigation/github-token`: fine-grained GitHub token, this repo only,
  *Pull requests: read and write*. Used only to post the PR diff comment.

Every resource is tagged `Project=investigation-engine` at the app level.

## Application stack

`Investigation-prod` (`AppStack` in `cdk/app.py`). Decisions: [ADR 0015](adr/0015-aurora-serverless-data-api.md),
[ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md), [ADR 0019](adr/0019-isolated-vpc-schema-custom-resource.md).

| Resource | Configuration |
|---|---|
| VPC `Vpc` | two `PRIVATE_ISOLATED` subnets (eu-north-1a/b), no internet gateway, `nat_gateways=0`. Exists only because Aurora must live in a VPC |
| Aurora cluster `Db` | PostgreSQL 17.9, one Serverless v2 writer, **0-4 ACU** (pauses after 5 idle minutes), **Data API on**, database `investigation`, not publicly accessible, security group without ingress, backups 1 day, deletion protection on, `removal_policy=SNAPSHOT` |
| Secret `Db/Secret` | generated credentials of user `postgres` (Secrets Manager, $0.40/month), read by the Data API callers |
| Bucket `Documents` | all public access blocked, SSL enforced, `RETAIN`, CORS `PUT` from `*` (presigned browser uploads, [ADR 0019](adr/0019-isolated-vpc-schema-custom-resource.md)). Prefixes: `uploads/` (UI), `bulk/` (JSONL shards), `jobs/` (job outputs, inert) |
| S3 events | `ObjectCreated` on `uploads/` and `bulk/` -> `ingest` (asynchronous invoke) |
| Lambda `api` | image, `engine.handlers.api`, x86_64, 1024 MB, 90 s, Function URL (output `ApiUrl`) |
| Lambda `ingest` | image, `engine.handlers.ingest`, x86_64, 1024 MB, 15 min, **reserved concurrency 5**: throttled S3 events wait in Lambda's async queue (up to 6 h) instead of overloading Bedrock and the database |
| CodeBuild `investigation-jobs` | see [Jobs](#jobs) |
| Custom resource `Schema` | Lambda `SchemaFn` + `cr.Provider`, see [Database schema](#database-schema) |

Environment of `api`, `ingest` and the jobs project (names and ARNs, no secrets): `CLUSTER_ARN`,
`SECRET_ARN`, `DB_NAME`, `BUCKET`. `src/engine/config.py` reads them (empty defaults for tests).

Permissions (least privilege, no `*` actions):

| Principal | Data API + secret | Bedrock | S3 |
|---|---|---|---|
| `api` | yes | Titan V2, gpt-oss-120b, Qwen3-235B, Claude Haiku (`eu.*`) | `PutObject` on `uploads/*` (to presign uploads) |
| `ingest` | yes | Titan V2 only (it embeds, it never calls an LLM) | `GetObject` on `uploads/*`, `bulk/*` |
| `investigation-jobs` | yes | same as `api` | `GetObject`, `PutObject` on the bucket, `ListBucket` |
| `SchemaFn` | yes | - | - |

- Data API access is `cluster.grant_data_api_access`: `rds-data:ExecuteStatement`,
  `BatchExecuteStatement`, `Begin/Commit/RollbackTransaction` on the cluster, plus `GetSecretValue`
  and `DescribeSecret` on the secret.
- Bedrock: `InvokeModel` and `InvokeModelWithResponseStream`, which also authorize `Converse` and
  `ConverseStream` (there is no separate Converse action). In-Region models by foundation-model ARN.
  Claude Haiku needs two statements: the `eu.anthropic.claude-haiku-*` inference profile in
  eu-north-1, and `arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-*` (every EU Region
  the profile routes to) with the condition `bedrock:InferenceProfileArn` = that profile, so the
  model can be called only through the profile.
- IAM is not quota: on 2026-10-24 the account's Bedrock quotas were 0 (Haiku cross-Region RPM/TPM
  adjustable; gpt-oss-120b and Qwen3 not adjustable) and Titan calls were throttled.

### Database schema

`sql/schema.sql` ([03 Data model](03-data-model.md)) is applied by the `Schema` custom resource:
its properties carry the SQL text, so CloudFormation sends *Create* on the first deploy and *Update*
whenever the file changes; *Delete* does nothing. The handler is `scripts/schema.py`, inlined as
the code of `SchemaFn` (Python 3.12, 5 min): it splits the file on `;` and runs each statement with
`rds-data:ExecuteStatement` (the Data API rejects several statements in one call), retrying every
error every 10 s for ~3 minutes, which covers `DatabaseResumingException` of a paused cluster. The
resource depends on the cluster and its writer instance. Nothing manual is needed after a merge.

By hand, for repairs: `TARGET=schema` in the jobs project (`make schema` reads `CLUSTER_ARN`,
`SECRET_ARN`, `DB_NAME` from the environment).

### Jobs

CodeBuild `investigation-jobs`: GitHub source through the same connection and account-level source
credential as the CI/CD projects, **no webhook**, `standard:7.0`, small, not privileged, 2 h
timeout, one build at a time (two jobs would share the Bedrock quota and the database), logs in its
own log group (1 month). Its role carries the connection permissions inline, as in the CI/CD
projects (the gotcha above applies to any project with a GitHub source). Buildspec
`.codebuild/jobs.yml`: install uv 0.9.21, `uv sync --frozen`, `make $TARGET`.

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override name=TARGET,value=dataset
# another branch: add --source-version feat/my-branch
# follow it in the CodeBuild console (the build's log tab)
```

| `TARGET` | What |
|---|---|
| `dataset` | HotpotQA -> dedup -> JSONL shards in `bulk/hotpotqa/` (which trigger `ingest`), stats and gold questions in `jobs/dataset/` |
| `dataset-stats` | the same counts with `--dry-run`, writes nothing |
| `schema` | re-apply `sql/schema.sql` |

`acme` and `eval CONFIG=...` arrive with their streams. A build without `TARGET` fails on purpose.

## CI/CD

[ADR 0012](adr/0012-codebuild-cicd-via-codeconnections.md),
[ADR 0013](adr/0013-branch-pr-workflow-and-ci.md).

| Event | Where | What |
|---|---|---|
| PR to `main` | GitHub Actions `ci.yml` | `make check` (ruff lint + format check, pytest, `cdk synth`) |
| PR to `main` (owner only) | CodeBuild `investigation-pr-diff`, `.codebuild/pr-diff.yml` | `make diff-pr` (template diff, lookup role only), posted as one PR comment (edited on each push) by `scripts/comment_pr.py`; status check on the PR |
| Push to `main` (owner only) | CodeBuild `investigation-deploy`, `.codebuild/deploy.yml` | `make test`, `make deploy`, `make verify` (`cdk diff --fail`), `make smoke` (`/health`); status on the commit |

- **Why CodeBuild and not GitHub OIDC:** the Free-plan SCP denies `iam:*Provider*`; creating the
  OIDC provider failed with an explicit deny (2026-10-24).
- Webhooks filter on the owner's GitHub id (`139613549`) and anchored refs (`^refs/heads/main$`),
  so code from anyone else never runs in the account.
- PR role: assume only `cdk-hnb659fds-lookup-role-*` (ReadOnly) + read the token parameter. Deploy
  role: assume lookup, deploy, file-publishing, image-publishing + describe `Investigation-prod`.
- Buildspecs are read from the repo at build time: editing `.codebuild/*.yml` needs no redeploy.
- Images: `aws/codebuild/standard:7.0`, `general1.small`; deploy runs privileged (Docker build).
  uv is installed in the build (`0.9.21`), Node from the image runtime (22).
- Third-party actions in `ci.yml` are pinned to commit SHAs.
- The CDK CLI is not installed globally: the Makefile runs `npx --yes aws-cdk@2.1146.1`. The library
  version is pinned in `uv.lock`. `CI=true` switches the Makefile from the `investigation` profile to
  ambient credentials.

## Deploying

```bash
make diff      # read it, every time
make deploy    # Investigation-prod; normally CodeBuild does this on merge
make verify    # fails if production differs from the code
make smoke     # GET /health on the live URL
```

`make bootstrap`, `make diff-cicd` + `make deploy-cicd` are by hand. `deploy` and `deploy-cicd` pass
`--require-approval never` (non-interactive shells cannot answer CDK's IAM prompt), so read the diff
first. Claude Code's auto mode refuses IAM-changing deploys; the owner runs those.

## Packaging

One image from `Dockerfile` (base `public.ecr.aws/lambda/python:3.12`), dependencies installed with
uv from `uv.lock` (`--no-dev`), code copied from `src/engine`. `.dockerignore` is a whitelist
(`pyproject.toml`, `uv.lock`, `src/`), which also keeps the CDK asset staged in `cdk.out` small.
[ADR 0009](adr/0009-one-container-image-for-all-lambdas.md).

## Cost

Target: inside the $100 credits until the interview. Full table with eu-north-1 prices in
[PLAN.md](../PLAN.md) (Deployment): ~$20-30 for the five days, ~$2-4 per month of demo. The main
spend is Claude Haiku in evaluation sweeps; Aurora costs only while awake ($0.14 per ACU-hour).
Rules: no NAT Gateway, no custom CloudWatch metrics, no provisioned concurrency, no always-on
database.

## Operating notes

- **Windows**: AWS CLI JSON output can crash with exit 255 on non-ASCII text (cp1251 console). Run
  with `PYTHONUTF8=1`.
- Interactive AWS CLI wizards (`aws configure sso`, `aws login` without `--profile`) fail inside the
  Claude Code terminal ("expecting a Windows console"); run them in PowerShell or pass every value
  as a flag.
- `aws login` in a browser with several AWS sessions offers a session picker; a session of another
  account silently logs the profile into that account. Check with
  `aws sts get-caller-identity --profile investigation` after every login.
