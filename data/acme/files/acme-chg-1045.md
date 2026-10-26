# Change CHG-1045: emergency scale-up of notification workers

Document: CHG-1045

Date: 2026-03-12

Services: notifications

## Description

This emergency change scaled up the notification service worker pool to drain the webhook backlog that accumulated during the March 12 outage. The notification workers were increased from 8 to 24 instances to process queued webhook deliveries to merchants.

## Reason

During the March 12 outage, the notifications service fell behind on webhook delivery. Merchants were not receiving real-time updates about payment events. The backlog grew as the service struggled to keep pace with the volume of queued messages. Scaling up worker capacity was necessary to clear the backlog and restore timely webhook delivery to merchants. See INC-306 for the full incident context and RB-07 for the standard webhook backlog procedure.

## Rollout

The emergency change was deployed at 15:05 UTC on March 12, 2026. Jonas Berg executed the scaling operation, increasing the notification worker pool from 8 to 24 instances. The additional workers began processing the backlog immediately upon deployment.

## Rollback plan

If the scaled-up worker pool caused downstream issues or failed to reduce the backlog, the worker count could be reduced back to 8 instances. This rollback would be executed through the same scaling mechanism used for the initial deployment.

## Approval

This emergency change was approved by Hannah Kim, lead of the Merchant Experience team, which owns the notifications service.

## Status

Deployed and active. The notification workers remain at 24 instances to continue processing webhook deliveries.
