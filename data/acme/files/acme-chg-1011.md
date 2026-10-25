# Change CHG-1011: release fraud-scorer model v3.4

Document: CHG-1011

Date: 2026-01-21

Services: fraud-scorer

## Description

Release of fraud-scorer model v3.4 to all traffic, replacing v3.3. The fraud-scorer service scores every payment for fraud risk with a machine-learning model; high scores are declined. This release updates the model to v3.4.

## Rollout

Deployment was executed by Marco Bellini and deployed at 09:30 UTC on 2026-01-21. The new model was deployed to all traffic, replacing v3.3 across the fraud-scorer service.

## Rollback plan

In the event of issues, the rollback procedure is documented in RB-06. The rollback restores the previous model version v3.3 and can be executed by on-call SRE staff.

## Approval

This change was approved by Ines Duarte, lead of the Risk team.

## Reason

Model v3.4 represents an improvement over v3.3 and was approved for production deployment.

## Status

The change was rolled back to v3.3 following INC-201. See the incident report for details on the issues that triggered the rollback decision.
