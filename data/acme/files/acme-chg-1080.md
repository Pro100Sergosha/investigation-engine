# Change CHG-1080: feature store consumer lag alert

Document: CHG-1080

Date: 2026-04-23

Services: fraud-scorer

## Description

This change deploys a new alert for the fraud-scorer service that pages the Risk on-call when the feature store consumer falls behind. The alert triggers when lag above 2 minutes is detected, enabling faster response to feature store synchronization issues.

## Reason

This change is a follow-up to INC-403, which identified that feature store consumer lag can impact fraud scoring latency and accuracy. The new alert provides early warning of degradation, allowing the Risk team to intervene before merchants experience payment delays or scoring failures.

## Rollout

Marco Bellini deployed this change on 2026-04-23. The alert is configured to send page notifications to the Risk on-call engineer whenever the feature store consumer lag exceeds 2 minutes. Alert thresholds and notification routing are documented in RB-12.

## Rollback plan

If the alert generates excessive false positives or causes operational issues, the alert can be disabled by removing the alert rule from the fraud-scorer monitoring configuration. This requires no service restart and takes effect within one minute. Rollback does not affect the fraud-scorer service itself.

## Approval

This change was approved by Ines Duarte, lead of the Risk team.

## Status

Deployed.
