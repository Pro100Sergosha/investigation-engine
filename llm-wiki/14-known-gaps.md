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
| Bedrock unusable: every call returns "account is being verified" | new account, AWS verification (normally < 2 h) | a test call succeeds |
| Claude Haiku through `eu.*` may be denied by the Free-plan SCP (cross-Region) | untested until Bedrock works ([ADR 0017](adr/0017-bedrock-claude-haiku-llm.md)) | a Haiku call succeeds, or gpt-oss-120b is made the main model |
| No reserved concurrency on `api` | not configured yet | added with the real `/ask` route (quota is 400, so it is possible here) |
| `ingest` is a stub: it logs the S3 keys and indexes nothing | wave 1 built the infrastructure only | wave 2 wires parse -> dedup -> chunk -> embed -> `db.py` into `handlers.ingest` |
| Bedrock quotas are 0 (2026-10-24): Haiku cross-Region RPM/TPM (adjustable), gpt-oss-120b and Qwen3 (not adjustable); Titan V2 throttled | new account; IAM permissions are in place, quotas are separate | Haiku and Titan quota increases granted in Service Quotas; gpt-oss/Qwen3 stay unusable until AWS raises them |
| Schema changes are additive only (`IF NOT EXISTS`); a new index over a loaded table can exceed the Data API's 45 s statement limit | schema applied by a custom resource on deploy ([ADR 0019](adr/0019-isolated-vpc-schema-custom-resource.md)) | accepted; a destructive change gets a one-off job |
| First deploy of the data path (Aurora cluster + writer, ~10-20 min) may exceed the 30 min timeout of `investigation-deploy` | timeout set before Aurora existed | the first deploy succeeds; otherwise raise the timeout in `CicdStack` and `make deploy-cicd` |
| Old paid account `788607671121` still exists, no budget on it | abandoned in favour of the Free-plan project ([ADR 0011](adr/0011-free-plan-aws-project.md)) | closed in the console, or a budget alert added |
| No SSE streaming of answers | not supported on Python Lambda Function URLs ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | accepted, listed as future work |
