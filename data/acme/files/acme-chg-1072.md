# Change CHG-1072: new NorthBank settlement file import

Document: CHG-1072

Date: 2026-04-14

Services: ledger

## Description

This change updates the ledger service to import the new version 2 format of the NorthBank settlement file. The settlement file is used by the daily reconciliation process to verify that all recorded transactions match NorthBank's records. The ledger service will parse the updated file format and load settlement data into ledger-db for reconciliation matching.

## Reason

NorthBank has updated the settlement file format to version 2 format to support additional transaction metadata and improve reconciliation accuracy. The ledger service must be updated to handle this new format to maintain accurate daily reconciliation operations.

## Rollout

The change will be deployed to the ledger service in the production environment. Sara Haddad will execute the deployment. The update includes parser changes to handle version 2 format fields and maintains backward compatibility with existing reconciliation logic. Deployment will occur during standard maintenance windows to minimize impact on reconciliation schedules.

## Rollback plan

If issues are detected after deployment, the ledger service can be rolled back to the previous version that imports the original settlement file format. Rollback will restore the prior parser logic and allow reconciliation to continue with the previous NorthBank settlement file format. Monitoring of reconciliation jobs will alert the team to any parsing failures that would trigger rollback procedures outlined in RB-04.

## Approval

This change is approved by Oskar Lind, lead of the Ledger team.

## Status

Approved and ready for deployment.
