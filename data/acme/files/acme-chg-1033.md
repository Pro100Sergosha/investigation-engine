# Change CHG-1033: shorter log retention for card-gateway

Document: CHG-1033

Date: 2026-03-03

Services: card-gateway

## Description

This change reduces the log retention period for card-gateway from 30 days to 14 days. The card-gateway service handles card authorization requests and responses, which may contain sensitive payment card data. Shortening the retention window decreases the volume of stored card data in logs.

## Reason

PCI DSS compliance requires that stored cardholder data be minimized and retained only as long as necessary for business purposes. By reducing card-gateway request logs from 30 days to 14 days, we lower our exposure to stored card data and strengthen our compliance posture. This change aligns with our data minimization obligations while maintaining sufficient retention for operational troubleshooting and incident investigation.

## Rollout

The change was deployed by Lena Vogel on 2026-03-03. The new retention policy applies to all new logs written after deployment. Existing logs older than 14 days are automatically purged according to the updated schedule.

## Rollback plan

If issues arise, the retention period can be reverted to 30 days by redeploying the previous configuration. This would restore the original log retention behavior without requiring service restart. Logs purged under the new policy cannot be recovered, so rollback is primarily useful for halting further data deletion.

## Approval

This change was approved by Daniel Okafor, lead of the Card Gateway team.

## Status

Deployed on 2026-03-03.
