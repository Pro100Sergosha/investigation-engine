# Change CHG-1074: fix the settlement import time zone

Document: CHG-1074

Date: 2026-04-16

Services: ledger

## Description

This change deploys a one-off script to the ledger service that corrects 297 ledger entries affected by a time zone conversion issue in the settlement import process. The script converts UTC+2 timestamps to UTC, aligning the affected entries with the correct settlement times.

## Reason

Follow-up to INC-402, which identified a ledger reconciliation mismatch. The settlement import introduced in CHG-1072 was converting UTC+2 timestamps to UTC incorrectly, causing entries to be recorded with wrong timestamps. This correction script addresses the backlog of affected entries and ensures ledger accuracy going forward.

## Rollout

Sara Haddad deployed the one-off correction script on 2026-04-16. The script runs against the ledger-db Postgres database and updates the 297 affected entries to reflect the correct UTC timestamps. The script is idempotent and can be safely re-run if needed. No service restart is required.

## Rollback plan

If the correction script produces unexpected results, the affected entries can be restored from the ledger-db backup taken prior to deployment. The script can be rolled back by restoring the backup and re-running the settlement import process with the corrected time zone handling from CHG-1072.

## Approval

Approved by Oskar Lind, lead of the Ledger team.

## Status

Deployed on 2026-04-16.
