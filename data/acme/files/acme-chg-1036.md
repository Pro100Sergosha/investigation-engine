# Change CHG-1036: per-merchant rate limit on payments-api

Document: CHG-1036

Date: 2026-03-04

Services: payments-api

## Description

This change implements per-merchant rate limiting on payments-api. Each merchant account is limited to 50 requests per second. Requests that exceed this limit receive an HTTP 429 response.

The rate limiter is applied at the API gateway layer before requests reach the payments-api service. Merchants hitting the limit will see HTTP 429 responses with a Retry-After header indicating when they can retry.

## Reason

This change is a follow-up to INC-304, which identified a single merchant's retry loop causing elevated latency across payments-api for all merchants. Per-merchant rate limiting prevents any single merchant from consuming excessive resources and impacting platform stability.

Rate limiting also encourages merchants to implement proper backoff strategies and contact support if they legitimately need higher throughput.

## Rollout

Deployed by Tomas Novak on 2026-03-04. The rate limiter was enabled gradually across merchant accounts to monitor for any unexpected behavior. Merchants with known high-volume legitimate traffic were notified in advance.

## Rollback plan

If issues arise, the rate limiter can be disabled via feature flag without requiring a service restart. Disabling the flag will immediately stop returning HTTP 429 responses. A full rollback would involve redeploying the previous version of payments-api.

## Approval

Approved by Maya Chen.

## Status

Deployed and active. Refer to RB-02 for operational procedures related to noisy merchants and rate limiting.
