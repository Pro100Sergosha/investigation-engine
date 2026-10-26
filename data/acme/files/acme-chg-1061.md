# Change CHG-1061: webhook retry policy

Document: CHG-1061

Date: 2026-04-01

Services: notifications

## Description

Change CHG-1061 updates the webhook retry policy in the notifications service. The service now retries failed webhook deliveries from 5 to 8 retries, spread over 24 hours using exponential backoff. This increases resilience for merchants receiving payment event notifications.

## Reason

Merchants rely on webhook notifications to reconcile payments in their systems. Transient network failures and temporary service unavailability can cause webhook delivery to fail. The previous retry policy did not provide sufficient opportunity for delivery to succeed after temporary outages. Increasing retry attempts to 8 and extending the retry window to 24 hours with exponential backoff reduces the likelihood that merchants miss critical payment events due to temporary delivery failures.

## Rollout

Jonas Berg deployed this change to the notifications service on 2026-04-01. The change applies to all new webhook delivery attempts from this date forward. Existing failed deliveries in the queue continue to use the previous retry policy.

## Rollback plan

If issues arise, the retry policy can be reverted to the previous configuration of 5 retries by redeploying the prior version of the notifications service. This rollback does not require coordination with other services and can be executed within minutes.

## Approval

This change was approved by Hannah Kim, lead of the Merchant Experience team.

## Status

Deployed.
