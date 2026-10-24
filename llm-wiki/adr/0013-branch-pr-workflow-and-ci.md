---
title: Branches and pull requests, CI on PRs, deploy on main
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0013: Branches and pull requests, CI on PRs, deploy on main

## Context

Code must be checked by commands, not by trust in whoever (or whatever) wrote it, and `main` deploys
to production (ADR 0010). The task also asks for a repository with real history.

## Decision

Same layout as binadar:
- Every change on a branch (`feat/`, `fix/`, `chore/`, `docs/`), pushed, opened as a pull request,
  squash merged when green. No direct commits to `main`.
- GitHub Actions `ci.yml` runs `make check` (ruff lint + format check, pytest, `cdk synth`) on
  pull requests only.
- CodeBuild posts the `cdk diff` against production on every PR and deploys on push to `main`
  (ADR 0012). The PR therefore carries two checks: code (Actions) and infrastructure (CodeBuild).
- Third-party actions are pinned to commit SHAs with the version in a comment.
- No Dependabot: a five-day project gains nothing from weekly update PRs.

## Consequences

Every change is checked before it reaches production, the history reads as a list of PRs, and the
same `make check` runs locally and in CI.
The cost: while the repository is private on a free GitHub plan, branch protection is unavailable
(binadar hits the same 403), so a red PR can still be merged by hand; enforcement starts when the
repository becomes public. Pinned SHAs go stale without Dependabot and are bumped by hand if needed.

## Alternatives considered

**CI on every push, including main**: runs the suite twice per merge (binadar removed it for that
reason); the deploy build runs `make test` anyway.

**Docs-only PR skip (binadar)**: saves nothing while the suite takes under a minute.
