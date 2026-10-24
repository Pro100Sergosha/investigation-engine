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
| Bedrock quotas (Titan RPM, Haiku tokens/min) unknown | new account | checked in Service Quotas before the bulk load |
| No reserved concurrency on `api` | not configured yet | added with the real `/ask` route (quota is 400, so it is possible here) |
| No Aurora, S3 bucket, `ingest` Lambda, Secrets Manager secret or `investigation-jobs` project in the stacks | stream A adds them | the corresponding PRs merge |
| Old paid account `788607671121` still exists, no budget on it | abandoned in favour of the Free-plan project ([ADR 0011](adr/0011-free-plan-aws-project.md)) | closed in the console, or a budget alert added |
| No SSE streaming of answers | not supported on Python Lambda Function URLs ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | accepted, listed as future work |
