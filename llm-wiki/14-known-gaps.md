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
| `Investigation-Cicd-prod` not deployed: no PR diff comments, merges to `main` deploy nothing | needs the CodeConnections handshake, the GitHub token in SSM, then a manual `make deploy-cicd` | first green `investigation-deploy` build |
| PR CodeBuild role can deploy | `cdk diff` needs the bootstrap deploy role; limited by the owner-only webhook filter ([ADR 0012](adr/0012-codebuild-cicd-via-codeconnections.md)) | a read-only diff role, if collaborators join |
| No reserved concurrency on `api` | not configured yet | added with the real `/ask` route (quota is 400, so it is possible here) |
| No RDS, S3 bucket, `ingest` Lambda or SSM parameters in the stack | stream D adds them when stream A needs the database | the corresponding PRs merge |
| Docker image never built locally | Docker Desktop was not running; CI builds it on deploy | first successful deploy |
| Old paid account `788607671121` still exists, no budget on it | abandoned in favour of the Free-plan project ([ADR 0011](adr/0011-free-plan-aws-project.md)) | closed in the console, or a budget alert added |
| No SSE streaming of answers | not supported on Python Lambda Function URLs ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | accepted, listed as future work |
