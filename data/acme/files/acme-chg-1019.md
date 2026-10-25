# Change CHG-1019: certificate expiry alert for webhook delivery

Document: CHG-1019

Date: 2026-02-11

Services: notifications

## Description

This change implements a certificate expiry alert for the notifications service webhook delivery system. An alert will fire 21 days before any notifications TLS certificate expires and will page the Merchant Experience on-call engineer. The alert is configured in the cert-expiry-webhooks monitoring rule.

## Reason

INC-202 documented a previous incident where webhook deliveries failed after a certificate expiry. This alert provides advance warning to prevent similar outages. By alerting 21 days before expiration, the on-call engineer has sufficient time to follow RB-09 and rotate the certificate before it becomes invalid.

## Rollout

The cert-expiry-webhooks alert will be deployed to the monitoring system. Once active, it will continuously check the expiry date of the notifications service TLS certificate and trigger a page to the Merchant Experience on-call rotation when the certificate is 21 days from expiration.

## Rollback plan

If the alert generates false positives or excessive noise, it can be disabled by removing the cert-expiry-webhooks rule from the monitoring configuration. This will not affect webhook delivery itself, only the advance warning system.

## Approval

Approved by Hannah Kim.

## Status

Ready for deployment.
