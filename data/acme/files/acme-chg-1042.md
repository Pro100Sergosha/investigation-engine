# Change CHG-1042: ledger connection pool tuning

Document: CHG-1042

Date: 2026-03-12

Services: ledger

## Description

This change reduces the ledger service's database connection pool to lower the number of idle connections on ledger-db. The max_connections parameter is being changed from 200 to 20.

## Reason

The ledger service maintains a large connection pool to ledger-db that results in excessive idle connections consuming database resources. Reducing the pool size will improve resource utilization without impacting payment processing throughput, as current traffic analysis shows peak concurrent connections remain well below the new limit.

## Rollout

Deployment is scheduled for 2026-03-12. Sara Haddad will deploy the change at 13:55 UTC. The modification will be applied directly to the ledger service configuration without a canary deployment, as the change is isolated to connection pool parameters and poses minimal risk to payment processing.

## Rollback plan

If any issues are detected post-deployment, the change can be quickly rolled back by restoring max_connections from 200 to 20 to its previous value and restarting the ledger service. Monitoring will track connection pool utilization and any rejected connection attempts immediately after deployment.

## Approval

Approved by Oskar Lind, lead of the Ledger team.

## Status

Marked low risk. Deployed at 13:55 UTC by Sara Haddad. This change was rolled back at 14:41 UTC during INC-301.
