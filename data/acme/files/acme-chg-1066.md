# Change CHG-1066: ledger-db failover test

Document: CHG-1066

Date: 2026-04-06

Services: ledger

## Description

Planned failover test of ledger-db to validate disaster recovery procedures and ensure the ledger service can successfully transition to its standby database instance. The test followed the failover runbook RB-11 and was announced to merchants via status page update STS-306.

## Reason

Regular failover testing is essential to verify that the ledger service can maintain availability during database failures. This test validates the runbook procedures, confirms failover automation works as expected, and ensures the team can execute manual steps if needed.

## Rollout

The failover test was executed by Sara Haddad on 2026-04-06 at 01:00 UTC. The test involved triggering a failover of ledger-db from the primary instance to the standby instance following documented procedures in RB-11. Failover completed in 41 seconds. During this window, the ledger service experienced a brief interruption while connections were redirected to the standby database. All ledger operations resumed normally after failover completion.

## Rollback plan

No rollback was required. The failover test completed successfully and the standby instance is now confirmed as operational. If issues had been detected during the test, the procedure would have involved failing back to the original primary instance using the same runbook procedures.

## Approval

This change was approved by Oskar Lind, lead of the Ledger team.

## Status

Complete. The failover test validated that ledger-db can successfully transition to its standby instance within the expected timeframe. The ledger service remained available throughout the test window. All procedures in RB-11 executed as documented.
