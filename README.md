# AI Investigation Engine

Multi-source investigation over 66,619 documents (66,555 HotpotQA paragraphs + 64 synthetic
"Acme Payments" documents in four formats). A question is answered by an agent loop over a hybrid
search. The answer is a set of claims, each citing the chunks it rests on. The system abstains
(`insufficient`) when the documents do not hold the answer, and reports `conflicting` when
documents disagree.

It is not "chat with a PDF". It does not answer from the model's own knowledge. It does not let
the model cite text it never retrieved: the server drops such claims.

- Live demo: https://uboosluwad7gxn2mk2kchw3lrq0trfvt.lambda-url.eu-north-1.on.aws/
- Task: Upgaming Talent Growth Program, "Applied AI – AI Investigation Engine Task"
  ([docs/task.pdf](docs/task.pdf)).
- Plan, schedule and status: [PLAN.md](PLAN.md). How the system works now:
  [llm-wiki/index.md](llm-wiki/index.md). Evaluation report: [EVALUATION.md](EVALUATION.md).
  AI usage report: [AI_USAGE.md](AI_USAGE.md).

## Example

Question `acme-022` from the evaluation set, `agent` configuration, run of 2026-10-26
([eval/results/agent.json](eval/results/agent.json)). The judge marked it correct.

> **Who approved change CHG-1042?**

| Field | Value |
|---|---|
| `status` | `conflicting` |
| `answer` | "Oskar Lind or Ravi Patel" |
| `contradictions` | "CHG-1042 approval: The change document states it was approved by Oskar Lind, lead of the Ledger team, but the postmortem INC-301 states it was approved by Ravi Patel." Cites chunks from `upload:acme-chg-1042.md` and `upload:acme-inc-301.pdf` |
| gold answer | "conflicting: Oskar Lind (CHG-1042) vs Ravi Patel (INC-301)" |
| work done | 2 searches, 2 Haiku calls, 11.8 s, $0.019 |

The two sources are a Markdown change record and a PDF postmortem. The contradiction is a
planted one ([data/acme/GROUND_TRUTH.md](data/acme/GROUND_TRUTH.md)).

