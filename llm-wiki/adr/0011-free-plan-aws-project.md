---
title: A Free-plan AWS project in eu-north-1, accessed with aws login
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0011: A Free-plan AWS project in eu-north-1, accessed with aws login

## Context

The task requires deployment on a free tier. binadar's AWS account was rejected outright: it runs
unrelated production services, its Lambda concurrency quota is 10 for the whole account, and its
permissions boundary denies RDS.

A first dedicated account (`788607671121`) was created on credits and accessed through IAM Identity
Center. Enabling Identity Center created an AWS Organization, which the Free plan does not support,
and the account was upgraded to the Paid plan. Paid means no hard stop: anything beyond credits is
charged to the card. That breaks the free-tier requirement, so the account was abandoned.

## Decision

Use an AWS **project** (new AWS experience) on the Free plan: account `988277499209`, Region
`eu-north-1` (fixed by the project), $100 credits, closes on 2027-04-24 instead of billing. Human
CLI access through `aws login --profile investigation` (browser sign-in, 12 h credentials renewable
for 90 days), no long-lived keys. Never enable anything that upgrades the plan (IAM Identity Center,
Organizations, Control Tower, Paid-only services). Lambda concurrency quota here is 400.

## Consequences

Spend is capped by construction; the demo lives until April 2027, past the interview. The project's
managed SCPs enforce a single Region, which keeps the inventory in one place.
The cost: no SSO and no multi-account; every Regional resource must be in `eu-north-1`
(Rekognition, Textract, Personalize and App Runner are unavailable there); some services require
leaving the Free plan, so each new service is checked against the
[supported list](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html)
first. The abandoned paid account still exists and should be closed or watched by a budget.

## Alternatives considered

**binadar's account**: shared production, concurrency 10, boundary denies RDS.

**The paid account `788607671121`**: works, Lambda/S3 always-free would cost ~$0, but no hard stop.

**Neon + Hugging Face Spaces (original plan)**: $0 without a card, but not AWS.
