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
| Schema changes are additive only (`IF NOT EXISTS`); a new index over a loaded table can exceed the Data API's 45 s statement limit | schema applied by a custom resource on deploy ([ADR 0019](adr/0019-isolated-vpc-schema-custom-resource.md)) | accepted; a destructive change gets a one-off job |
| First deploy of `Investigation-Data-prod` (Aurora cluster + writer, ~10-20 min) plus the image build may exceed the 30 min timeout of `investigation-deploy` | timeout set before Aurora existed | the first deploy succeeds; otherwise raise the timeout in `CicdStack` and `make deploy-cicd` |
| Old paid account `788607671121` still exists, no budget on it | abandoned in favour of the Free-plan project ([ADR 0011](adr/0011-free-plan-aws-project.md)) | closed in the console, or a budget alert added |
| No SSE streaming of answers | not supported on Python Lambda Function URLs ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | accepted, listed as future work |
