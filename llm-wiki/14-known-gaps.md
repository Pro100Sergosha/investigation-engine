---
title: Known gaps
status: current
last_updated: 2026-10-24
owner: Pro100Sergosha
---

# 14 Known gaps

What does not work yet, or works on a temporary arrangement. Remove an entry in the same commit
that closes it.

| Gap | Why | Closes when |
|---|---|---|
| Branch protection is off: a red PR can be merged by hand | GitHub free plan offers it only on public repositories | the repository is made public (required for submission anyway) |
| Claude Haiku 4.5 limited to 10 requests/min per profile (`eu.*` and `global.*`); an eval sweep takes ~2 h | Bedrock quota of a new account ([ADR 0017](adr/0017-bedrock-claude-haiku-llm.md) update) | the account-level increase to 10,000 is approved |
| No reserved concurrency on `api` | not configured yet | added with the real `/ask` route (quota is 400, so it is possible here) |
| `ingest` is a stub: it logs the S3 keys and indexes nothing | wave 1 built the infrastructure only | wave 2 wires parse -> dedup -> chunk -> embed -> `db.py` into `handlers.ingest` |
| Schema changes are additive only (`IF NOT EXISTS`); a new index over a loaded table holds the deploy for minutes | schema applied by a custom resource on deploy ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | accepted; a destructive change gets a one-off job |
| `investigation-deploy` runs builds in parallel: merges in quick succession race (2026-10-24: ECR "tag is immutable", a stack deployed before the stack it imports from) | no `concurrent_build_limit` on the project | `concurrent_build_limit=1` in `CicdStack`, deployed by hand (`make deploy-cicd`); until then merge one PR at a time |
| Aurora ACU range is the express-configuration default, not 0-4 | express creation accepts only a few settings ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | after the first deploy: read the range, then set `ServerlessV2ScalingConfiguration` (min 0, max 4) in `DataStack` |
| The database endpoint is public (internet access gateway) | the Free plan creates Aurora only with express configuration ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | accepted: IAM-only auth, TLS, no password exists |
| Old paid account `788607671121` still exists, no budget on it | abandoned in favour of the Free-plan project ([ADR 0011](adr/0011-free-plan-aws-project.md)) | closed in the console, or a budget alert added |
| No SSE streaming of answers | not supported on Python Lambda Function URLs ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | accepted, listed as future work |
