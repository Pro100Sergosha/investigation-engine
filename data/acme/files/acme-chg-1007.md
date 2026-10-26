# Change CHG-1007: raise NorthBank authorization timeout

Document: CHG-1007

Date: 2026-01-14

Services: card-gateway

## Description

This change raises the card-gateway timeout for authorization requests to NorthBank from 5 seconds to 8 seconds. The timeout applies to all card authorization attempts sent through the card-gateway service to our acquiring bank partner NorthBank.

## Reason

NorthBank latency rose during evening peaks, causing authorization requests to exceed the current 5-second timeout window. This resulted in unnecessary payment declines during high-traffic periods. Increasing the timeout to 8 seconds accommodates the elevated latency while maintaining reasonable response times for the payments-api and merchant checkout flows.

## Rollout

Lena Vogel deployed this change to the card-gateway service on 2026-01-14. The timeout parameter was updated in the service configuration and applied to all new authorization requests immediately upon deployment.

## Rollback plan

If authorization success rates do not improve or if timeout-related issues emerge, the timeout can be reverted to 5 seconds by redeploying the previous card-gateway configuration. This rollback requires no database changes and can be executed within minutes. Refer to RB-05 for detailed procedures.

## Approval

This change was approved by Daniel Okafor, lead of the Card Gateway team.

## Status

Deployed on 2026-01-14.