Try it on the live URL (the first request after an idle period can take ~15 s more, see
[Free-tier limits](#free-tier-limits-and-cost)):

```bash
curl -s -X POST https://uboosluwad7gxn2mk2kchw3lrq0trfvt.lambda-url.eu-north-1.on.aws/ask \
  -H 'content-type: application/json' -d '{"question": "Who approved change CHG-1042?"}'
```

The HTTP routes and JSON shapes are in [llm-wiki/04-api-contract.md](llm-wiki/04-api-contract.md).

## Architecture

Everything runs on AWS in `eu-north-1`: two Lambdas from one container image, one Aurora
PostgreSQL database with pgvector, one S3 bucket, Amazon Bedrock for models, CodeBuild for jobs
and deploys. The full description is [llm-wiki/02-architecture.md](llm-wiki/02-architecture.md).

```
browser ──HTTPS──> Lambda Function URL ──> api Lambda (container image, at most 4 at once)
   │                                         GET  /                 -> index.html
   │                                         GET  /documents        POST /documents/upload-url
   │                                         DELETE /documents/{id} GET  /chunks/{id}
   │                                         POST /ask  (agent loop, 80 s deadline, timeout 90 s)
   │                                             ├──IAM──> Bedrock: Claude Haiku, gpt-oss-120b, Cohere Embed V4 (eu.*)
   │                                             └──IAM token, TLS 5432──> Aurora (express)
   └──PUT (presigned)──> S3 uploads/ ──event──> ingest Lambda (same image, at most 2 at once)
                                                  parse -> dedup -> chunk -> Cohere V4 (96 per request) -> Aurora
                                                  gave up after 2 retries -> SQS IngestFailures

CodeBuild investigation-jobs: dataset (HotpotQA shards -> S3 -> ingest) | redrive-ingest
                              (IngestFailures -> ingest) | eval CONFIG=... (llm-wiki/09) | acme, acme-load
```

### Ingest flow

One path for UI uploads and the bulk corpus ([ADR 0018](llm-wiki/adr/0018-cloud-only-ingestion-and-jobs.md)).

| Step | What happens | Code |
|---|---|---|
| 1. Upload URL | `POST /documents/upload-url` checks the file name (`[A-Za-z0-9._-]{1,100}`, suffix `.pdf .docx .html .htm .md .jsonl`) and returns a presigned S3 `PUT` URL for `uploads/<name>`, valid 5 minutes. The bulk corpus arrives as JSONL shards under `bulk/` instead | [handlers.py](src/engine/handlers.py) |
| 2. S3 event | `ObjectCreated` on `uploads/` or `bulk/` invokes `ingest` asynchronously; at most 2 run at once | [cdk/app.py](cdk/app.py) |
| 3. Parse | PDF (pypdf), DOCX (python-docx), HTML, Markdown and JSONL (standard library) -> `ParsedDoc` with source, title, date, type and metadata | [parsers.py](src/engine/parsers.py) |
| 4. Dedup | sha256 of normalized text. Same hash as any stored document -> skipped. Same source with a new hash -> update: `version + 1`, chunks replaced in one transaction | [index.py](src/engine/index.py) |
| 5. Chunk | both strategies stored side by side: fixed 300/50 tokens and structure-aware (headings and paragraphs) | [chunking.py](src/engine/chunking.py) |
| 6. Embed | Cohere Embed V4, 1024 dimensions, 96 texts per request, each chunk as `<title>\n\n<chunk>` | [embed.py](src/engine/embed.py) |
| 7. Store | `documents` + `chunks` (text, `tsvector`, `halfvec(1024)`), one transaction per document | [db.py](src/engine/db.py), [sql/schema.sql](sql/schema.sql) |
| 8. Failures | a bad file is logged and skipped. A Bedrock or database error fails the invocation; Lambda retries twice, then puts the event into SQS `IngestFailures` (kept 14 days). `make redrive-ingest` reruns it | [scripts/redrive_ingest.py](scripts/redrive_ingest.py) |

Ingestion is asynchronous. The UI polls `GET /documents` until the document appears.

### Ask flow

`POST /ask` -> `agent.ask(question)` with the defaults: fixed chunks, mode `mmr`, at most 6 LLM
calls ([ADR 0025](llm-wiki/adr/0025-agent-loop-seeded-forced-deadline.md),
[ADR 0029](llm-wiki/adr/0029-weighted-rrf-min-max-mmr-fixed-chunks.md)).

| Step | What happens | Code |
|---|---|---|
| 1. Seeded search | the server searches the question itself (k = 10) and puts the hits into the first message | [agent.py](src/engine/agent.py) |
| 2. Search | `search(q, k)`: Cohere query vector -> dense top-40 (partial HNSW index of the strategy) + keyword top-40 (OR `tsquery`, `ts_rank_cd`) -> weighted RRF (k0 = 10, keyword list at weight 0.5) -> MMR (lambda 0.85, min-max relevance) with a per-document cap | [search.py](src/engine/search.py), [rank.py](src/engine/rank.py) |
| 3. Tool loop | Claude Haiku calls `search(query, k)` (k clamped to 1-40) or `get_document(id)` (the document's chunks, up to 8,000 characters, citable) | [agent.py](src/engine/agent.py) |
| 4. LLM client | every call goes through one client: timeout, retry with backoff, Haiku `eu.*` -> Haiku `global.*` -> gpt-oss-120b, prompt caching, Postgres `llm_cache` | [llm.py](src/engine/llm.py) |
| 5. Forced final answer | the last step, or any step with less than 45 s left of the 80 s deadline, offers only `final_answer` and forces it with `toolChoice` | [agent.py](src/engine/agent.py) |
| 6. Citation validator | drops every claim or contradiction that cites a chunk not shown in this run; no claim left -> `insufficient` | [grounding.py](src/engine/grounding.py) |
| 7. Answer | `Answer(status, answer, claims, contradictions, trace)`; the handler adds the cited chunks as `sources` | [models.py](src/engine/models.py), [handlers.py](src/engine/handlers.py) |

A model error or timeout never becomes an HTTP error: the answer is `insufficient` with the
reason in `trace`.

### Module map

| Module | Responsibility |
|---|---|
| [src/engine/models.py](src/engine/models.py) | shared dataclasses: `ParsedDoc`, `Hit`, `Claim`, `Answer` |
| [src/engine/config.py](src/engine/config.py) | the only module that reads environment variables |
| [src/engine/db.py](src/engine/db.py) | the only database access: pg8000 over TLS, IAM auth token as the password, retry while the cluster resumes |
| [src/engine/parsers.py](src/engine/parsers.py) | one file -> `ParsedDoc`; one JSONL shard -> many |
| [src/engine/chunking.py](src/engine/chunking.py) | fixed windows and structure-aware chunks |
| [src/engine/index.py](src/engine/index.py) | writes: dedup hashes, insert, update, delete with chunks |
| [src/engine/embed.py](src/engine/embed.py) | the only embedding calls: Cohere Embed V4 |
| [src/engine/search.py](src/engine/search.py) | reads: dense + keyword -> RRF -> MMR; document and chunk lookups |
| [src/engine/rank.py](src/engine/rank.py) | hand-written weighted RRF and MMR with a per-document cap |
| [src/engine/llm.py](src/engine/llm.py) | the only LLM calls: Bedrock Converse, retry, fallback, caches |
| [src/engine/agent.py](src/engine/agent.py) | the tool-calling loop |
| [src/engine/grounding.py](src/engine/grounding.py) | citation validator and status rules |
| [src/engine/handlers.py](src/engine/handlers.py) | Lambda entry points: `api` (hand-written router), `ingest`, `schema` |
| [static/index.html](static/index.html) | the UI: one page, vanilla JS, served by `api` at `GET /` |
| [eval/run.py](eval/run.py), [eval/metrics.py](eval/metrics.py) | evaluation runner and metric functions |
| [scripts/](scripts/) | jobs: HotpotQA shards, Acme generation, ingest redrive, PR diff comment |
| [cdk/app.py](cdk/app.py) | all infrastructure, three stacks |
| [sql/schema.sql](sql/schema.sql) | the whole schema, idempotent, applied on deploy |

## Justification of decisions

Each row has an ADR with context, costs and rejected alternatives. The table is the short form.

| Decision | Why | ADR |
|---|---|---|
| Own small code, no LangChain, LlamaIndex or web framework | every line must be explainable and changeable at the interview without AI | [0001](llm-wiki/adr/0001-own-code-no-rag-frameworks.md) |
| Postgres + pgvector as the single store | documents, chunks, vectors, keyword index, dedup hashes and LLM cache in one place, plain SQL | [0002](llm-wiki/adr/0002-postgres-pgvector-single-store.md) |
| Hybrid search with hand-written RRF and MMR | RRF needs no score normalization; MMR with a cap spreads hits over documents for multi-hop | [0003](llm-wiki/adr/0003-hybrid-search-own-rrf-mmr.md) |
| Weighted RRF (k0 = 10, keyword 0.5), min-max MMR, fixed chunks by default | tuned by the retrieval eval: equal-weight RRF at k0 = 60 cut Recall@10 to 0.71 | [0029](llm-wiki/adr/0029-weighted-rrf-min-max-mmr-fixed-chunks.md) |
| Partial HNSW index per chunking strategy, OR keyword queries | one shared HNSW graph returned too few rows of a strategy; AND keyword queries matched almost nothing for long questions | [0024](llm-wiki/adr/0024-partial-hnsw-per-strategy-or-keyword-query.md) |
| Own agent loop, server-side citation validation | anti-hallucination is a check in code, not a prompt promise; abstention is a normal outcome | [0005](llm-wiki/adr/0005-agent-loop-with-citation-validation.md) |
| Seeded first search, forced `final_answer`, own 80 s deadline | saves one call, always ends with an answer, stays inside the 90 s Lambda timeout | [0025](llm-wiki/adr/0025-agent-loop-seeded-forced-deadline.md) |
| HotpotQA for scale + synthetic Acme corpus | HotpotQA gives 50k+ documents with gold labels; Acme gives investigations, contradictions and gaps HotpotQA lacks | [0006](llm-wiki/adr/0006-hotpotqa-plus-synthetic-acme-corpus.md) |
| Acme generated by Haiku from a hand-written spec, every fact checked in the parsed file | facts and labels come from the spec, not from the model | [0026](llm-wiki/adr/0026-acme-corpus-spec-driven-generation.md) |
| Bedrock only: Claude Haiku 4.5 agent, gpt-oss-120b fallback, Qwen3-235B judge | IAM instead of API keys, paid from credits, reliable tool calling; judge from another model family | [0017](llm-wiki/adr/0017-bedrock-claude-haiku-llm.md) |
| One LLM client with its own retry, fallback and Postgres cache | only the client knows when retries are exhausted; reruns are served from the cache | [0023](llm-wiki/adr/0023-llm-client-own-retry-fallback-cache.md) |
| Haiku `global.*` pool before gpt-oss | `eu.*` failed for every call on 2026-10-26; a second pool doubles the 10 requests/min quota | [0028](llm-wiki/adr/0028-haiku-global-pool-before-gpt-oss.md) |
| Cohere Embed V4, 96 texts per request; failed ingest events in SQS | 96 texts per request loaded the corpus in ~65 min instead of ~18 h estimated with Titan | [0022](llm-wiki/adr/0022-cohere-embed-v4-batched.md) |
| Aurora Serverless v2, scales to 0 ACU | idle cost is storage only, so the credits last until the interview | [0015](llm-wiki/adr/0015-aurora-serverless-data-api.md) |
| Aurora express configuration with IAM-token connections | the only Aurora the Free plan creates: no VPC, no password, no secret | [0021](llm-wiki/adr/0021-aurora-express-iam-auth.md) |
| Lambda Function URL, UI served by the same Lambda | API Gateway cuts requests at 30 s, the agent can take longer; same origin, no CORS | [0008](llm-wiki/adr/0008-function-url-not-api-gateway.md) |
| Nothing runs on the author's computer: S3-triggered ingest, CodeBuild jobs | data and evaluation rebuild from the repository alone, not from one machine's state; builds run up to 8 h, Lambda 15 min | [0018](llm-wiki/adr/0018-cloud-only-ingestion-and-jobs.md) |
| Own eval runner: retrieval sweep without an LLM, Qwen3 judge, pacing | retrieval configs compared for ~$0; pacing keeps runs inside the Haiku and Cohere quotas | [0027](llm-wiki/adr/0027-eval-runner-retrieval-sweep-qwen-judge.md) |
| CDK in Python, production as the only environment | infrastructure in the backend's language, diffable in review | [0010](llm-wiki/adr/0010-cdk-single-production-environment.md) |
| Stacks split by lifecycle | a code deploy can never replace the database | [0020](llm-wiki/adr/0020-data-stack-split-by-lifecycle.md) |
| AWS Free-plan project, `aws login`, no long-lived keys | free hosting is a requirement; spend is capped by construction | [0011](llm-wiki/adr/0011-free-plan-aws-project.md) |
| CD in CodeBuild through CodeConnections | GitHub OIDC is denied by the Free-plan SCP; long-lived keys in GitHub are not allowed | [0012](llm-wiki/adr/0012-codebuild-cicd-via-codeconnections.md) |
| Branches, pull requests, CI on PRs, deploy on merge | `main` is always deployable; every PR shows code checks and the infrastructure diff | [0013](llm-wiki/adr/0013-branch-pr-workflow-and-ci.md) |
| Shared dataclass contracts, parallel workstreams | streams could start in parallel and merge without breaking each other | [0014](llm-wiki/adr/0014-shared-contracts-parallel-streams.md) |

Reversed decisions worth knowing (each old ADR is kept as history):

| From | To | Why it changed |
|---|---|---|
| Groq free tier ([0004](llm-wiki/adr/0004-groq-llm-with-postgres-cache.md)) | Bedrock Haiku ([0017](llm-wiki/adr/0017-bedrock-claude-haiku-llm.md)) | external API key and ~8k tokens/min would stall the evaluation |
| Public RDS instance ([0007](llm-wiki/adr/0007-serverless-lambda-no-vpc-public-rds.md)) | Aurora Serverless v2 ([0015](llm-wiki/adr/0015-aurora-serverless-data-api.md)), then express + IAM ([0021](llm-wiki/adr/0021-aurora-express-iam-auth.md)) | RDS costs ~$18/month idle; the Free plan then refused a non-express Aurora cluster |
| Model in the Lambda image ([0009](llm-wiki/adr/0009-one-container-image-for-all-lambdas.md)) | Titan V2 on Bedrock ([0016](llm-wiki/adr/0016-titan-embeddings-no-model-in-lambda.md)) | no ML runtime in the image, shorter cold starts |
| Titan V2 ([0016](llm-wiki/adr/0016-titan-embeddings-no-model-in-lambda.md)) | Cohere Embed V4 ([0022](llm-wiki/adr/0022-cohere-embed-v4-batched.md)) | Titan takes one text per request and throttled at ~1 request/s: the first bulk load stalled at 1,853 documents |

## Running it

### What you need

- `git` and the GitHub CLI `gh`.
- AWS CLI signed in with `aws login --profile investigation` (12 h, renews up to 90 days). No
  long-lived keys. Check the account with `aws sts get-caller-identity --profile investigation`.
- Nothing else runs on the laptop ([ADR 0018](llm-wiki/adr/0018-cloud-only-ingestion-and-jobs.md)).
  Ingestion, corpus generation and evaluation run in Lambda and CodeBuild. `make check` runs in
  GitHub Actions on every PR; it makes no AWS calls, so it also runs anywhere with uv and Node.

### Make targets

All targets are in the [Makefile](Makefile); `make help` lists them.

| Target | What it does | Where it runs |
|---|---|---|
| `make check` | `lint` (ruff check + format check), `test` (pytest), `synth` (`cdk synth`) | GitHub Actions on PRs |
| `make fmt` | format and apply safe lint fixes | anywhere |
| `make diff` | `cdk diff` of `Investigation-Data-prod` and `Investigation-prod`. Read it before every deploy | owner, or CodeBuild PR diff (`diff-pr`) |
| `make deploy` | deploy the data stack, then the application stack | CodeBuild on merge to `main` |
| `make verify` | fail if either deployed stack differs from the code | CodeBuild on merge |
| `make smoke` | `GET /health` and `GET /documents?limit=1` on the live URL | CodeBuild on merge |
| `make diff-cicd`, `make deploy-cicd` | the CI/CD stack | by hand only |
| `make bootstrap` | one-time CDK bootstrap of the account and Region | by hand, once |
| `make dataset` | HotpotQA -> dedup -> JSONL shards in `bulk/` (which trigger `ingest`) | CodeBuild `investigation-jobs` |
| `make dataset-stats` | the same counts, writes nothing | CodeBuild `investigation-jobs` |
| `make acme` | generate the Acme corpus with Haiku from `data/acme/spec.json`, checked, to `jobs/acme/` | CodeBuild `investigation-jobs` |
| `make acme-labels` | rewrite `GROUND_TRUTH.md` and `questions.jsonl` from the spec, no AWS | anywhere |
| `make acme-load` | copy `data/acme/files/` to `uploads/`, so `ingest` indexes them like UI uploads | CodeBuild `investigation-jobs` |
| `make redrive-ingest` | rerun the events in `IngestFailures` | CodeBuild `investigation-jobs` |
| `make eval CONFIG=<name> [LIMIT=N]` | run the question set in one configuration, results to `jobs/eval/<config>.json` | CodeBuild `investigation-jobs` |

### Running a job

A job is a CodeBuild build of `investigation-jobs` with one variable, `TARGET`, which names the
Makefile target (llm-wiki/07, [Jobs](llm-wiki/07-infrastructure.md#jobs)):

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override name=TARGET,value=dataset
# another branch: add --source-version feat/my-branch
```

Loading the corpus from scratch: `TARGET=dataset` (HotpotQA shards; `ingest` loads them), then
`TARGET=acme-load`. Both are safe to rerun: `ingest` skips what is stored.

### Running an evaluation

From [llm-wiki/09-evaluation.md](llm-wiki/09-evaluation.md#running). The whole value is one
`TARGET`:

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override "name=TARGET,value=eval CONFIG=agent LIMIT=3"
# full runs: value=eval CONFIG=retrieval | agent | agent-structured | single-shot
```

- `retrieval` uses no LLM; the other three run the agent and the Qwen3 judge.
- Results go to `s3://$BUCKET/jobs/eval/<config>.json` (`<config>-limit<N>.json` for a dry run).
  They are downloaded and committed through a PR into [eval/results/](eval/results/).
- Do not run an eval during a bulk load or the Acme generation: they share the Cohere and Haiku
  quotas.
- A rerun with the same prompts is served by `llm_cache`: cheap and fast, but its cost and
  latency are not the system's.

## Deployment

### Deployment architecture

| Piece | Configuration |
|---|---|
| Account | AWS project `988277499209` on the Free plan, Region `eu-north-1` |
| `api` Lambda | container image, x86_64, 1024 MB, 90 s timeout, reserved concurrency 4, public Function URL (auth `NONE`) |
| `ingest` Lambda | same image, 1024 MB, 15 min, reserved concurrency 2, async retries 2, on failure -> SQS `IngestFailures` |
| `SchemaFn` | same image; applies [sql/schema.sql](sql/schema.sql) as a custom resource on every deploy that changes it |
| Aurora | Serverless v2, express configuration, PostgreSQL 17.9 + pgvector, 0-4 ACU, auto-pause after 300 s, IAM authentication only |
| S3 `Documents` | all public access blocked, SSL enforced, retained on stack delete. Prefixes `uploads/`, `bulk/`, `jobs/` |
| CodeBuild | `investigation-jobs` (jobs), `investigation-pr-diff`, `investigation-deploy` (CI/CD) |
| Logs | CloudWatch Logs, one JSON line per request; no custom metrics |

Lambdas and CodeBuild run outside any VPC. Aurora has no VPC either: it is reached through its
internet access gateway over TLS, with IAM auth tokens. No NAT Gateway. Details:
[llm-wiki/07-infrastructure.md](llm-wiki/07-infrastructure.md).

### Stacks by lifecycle

| Stack | Contents | Deployed by |
|---|---|---|
| `Investigation-Data-prod` | the Aurora cluster: stateful, rarely changes | CodeBuild on merge to `main`, first |
| `Investigation-prod` | Lambdas, Function URL, documents bucket and its notifications, `IngestFailures`, jobs project, schema custom resource, IAM grants | CodeBuild on merge to `main`, second |
| `Investigation-Cicd-prod` | the CodeBuild CI/CD projects | by hand only |

A code deploy of `Investigation-prod` cannot replace the database
([ADR 0020](llm-wiki/adr/0020-data-stack-split-by-lifecycle.md),
[ADR 0021](llm-wiki/adr/0021-aurora-express-iam-auth.md)). The bucket stays in the application
stack with the Lambda its notifications call; otherwise the two stacks would depend on each other.

### CI/CD

| Event | Where | What |
|---|---|---|
| Pull request to `main` | GitHub Actions [ci.yml](.github/workflows/ci.yml) | `make check` |
| Pull request to `main` | CodeBuild `investigation-pr-diff` ([.codebuild/pr-diff.yml](.codebuild/pr-diff.yml)) | `cdk diff` against production, posted as one PR comment |
| Push to `main` | CodeBuild `investigation-deploy` ([.codebuild/deploy.yml](.codebuild/deploy.yml)) | `make test deploy verify smoke` |

CodeBuild gets the repository through a CodeConnections connection (GitHub App). There is no
GitHub OIDC: the Free-plan SCP denies `iam:*Provider*`, and creating the provider failed with an
explicit deny ([ADR 0012](llm-wiki/adr/0012-codebuild-cicd-via-codeconnections.md)). Webhooks fire
only for the repository owner, so nobody else's code runs in the account.

### Secrets

| Secret | How it is handled |
|---|---|
| LLM and embedding access | none: Bedrock is called with the Lambda's IAM role, no API keys |
| Database | no password exists. Each caller signs a 15-minute IAM auth token for its database user (`app`: data access only; `postgres`: schema only) |
| GitHub token for the PR diff comment | SSM Parameter Store SecureString `/investigation/github-token`, fine-grained, this repository only |
| Lambda environment | only non-secret values (`DB_HOST`, `DB_NAME`, `BUCKET`), read only in [config.py](src/engine/config.py) |

Locally, `.env` is gitignored and [.env.example](.env.example) is the template.

### Persistence

Aurora has deletion protection and a snapshot removal policy. The corpus loaded on 2026-10-25 has
been served after every redeploy since: each merge redeploys the Lambdas, not the data. The S3
bucket is retained if its stack is deleted.

## Free-tier limits and cost

The account is an AWS Free-plan project: $100 credits, expires 2027-04-24, then closes instead of
billing. It has never been upgraded ([ADR 0011](llm-wiki/adr/0011-free-plan-aws-project.md)).

| Limit | Value | Effect |
|---|---|---|
| Aurora sleep | scales to 0 ACU after 300 s without connections (warm `api` instances keep one open); resume 15-25 s, median ~18.5 s | the first request after idle is slow. If the resume outlasts `db.connect`'s retries the API answers 503 and the UI retries once after 15 s; a cold request can also hit the 90 s Lambda timeout (502) |
| Claude Haiku 4.5 | 10 requests/min per profile (`eu.*` and `global.*`) | an eval sweep of three answer runs takes ~50 min; requested increase not approved yet |
| Cohere Embed V4 | 20 requests/min, 300k tokens/min, 16.2M tokens/day per profile pool | the bulk load and query embeddings share it; at most one full reload (~11M tokens) per day |
| Qwen3-235B (judge), gpt-oss-120b | 100 requests/min | not paced |
| `api` reserved concurrency | 4 | a fifth request at once gets 429 from Lambda; caps what the unauthenticated `POST /ask` can spend |
| `ingest` reserved concurrency | 2 | two workers fill the Cohere pool |
| Lambda timeouts | `api` 90 s (agent deadline 80 s), `ingest` 15 min | long jobs go to CodeBuild |

Cost estimate (eu-north-1 prices from the AWS Pricing API, 2026-10-24; [PLAN.md](PLAN.md) section 3):

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
| Embedding the corpus once (Cohere) | ~$1.3 | [llm-wiki/05](llm-wiki/05-corpora.md) |
| Generating the Acme corpus (95 Haiku calls) | $0.28 | [llm-wiki/05](llm-wiki/05-corpora.md) |
| Eval `agent`, 72 questions | $1.16 (~$0.016 per question) | [llm-wiki/09](llm-wiki/09-evaluation.md#pacing-and-cost) |
| Eval `agent-structured` | $1.08 (~$0.015 per question) | same |
| Eval `single-shot` | $0.37 (~$0.005 per question) | same |
| Eval `retrieval` | ~$0 (Cohere, a few thousand tokens) | same |
| Judge | ~$0.0001 per question | same |

Eval costs include the judge, count uncached calls only, and price Bedrock prompt-cache tokens
(writes at 1.25x, reads at 0.1x the input price). The agent loop costs ~3x single-shot per
question.

## Performance

| What | Number | Source |
|---|---|---|
| Bulk load of 66,555 HotpotQA documents | ~65 min, measured: documents created between 17:29 and 18:34 UTC on 2026-10-25. Bound by the Cohere pool (~700 requests of 96 texts); the estimate beforehand was ~35-40 min | [llm-wiki/05](llm-wiki/05-corpora.md), [ADR 0022](llm-wiki/adr/0022-cohere-embed-v4-batched.md) |
| Database write | ~0.03 s per document | [llm-wiki/05](llm-wiki/05-corpora.md) |
| Eval build time (72 questions) | `retrieval` ~5 min, `agent-structured` 19 min, `single-shot` 9 min; `agent` with the current prompt not recorded (22 min with the prompt of #31) | [llm-wiki/09](llm-wiki/09-evaluation.md#pacing-and-cost) |
| Prompt cache | steps 3-6 of a run read the history from the cache, ~35% cheaper per question | [llm-wiki/14](llm-wiki/14-known-gaps.md) |

`ask` latency per configuration, seconds, 72 questions
([llm-wiki/09](llm-wiki/09-evaluation.md#results)):

| Config | p50 | p95 |
|---|---|---|
| `agent` (fixed chunks, 6 steps, current prompt) | 10.3 | 45.6 |
| `agent`, prompt of #31 (first uncached run, during the `eu.*` outage) | 13.4 | 40.0 |
| `agent-structured` | 6.7 | 22.8 |
| `single-shot` (1 step) | 5.8 | 11.4 |

Quality in one line (the full analysis is in [EVALUATION.md](EVALUATION.md)): `agent` judge
correctness 0.82, citation precision 0.94, abstention precision/recall 0.77/0.91, contradiction
precision/recall 1.00/0.67; the loop beats single-shot on multi-hop questions, 0.87 vs 0.52 with
the same prompt; fixed/mmr retrieval Recall@10 0.89.

Load test (`make load-test` in CodeBuild, same Region, 200 GETs per level over `/health`,
`/documents` and `/documents/{id}`; details in
[llm-wiki/07](llm-wiki/07-infrastructure.md#performance)):

| Concurrent clients | Succeeded / 429 / other errors | p50 / p95 / p99 ms |
|---|---|---|
| 1 | 200 / 0 / 0 | 26 / 48 / 52 |
| 5 | 104 / 96 / 0 | 24 / 77 / 1,556 (new instances starting) |
| 10 | 97 / 103 / 0 | 27 / 60 / 74 |

| What | Number |
|---|---|
| `api` cold start | init p50 1.29 s, p95 1.74 s (55 cold starts in the production logs) |
| Aurora resume from 0 ACU | 15-25 s, median ~18.5 s (12 resumes in the production logs) |
| One search from the Lambda (`/ask` rerun served by `llm_cache`) | 0.74 s end to end |
| Search in Region (retrieval eval) | mmr p50 0.33 s, p95 0.73 s; hybrid SQL alone p50 0.13 s |

What limits throughput: the `api` reserved concurrency of 4 (the 5th concurrent request gets 429,
nothing else failed); for `POST /ask`, the Bedrock quotas (Haiku 10 requests/min per profile,
Cohere 20/min) long before Lambda or Aurora (max 4 ACU, not moved by the test). Aurora does not
pause while warm `api` instances hold their connection. Monitoring: one CloudWatch dashboard of
built-in metrics and Logs Insights tables ([ADR 0033](llm-wiki/adr/0033-dashboard-built-in-metrics-logs-insights.md)).

Not measured:

- `POST /ask` under concurrent load (deliberately: it spends Bedrock credits).
- The judge's agreement with a human is not measured yet.

## Limitations and future work

Known gaps ([llm-wiki/14-known-gaps.md](llm-wiki/14-known-gaps.md) has the full list):

- **Contradiction recall is 0.67**: 4 of 12 contradictory questions are answered from one
  document. Next step: a server-side second search for the asked fact, excluding the cited
  document, before `final_answer`.
- **Short answers are loose**: EM 0.52 vs F1 0.73 vs judge 0.82; short answers carry extra words.
- **Malformed `final_answer`**: 5 of 72 answers need a reprompt (Haiku sends `claims` as a string).
- **No auth on the Function URL**: anyone with the URL can upload and delete documents. Planned:
  a custom domain with a secret header.
- **The database endpoint is public** (express configuration): IAM-only auth and TLS, no password.
- **Fallback leaves the EU silently**: when `eu.*` fails, questions go to Haiku's `global.*` pool,
  then to gpt-oss-120b. The trace records the model per call.
- **Cold requests**: a resuming database can push `POST /ask` past 90 s (502).
- **Parsers**: a PDF page becomes one paragraph; DOCX tables, headers, footers and text boxes are
  not indexed; one bad line in a JSONL shard skips the whole shard.
- **Operations**: failed ingest events wait in `IngestFailures` (an alarm turns red on the
  dashboard, nobody is notified); schema changes are
  additive only; the deploy concurrency limit is in code but not deployed, so merges go one at a
  time.
- **Quotas**: Haiku 10 requests/min per profile until the increase is approved; query embeddings
  share the Cohere pool with the bulk load.
- **Evaluation**: 72 questions, so differences below ~0.1 are noise; retrieval weights were tuned
  on the same set, so retrieval numbers are optimistic; the HotpotQA chunking comparison is weak
  (paragraphs average 532 characters).

Bonus items not done (PLAN.md section 1, "6. Bonus"), listed as future work:

| Item | State |
|---|---|
| Compare several LLMs or embedding models | not done; Titan was replaced for throughput, not compared on quality. Cheapest next step: Cohere V4 at 512 vs 1024 dimensions |
| More advanced re-ranking | partial: weighted RRF + MMR; no cross-encoder reranker |
| Prompt-injection tests | not started: the prompt treats documents as data, nothing tests it |
| Streaming answers | dropped: Python Lambda Function URLs do not stream |

Done bonus items: agentic RAG (own loop with tools), caching and performance work (`llm_cache`,
prompt caching, 96 texts per embedding request, partial HNSW per strategy), monitoring (CloudWatch
dashboard, ADR 0033) and performance testing (load test over the 66k-document corpus, above).

Scope cut to fit five days ([PLAN.md](PLAN.md) section 5, "Cuts"): the Acme corpus was planned
at ~60-100 documents instead of 150-300 and has 64.

## Repository layout

```
src/engine/      the application (one module per responsibility, see the module map)
eval/            runner, metrics, HotpotQA questions, committed results
data/acme/       Acme spec, generated corpus, ground truth, questions
scripts/         CodeBuild jobs and the PR diff comment
sql/schema.sql   the whole schema
static/          the UI page
cdk/app.py       all infrastructure
.codebuild/      buildspecs: jobs, PR diff, deploy
tests/           pytest, one file per module
llm-wiki/        knowledge base: architecture, data model, API, infrastructure, evaluation, ADRs
```

## Further reading

- [llm-wiki/index.md](llm-wiki/index.md): the system as it is, and the index of all ADRs.
- [EVALUATION.md](EVALUATION.md): methodology, metrics, results and failure analysis.
- [AI_USAGE.md](AI_USAGE.md): which AI tools were used, for what, and what was changed by hand.
- [PLAN.md](PLAN.md): plan, schedule, task checklist, costs and risks.
