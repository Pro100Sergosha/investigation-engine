# Running it

Prerequisites, Make targets, jobs and evaluations. Back to the [README](../README.md).

## What you need

- `git` and the GitHub CLI `gh`.
- AWS CLI signed in with `aws login --profile investigation` (12 h, renews up to 90 days). No
  long-lived keys. Check the account with `aws sts get-caller-identity --profile investigation`.
- Nothing else runs on the laptop ([ADR 0018](../llm-wiki/adr/0018-cloud-only-ingestion-and-jobs.md)).
  Ingestion, corpus generation and evaluation run in Lambda and CodeBuild. `make check` runs in
  GitHub Actions on every PR; it makes no AWS calls, so it also runs anywhere with uv and Node.

## Make targets

All targets are in the [Makefile](../Makefile); `make help` lists them.

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

## Running a job

A job is a CodeBuild build of `investigation-jobs` with one variable, `TARGET`, which names the
Makefile target (llm-wiki/07, [Jobs](../llm-wiki/07-infrastructure.md#jobs)):

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override name=TARGET,value=dataset
# another branch: add --source-version feat/my-branch
```

Loading the corpus from scratch: `TARGET=dataset` (HotpotQA shards; `ingest` loads them), then
`TARGET=acme-load`. Both are safe to rerun: `ingest` skips what is stored.

## Running an evaluation

From [llm-wiki/09-evaluation.md](../llm-wiki/09-evaluation.md#running). The whole value is one
`TARGET`:

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override "name=TARGET,value=eval CONFIG=agent LIMIT=3"
# full runs: value=eval CONFIG=retrieval | embeddings | agent | agent-structured | single-shot | agent-gpt-oss
```

- `retrieval` uses no LLM; the other three run the agent and the Qwen3 judge.
- Results go to `s3://$BUCKET/jobs/eval/<config>.json` (`<config>-limit<N>.json` for a dry run).
  They are downloaded and committed through a PR into [eval/results/](../eval/results/).
- Do not run an eval during a bulk load or the Acme generation: they share the Cohere and Haiku
  quotas.
- A rerun with the same prompts is served by `llm_cache`: cheap and fast, but its cost and
  latency are not the system's.
