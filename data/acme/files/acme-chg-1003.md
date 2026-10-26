# Change CHG-1003: payments-api runtime upgrade to Python 3.12

Document: CHG-1003

Date: 2026-01-08

Services: payments-api

## Description

This change upgrades the payments-api runtime from Python 3.11 to Python 3.12. The upgrade includes dependency updates and compatibility testing to ensure all payment processing flows continue to operate correctly under the new runtime version.

## Reason

Python 3.12 provides performance improvements, security patches, and enhanced standard library features. Upgrading maintains our runtime on a supported version and allows the Payments Platform team to benefit from upstream improvements and security updates.

## Rollout

The deployment follows a phased approach to minimize risk:

- Canary at 5% of traffic to validate the new runtime against live payment traffic

- Monitoring of error rates, latency, and payment success metrics during the canary phase

- Gradual traffic shift to 100% once canary metrics confirm stability

- Full rollout to all payments-api instances

Deployment executed by Tomas Novak.

## Rollback plan

If critical issues are detected during canary or full rollout, traffic will be shifted back to the Python 3.11 runtime. The previous deployment remains available for immediate activation. Rollback can be executed within minutes if needed.

## Approval

This change was approved by Maya Chen, lead of the Payments Platform team.

## Status

Deployed on 2026-01-08.
