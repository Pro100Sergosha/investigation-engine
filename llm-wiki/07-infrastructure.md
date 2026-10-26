---
title: Infrastructure
status: current
last_updated: 2026-10-25
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
| `Investigation-Data-prod` | the Aurora cluster: stateful, rarely changes, see [below](#data-stack) | CodeBuild on push to `main`, before `Investigation-prod` | **deployed** 2026-10-24 (express configuration, ADR 0021) |
| `Investigation-prod` | the application, see [below](#application-stack) | CodeBuild on push to `main` | **deployed** 2026-10-24 with the data path; document API and `ingest` indexing since 2026-10-25 (#21) |

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

Stacks are split by lifecycle ([ADR 0020](adr/0020-data-stack-split-by-lifecycle.md)): a code
deploy of `Investigation-prod` cannot replace the database. `Investigation-prod` imports two
exports of `Investigation-Data-prod` (writer endpoint, cluster resource id), strong references (`cdk.json`):
never remove an export that is still imported in the same deploy; a removal takes two deploys.

## Data stack

`Investigation-Data-prod` (`DataStack` in `cdk/app.py`). Decisions: [ADR 0020](adr/0020-data-stack-split-by-lifecycle.md),
[ADR 0021](adr/0021-aurora-express-iam-auth.md).

| Resource | Configuration |
|---|---|
| Aurora cluster `Db` (`CfnDBCluster`) | identifier `investigation`, **express configuration** (the only kind the Free plan creates): Aurora PostgreSQL at the default version (17.9), one serverless writer created by express, no VPC, **internet access gateway** (PostgreSQL over TLS, port 5432), **IAM authentication only**, master user `postgres`, database `postgres` (express rejects an initial database name), **deletion protection on**, `DeletionPolicy`/`UpdateReplacePolicy: Snapshot`, **0-4 ACU** with auto-pause after 300 s (the express default, pinned in code), backups 1 day. Deletion protection and capacity were applied by an update after the create (express rejects most settings at create) |

`WithExpressConfiguration` is set with `add_property_override` (not in aws-cdk-lib 2.274's schema,
so `cdk synth` warns; the live CloudFormation registry has it). It is create-only.

## Application stack

`Investigation-prod` (`AppStack` in `cdk/app.py`). Decisions: [ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md),
[ADR 0019](adr/0019-isolated-vpc-schema-custom-resource.md) (bucket CORS), [ADR 0021](adr/0021-aurora-express-iam-auth.md) (database access). The bucket stays here with its notifications:
they call `ingest`, and a bucket in the data stack would make the stacks depend on each other.

| Resource | Configuration |
|---|---|
| Bucket `Documents` | all public access blocked, SSL enforced, `RETAIN`, CORS `PUT` from `*` (presigned browser uploads, [ADR 0019](adr/0019-isolated-vpc-schema-custom-resource.md)). Prefixes: `uploads/` (UI), `bulk/` (JSONL shards), `jobs/` (job outputs, inert) |
| S3 events | `ObjectCreated` on `uploads/` and `bulk/` -> `ingest` (asynchronous invoke) |
| Lambda `api` | image, `engine.handlers.api`, x86_64, 1024 MB, 90 s (the agent stops at 80 s, [ADR 0025](adr/0025-agent-loop-seeded-forced-deadline.md)), **reserved concurrency 4**: caps what the unauthenticated `POST /ask` can spend; more requests get 429. Function URL (output `ApiUrl`) |
| Lambda `ingest` | image, `engine.handlers.ingest`, x86_64, 1024 MB, 15 min, **reserved concurrency 2**: two workers fill the ~20 requests/min of the Cohere `eu.*` pool ([ADR 0022](adr/0022-cohere-embed-v4-batched.md)); throttled S3 events wait in Lambda's async queue instead of overloading Bedrock and the database. Async invoke config: 2 retries, maximum event age 6 h (set explicitly), **on failure -> `IngestFailures`** |
| Queue `IngestFailures` | SQS, SQS-managed encryption, SSL enforced, 14 days retention. Lambda puts here every `ingest` event it gave up on (retries exhausted or older than 6 h): the original S3 event (`requestPayload`), `requestContext.condition` and the error (`responsePayload`). No alarm: the depth is visible in the SQS console. Rerun with `make redrive-ingest` ([Jobs](#jobs)) |
| CodeBuild `investigation-jobs` | see [Jobs](#jobs) |
| Custom resource `Schema` | Lambda `SchemaFn` (app image, `engine.handlers.schema`) + `cr.Provider`, see [Database schema](#database-schema) |

Environment of `api`, `ingest` and the jobs project (no secrets): `DB_HOST` (writer endpoint),
`DB_NAME`, `BUCKET`; the jobs project also `INGEST_FAILURES_QUEUE` (queue URL) and
`INGEST_FUNCTION` (the `ingest` function name); `SchemaFn` gets `DB_HOST` and `DB_NAME`. `src/engine/config.py` reads them
(empty defaults for tests; `DB_USER` defaults to `app`).

Permissions (least privilege, no `*` actions):

| Principal | Database login (`rds-db:connect`) | Bedrock | S3 |
|---|---|---|---|
| `api` | `app` | Cohere Embed V4 (`eu.*`), gpt-oss-120b, Qwen3-235B, Claude Haiku 4.5 (`eu.*`) | `PutObject` on `uploads/*` (to presign uploads) |
| `ingest` | `app` | Cohere Embed V4 (`eu.*`) only (it embeds, it never calls an LLM) | `GetObject` on `uploads/*`, `bulk/*`; `SendMessage` to `IngestFailures` (the failure destination) |
| `investigation-jobs` | `app` | same as `api` | `GetObject`, `PutObject` on the bucket, `ListBucket`; receive/delete on `IngestFailures` and `lambda:InvokeFunction` on `ingest` (for `redrive-ingest`) |
| `SchemaFn` | `postgres` | - | - |

- Database login is `rds-db:connect` on `arn:aws:rds-db:eu-north-1:988277499209:dbuser:<cluster
  resource id>/<user>`: it lets the role sign an IAM auth token for that one database user
  (`generate_db_auth_token`, local, no API call). No secret, no password.
- Bedrock: `InvokeModel` and `InvokeModelWithResponseStream`, which also authorize `Converse` and
  `ConverseStream` (there is no separate Converse action). In-Region models by foundation-model ARN.
  Cohere Embed V4 and Claude Haiku 4.5 exist here only through `eu.*` inference profiles; each
  needs two statements (`_allow_eu_profile` in `cdk/app.py`): the profile in eu-north-1
  (`inference-profile/eu.cohere.embed-v4:0`, `inference-profile/eu.anthropic.claude-haiku-4-5-*`),
  and `arn:aws:bedrock:*::foundation-model/<model>` (every EU Region the profile routes to) with
  the condition `bedrock:InferenceProfileArn` = that profile, so the model can be called only
  through the profile.
- IAM is not quota: verified on 2026-10-24, all four models answer and cross-Region inference works,
  but Claude Haiku 4.5 is limited to 10 requests/min per profile until the account-level increase
  is approved (14 Known gaps). Haiku 5.5 is not available to the account.
- Cohere Embed V4 quotas per profile pool (verified 2026-10-25): 20 requests/min, 300k
  tokens/min, 16.2M tokens/day, shared by the bulk load and query embeddings.

### Database schema

`sql/schema.sql` ([03 Data model](03-data-model.md)) is applied by the `Schema` custom resource in
`Investigation-prod`: its properties carry the SQL text and the writer endpoint, so CloudFormation
sends *Create* on the first deploy and *Update* whenever either changes; *Delete* does nothing.
The handler is `engine.handlers.schema` in the app image (`SchemaFn`, 5 min): it connects as
`postgres` with an IAM token (`engine.db.connect`, which retries for ~1 minute while a paused
cluster resumes) and runs the whole file in one call, one implicit transaction. The file also
creates the `app` role and its grants. Nothing manual is needed after a merge; a repair is a deploy
that changes the file.

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
| `acme` | `scripts/gen_acme.py`: the Acme corpus from `data/acme/spec.json`, one Haiku call per document, each file checked by parsing it; files and labels to `jobs/acme/` (inert), to be committed ([05 Corpora](05-corpora.md#acme-synthetic)) |
| `acme-load` | copies the committed `data/acme/files/` to `uploads/`, so `ingest` indexes them as `upload:<file name>` |
| `redrive-ingest` | `scripts/redrive_ingest.py`: for each message in `IngestFailures`, log the condition and error, invoke `ingest` asynchronously with the original S3 event, delete the message once the invoke is accepted; stops at the first empty receive. Safe to run twice: `ingest` skips what is stored |
| `eval CONFIG=<name> [LIMIT=N]` | `eval/run.py`: the question set through `retrieval` (no LLM), `agent`, `agent-fixed` or `single-shot`; results to `jobs/eval/<config>.json` ([09 Evaluation](09-evaluation.md)). The whole value goes in one variable: `"name=TARGET,value=eval CONFIG=agent LIMIT=3"` |

A build without `TARGET` fails on purpose.

## CI/CD

[ADR 0012](adr/0012-codebuild-cicd-via-codeconnections.md),
[ADR 0013](adr/0013-branch-pr-workflow-and-ci.md).

| Event | Where | What |
|---|---|---|
| PR to `main` | GitHub Actions `ci.yml` | `make check` (ruff lint + format check, pytest, `cdk synth`) |
| PR to `main` (owner only) | CodeBuild `investigation-pr-diff`, `.codebuild/pr-diff.yml` | `make diff-pr` (template diff, lookup role only), posted as one PR comment (edited on each push) by `scripts/comment_pr.py`; status check on the PR |
| Push to `main` (owner only) | CodeBuild `investigation-deploy`, `.codebuild/deploy.yml` (one build at a time, `concurrent_build_limit=1`: later pushes queue in order) | `make test`, `make deploy` (data stack, then app stack), `make verify` (`cdk diff --fail` on both), `make smoke` (`/health` and `/documents?limit=1`); status on the commit |

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
make diff      # both stacks; read it, every time
make deploy    # Investigation-Data-prod, then Investigation-prod; normally CodeBuild does this on merge
make verify    # fails if either stack in production differs from the code
make smoke     # GET /health and GET /documents?limit=1 (the database path) on the live URL
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
Embedding the corpus with Cohere Embed V4 costs ~$1.3 per full load. SQS (`IngestFailures`,
on the Free plan list) is $0 at this volume (1M requests/month free).
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
