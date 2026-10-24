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
| `Investigation-prod` | `api` DockerImageFunction (1024 MB, 90 s) + Function URL, output `ApiUrl` | CodeBuild on push to `main` | not yet deployed |

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
