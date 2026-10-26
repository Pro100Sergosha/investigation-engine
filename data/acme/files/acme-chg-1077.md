# Change CHG-1077: enable payment links

Document: CHG-1077

Date: 2026-04-20

Services: payments-api

## Description

This change enables the payment_links feature for a first group of merchants behind a feature flag. The payment_links feature allows merchants to generate shareable payment links that customers can use to complete transactions without requiring direct API integration.

The feature flag will initially target 10% of merchants, allowing us to validate the feature in production with real merchant traffic before broader rollout.

## Reason

Payment links represent a key product expansion for Acme Payments. This capability addresses merchant requests for simpler payment collection methods and reduces friction for merchants who lack technical resources for full API integration. Early validation with a subset of merchants enables us to identify and resolve issues before general availability.

## Rollout

Deployment occurs on the payments-api service. Tomas Novak deployed this change. The feature flag controls access, ensuring that only merchants in the initial cohort can generate payment links. Merchants outside the cohort will not see the feature in the merchant portal or through API calls.

The 10% of merchants cohort was selected to provide sufficient traffic for validation while limiting blast radius if issues arise. Monitoring will track payment link creation rates, success rates, and error patterns throughout the rollout period.

## Rollback plan

If critical issues emerge, the feature flag can be disabled immediately, preventing new payment link generation. Existing payment links remain valid but will not be created for new requests. No database migrations or service restarts are required for rollback. The change is fully reversible through feature flag configuration.

## Approval

This change was approved by Maya Chen, lead of the Payments Platform team.

## Status

Deployed on 2026-04-20.
