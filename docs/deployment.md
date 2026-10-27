# Deployment

Deployment architecture, stacks, CI/CD, secrets, persistence, free-tier limits and cost. Back to the [README](../README.md).

## Deployment architecture

| Piece | Configuration |
|---|---|
| Account | AWS project `988277499209` on the Free plan, Region `eu-north-1` |
| `api` Lambda | container image, x86_64, 1024 MB, 90 s timeout, reserved concurrency 4, public Function URL (auth `NONE`) |
| `ingest` Lambda | same image, 1024 MB, 15 min, reserved concurrency 2, async retries 2, on failure -> SQS `IngestFailures` |
| `SchemaFn` | same image; applies [sql/schema.sql](../sql/schema.sql) as a custom resource on every deploy that changes it |
| Aurora | Serverless v2, express configuration, PostgreSQL 17.9 + pgvector, 0-4 ACU, auto-pause after 300 s, IAM authentication only |
| S3 `Documents` | all public access blocked, SSL enforced, retained on stack delete. Prefixes `uploads/`, `bulk/`, `jobs/` |
| CodeBuild | `investigation-jobs` (jobs), `investigation-pr-diff`, `investigation-deploy` (CI/CD) |
| Logs | CloudWatch Logs, one JSON line per request; no custom metrics |

Lambdas and CodeBuild run outside any VPC. Aurora has no VPC either: it is reached through its
internet access gateway over TLS, with IAM auth tokens. No NAT Gateway. Details:
[llm-wiki/07-infrastructure.md](../llm-wiki/07-infrastructure.md).

## Stacks by lifecycle

| Stack | Contents | Deployed by |
|---|---|---|
| `Investigation-Data-prod` | the Aurora cluster: stateful, rarely changes | CodeBuild on merge to `main`, first |
| `Investigation-prod` | Lambdas, Function URL, documents bucket and its notifications, `IngestFailures`, jobs project, schema custom resource, IAM grants | CodeBuild on merge to `main`, second |
| `Investigation-Cicd-prod` | the CodeBuild CI/CD projects | by hand only |

A code deploy of `Investigation-prod` cannot replace the database
([ADR 0020](../llm-wiki/adr/0020-data-stack-split-by-lifecycle.md),
[ADR 0021](../llm-wiki/adr/0021-aurora-express-iam-auth.md)). The bucket stays in the application
stack with the Lambda its notifications call; otherwise the two stacks would depend on each other.

## CI/CD

| Event | Where | What |
|---|---|---|
| Pull request to `main` | GitHub Actions [ci.yml](../.github/workflows/ci.yml) | `make check` |
| Pull request to `main` | CodeBuild `investigation-pr-diff` ([.codebuild/pr-diff.yml](../.codebuild/pr-diff.yml)) | `cdk diff` against production, posted as one PR comment |
| Push to `main` | CodeBuild `investigation-deploy` ([.codebuild/deploy.yml](../.codebuild/deploy.yml)) | `make test deploy verify smoke` |

CodeBuild gets the repository through a CodeConnections connection (GitHub App). There is no
GitHub OIDC: the Free-plan SCP denies `iam:*Provider*`, and creating the provider failed with an
explicit deny ([ADR 0012](../llm-wiki/adr/0012-codebuild-cicd-via-codeconnections.md)). Webhooks fire
only for the repository owner, so nobody else's code runs in the account.

## Secrets

