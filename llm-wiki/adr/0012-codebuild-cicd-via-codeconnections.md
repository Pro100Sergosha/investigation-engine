---
title: CD runs in CodeBuild, triggered by GitHub through CodeConnections
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0012: CD runs in CodeBuild, triggered by GitHub through CodeConnections

## Context

Merges to `main` deploy automatically (ADR 0010), and a pull request should show whether its
infrastructure change matches production before it is merged. The first design was GitHub Actions
assuming an AWS role through GitHub OIDC (binadar's approach). On this Free-plan project
(ADR 0011) the managed SCP denies `iam:*Provider*`: creating the OIDC provider failed with an
explicit deny, so OIDC is impossible here. Long-lived access keys in GitHub secrets were the other
obvious option and contradict the no-long-lived-keys rule.

## Decision

Deployment runs inside AWS. Stack `Investigation-Cicd-prod` defines two CodeBuild projects whose
source is this GitHub repo, authenticated through a CodeConnections connection (GitHub App), with
webhooks and build status reported back to GitHub:
- `investigation-pr-diff`: on PR created/updated/reopened against `main`, runs `make diff` and posts
  the diff as one PR comment (`scripts/comment_pr.py`, edited on every push). The comment needs a
  fine-grained GitHub token, stored as SSM SecureString `/investigation/github-token`.
- `investigation-deploy`: on push to `main`, runs `make test`, `make deploy`, `make verify`
  (`cdk diff --fail`: the deployed stack must equal the code) and `make smoke` (`/health`).

Both webhooks fire only for events by the repo owner (actor id filter); branch patterns are anchored
regexes. Each project role can only assume the CDK bootstrap roles (`cdk-hnb659fds-*`), plus reading
the token (PR) or describing `Investigation-prod` (deploy). Buildspecs live in `.codebuild/`, so a
build change needs no redeploy. The connection is created once with the CLI and confirmed in the
console (the GitHub handshake cannot be automated); `Investigation-Cicd-prod` is deployed by hand
(`make deploy-cicd`), never by itself. GitHub Actions keeps running `make check` on PRs.

## Consequences

No AWS credentials exist outside AWS; the PR shows the exact infrastructure change and the merge
commit shows whether production now matches the code.
The cost: the PR build runs code from the PR branch with a role that can deploy, so anyone able to
open a PR as the owner could deploy from a branch; the actor filter and a private repo limit this to
the owner. One GitHub token (PR comments only) is long-lived, scoped to this repo. CodeBuild's free
tier is 100 build minutes a month on `general1.small`; an image build takes several minutes, beyond
that it bills from credits at a fraction of a cent per minute. Two CI systems to read instead of
one. Build logs are in CloudWatch, visible only with AWS access.

## Alternatives considered

**GitHub Actions + OIDC (binadar)**: blocked by the Free-plan SCP.

**GitHub Actions + IAM user access keys**: 15 minutes of work, `iam:CreateAccessKey` is allowed, but
long-lived keys outside AWS.

**CodePipeline in front of CodeBuild**: adds a pipeline view and approval stages; with one build
step it is an extra resource with nothing to orchestrate.

**Manual `make deploy` from the laptop**: zero setup, no automatic deployment and no PR diff.
