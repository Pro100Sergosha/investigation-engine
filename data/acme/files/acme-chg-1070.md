# Change CHG-1070: card-gateway autoscaling

Document: CHG-1070

Date: 2026-04-09

Services: card-gateway

## Description

card-gateway now scales out on CPU instead of running a fixed number of instances. The service maintains a minimum of 4 instances and automatically scales up when CPU reaches 70%. This change enables the service to handle traffic spikes without manual intervention while maintaining cost efficiency during low-traffic periods.

## Reason

The previous fixed-instance configuration required manual scaling decisions and could not respond quickly to sudden increases in card authorization volume. By implementing CPU-based autoscaling at 70% CPU, card-gateway can automatically provision additional capacity when needed, reducing latency during peak periods and improving the reliability of payment authorization requests sent to NorthBank.

## Rollout

Lena Vogel deployed the autoscaling configuration on 2026-04-09. The change was applied to the card-gateway service in the production environment. Monitoring was enabled to track CPU utilization and instance count changes in real time.

## Rollback plan

If autoscaling causes unexpected behavior or cost increases, the deployment can be rolled back to the fixed-instance configuration. The previous instance count and resource allocation settings are retained in version control and can be redeployed within minutes. Lena Vogel and the Card Gateway team can execute the rollback without requiring additional approvals.

## Approval

This change was approved by Daniel Okafor, lead of the Card Gateway team.

## Status

Deployed on 2026-04-09.