| Secret | How it is handled |
|---|---|
| LLM and embedding access | none: Bedrock is called with the Lambda's IAM role, no API keys |
| Database | no password exists. Each caller signs a 15-minute IAM auth token for its database user (`app`: data access only; `postgres`: schema only) |
| GitHub token for the PR diff comment | SSM Parameter Store SecureString `/investigation/github-token`, fine-grained, this repository only |
| Admin token of the public API | SSM SecureString `/investigation/admin-token` (random, created with the CLI), read by `api` once per container, compared with `hmac.compare_digest`, never logged |
| Lambda environment | only non-secret values (`DB_HOST`, `DB_NAME`, `BUCKET`, `ADMIN_TOKEN_PARAM` = the parameter's name), read only in [config.py](../src/engine/config.py) |

Locally, `.env` is gitignored and [.env.example](../.env.example) is the template.

## Public API protection

The Function URL has no auth, because reviewers must add, update and delete documents from the
page without accounts ([ADR 0030](../llm-wiki/adr/0030-read-only-seed-admin-token-daily-caps.md),
[API contract](../llm-wiki/04-api-contract.md#protection)):

- the seed corpus (HotpotQA and the `acme-*` files) is read-only: `DELETE` is 403, and so is
  an upload under an `acme-*` name. Your own uploads can be updated and deleted;
- `POST /ask` is 429 after 150 Bedrock calls per UTC day (calls served from the LLM cache are
  free and not counted), upload URLs after 50 per day; an upload is at most 5 MB (the size is
  signed into the presigned URL);
- a secret `x-admin-token` header (SSM SecureString) lifts both rules for the author.

## Persistence

Aurora has deletion protection and a snapshot removal policy. The corpus loaded on 2026-10-25 has
been served after every redeploy since: each merge redeploys the Lambdas, not the data. The S3
bucket is retained if its stack is deleted.

## Free-tier limits and cost

The account is an AWS Free-plan project: $100 credits, expires 2027-04-24, then closes instead of
billing. It has never been upgraded ([ADR 0011](../llm-wiki/adr/0011-free-plan-aws-project.md)).

| Limit | Value | Effect |
|---|---|---|
| Aurora sleep | scales to 0 ACU after 300 s without connections (warm `api` instances keep one open); resume 15-25 s, median ~18.5 s | the first request after idle is slow. If the resume outlasts `db.connect`'s retries the API answers 503 and the UI retries once after 15 s; a cold request can also hit the 90 s Lambda timeout (502) |
| Claude Haiku 4.5 | 10 requests/min per profile (`eu.*` and `global.*`) | an eval sweep of three answer runs takes ~50 min; requested increase not approved yet |
| Cohere Embed V4 | 20 requests/min, 300k tokens/min, 16.2M tokens/day per profile pool | the bulk load and query embeddings share it; at most one full reload (~11M tokens) per day |
| Qwen3-235B (judge), gpt-oss-120b | 100 requests/min | not paced |
| `api` reserved concurrency | 4 | a fifth request at once gets 429 from Lambda; caps how fast the unauthenticated `POST /ask` can spend |
| Public `POST /ask` | 150 Bedrock calls per UTC day (~65 questions, ~$1; worst case ~$5) | then 429 until 00:00 UTC; the admin token is not capped |
| Public uploads | 50 upload URLs per UTC day, 5 MB per file | then 429; a larger file is refused before upload |
| `ingest` reserved concurrency | 2 | two workers fill the Cohere pool |
| Lambda timeouts | `api` 90 s (agent deadline 80 s), `ingest` 15 min | long jobs go to CodeBuild |

Cost estimate (eu-north-1 prices from the AWS Pricing API, 2026-10-24; [PLAN.md](../PLAN.md) section 3):

| Service | Price | 5 days of development | Per month of demo |
|---|---|---|---|
| Lambda | always free (1M requests, 400k GB-s/month) | $0 | $0 |
| Aurora Serverless v2 | $0.14 per ACU-hour while awake, storage ~$0.1/GB-month | ~$1-2 | ~$0.5-1 |
| Bedrock Cohere Embed V4 (`eu.*`) | ~$0.12 per 1M tokens (third-party trackers; the Pricing API gave no clear figure) | ~$1.5-3 (one or two full loads of ~11M tokens) | ~$0 |
| SQS (`IngestFailures`) | 1M requests/month free | $0 | $0 |
| Bedrock Claude Haiku | $1.10 / $5.50 per 1M (Haiku 4.5, EU) | ~$15-25 | ~$1-2 |
| Bedrock gpt-oss-120b, Qwen3 | $0.15/$0.60, $0.22/$0.88 per 1M | ~$1 | ~$0 |
| CodeBuild | 100 min/month free, then ~$0.005/min | ~$1-2 | ~$0 |
| S3, ECR | cents (ECR needs a lifecycle policy) | ~$0.1 | ~$0.2 |
| CloudFormation, CodeConnections, SSM, CloudWatch Logs, IAM, KMS | free at this volume | $0 | $0 |
| CloudWatch dashboard + 2 alarms, Logs Insights | free tier: 3 dashboards x 50 metrics (1 used, 35 metrics), 10 alarms, 5 GB Logs data incl. Insights scans | $0 | $0 |
| **Total** | | **~$20-30** | **~$2-4** |

Measured costs:

| What | Cost | Source |
|---|---|---|
| Embedding the corpus once (Cohere) | ~$1.3 | [llm-wiki/05](../llm-wiki/05-corpora.md) |
| Generating the Acme corpus (95 Haiku calls) | $0.28 | [llm-wiki/05](../llm-wiki/05-corpora.md) |
| Eval `agent`, 72 questions | $1.16 (~$0.016 per question) | [llm-wiki/09](../llm-wiki/09-evaluation.md#pacing-and-cost) |
| Eval `agent-structured` | $1.08 (~$0.015 per question) | same |
| Eval `single-shot` | $0.37 (~$0.005 per question) | same |
| Eval `retrieval` | ~$0 (Cohere, a few thousand tokens) | same |
| Judge | ~$0.0001 per question | same |

Eval costs include the judge, count uncached calls only, and price Bedrock prompt-cache tokens
(writes at 1.25x, reads at 0.1x the input price). The agent loop costs ~3x single-shot per
question.
