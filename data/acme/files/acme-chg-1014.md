# Change CHG-1014: index on ledger entries by created_at

Document: CHG-1014

Date: 2026-01-28

Services: ledger

## Description

This change adds an index on the ledger entries table to speed up daily reports. The index is created on the created_at column using CREATE INDEX CONCURRENTLY to avoid locking the table during the operation.

## Reason

Daily report queries that filter ledger entries by created_at currently perform full table scans. Adding this index will reduce query latency and database load during peak reporting hours. The concurrent index creation allows the change to be deployed without blocking normal payment processing.

## Rollout

The index is deployed to the ledger-db Postgres database by Sara Haddad. The CREATE INDEX CONCURRENTLY command is executed during standard maintenance windows to minimize any performance impact. No application code changes are required; the database query planner will automatically use the new index.

## Rollback plan

If the index causes unexpected performance degradation, it can be dropped with DROP INDEX CONCURRENTLY ledger_entries_created_at_idx without locking the table. This operation takes longer than a standard drop but allows concurrent queries to continue. The ledger service will continue to function normally during and after index removal.

## Approval

This change is approved by Oskar Lind, lead of the Ledger team.

## Status

Deployed on 2026-01-28.
