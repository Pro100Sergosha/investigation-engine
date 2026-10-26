# Change CHG-1050: longer idempotency key retention

Document: CHG-1050

Date: 2026-03-18

Services: payments-api

## Description

payments-api extends idempotency key retention from 24 hours to 72 hours. The Idempotency-Key header allows merchants to safely retry payment requests; the API deduplicates requests with the same key within the retention window. Longer retention ensures merchants can retry after extended outages without creating duplicate charges.

## Reason

Recent outages have caused merchants to retry payment requests after delays exceeding 24 hours. Without extended key retention, these retries are treated as new requests, resulting in duplicate charges that require manual reconciliation. Extending retention to 72 hours provides a buffer for merchant recovery workflows while remaining operationally feasible for the ledger backend.

## Rollout

Tomas Novak deployed the change to production on 2026-03-18. The deployment updates the idempotency key storage configuration in payments-api and adjusts the cleanup job that removes expired keys from the cache. No API changes are required; existing merchant integrations continue to work without modification.

## Rollback plan

If issues arise, the retention window can be reverted to 24 hours by redeploying the previous configuration. The change is backward compatible; no data migration is needed. Rollback can be executed within 15 minutes.

## Approval

Approved by Maya Chen, lead of the Payments Platform team.

## Status

Deployed to production on 2026-03-18. Monitoring idempotency key cache performance and deduplication rates. No issues reported.
