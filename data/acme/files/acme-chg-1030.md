# Change CHG-1030: ledger-db Postgres minor upgrade

Document: CHG-1030

Date: 2026-03-02

Services: ledger

## Description

This change upgrades the ledger-db Postgres database from Postgres 16.3 to 16.4. The upgrade is a minor version bump that includes bug fixes and performance improvements from the upstream Postgres project. The upgrade will be performed during the announced maintenance window documented in STS-210.

## Reason

Minor version upgrades to Postgres are part of regular maintenance to ensure the ledger service runs on a supported and patched database version. Version 16.4 addresses known issues in 16.3 and improves stability of the double-entry ledger that records every money movement across Acme Payments.

## Rollout

The upgrade will be deployed by Sara Haddad on 2026-03-02 at 02:00 UTC. The ledger-db instance will be taken offline during the upgrade window. Merchants will not be able to process payments during this time, as documented in STS-210. The upgrade process follows standard Postgres minor version procedures and is expected to complete within the maintenance window.

## Rollback plan

If the upgrade encounters issues, the previous version can be restored from a backup taken before the upgrade begins. The ledger-db failover procedure documented in RB-11 can be used to restore service if needed. Rollback will restore the database to its state before the upgrade.

## Approval

This change is approved by Oskar Lind, lead of the Ledger team.

## Status

Scheduled for deployment during the announced maintenance window on 2026-03-02 at 02:00 UTC.
