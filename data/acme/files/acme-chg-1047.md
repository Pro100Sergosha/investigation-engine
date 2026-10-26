# Change CHG-1047: restore ledger pool size and add a config check

Document: CHG-1047

Date: 2026-03-13

Services: ledger

## Description

This change restores the ledger connection pool to its previous configuration and adds a deploy-time validation check. The max_connections parameter is set back to 200. A new configuration validator will reject any pool size below 100 during deployment, preventing future misconfigurations that could lead to connection saturation.

## Reason

Follow-up to INC-301, which identified that the ledger connection pool had been undersized during CHG-1042. The reduced pool size caused connection exhaustion under normal payment load, leading to cascading failures across the payments platform. By restoring max_connections back to 200 and adding automated validation, we prevent recurrence of this failure mode and ensure the pool remains within safe operating bounds.

## Rollout

Oskar Lind deployed this change on 2026-03-13. The deployment includes:

- Restoration of max_connections to 200 in the ledger service configuration

- Addition of a deploy-time check that validates the pool size is not below 100

- Verification that connection utilization returns to normal levels post-deployment

The change was deployed to the production ledger service without requiring a full service restart, as the pool size adjustment takes effect on new connections.

## Rollback plan

If issues arise post-deployment, the change can be rolled back by reverting the configuration to the previous state and redeploying. The validator will not prevent rollback. Connection pool metrics should be monitored during and after any rollback to confirm stability.

## Approval

Approved by Ravi Patel.

## Status

Deployed. Ledger connection pool is operating at normal capacity. Refer to RB-03 for ongoing monitoring procedures and saturation detection.
