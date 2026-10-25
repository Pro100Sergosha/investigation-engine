# Change CHG-1064: move to the new NorthBank TLS endpoint

Document: CHG-1064

Date: 2026-04-03

Services: card-gateway

## Description

Card Gateway team will migrate the card-gateway service to connect to NorthBank's new TLS endpoint at auth2.northbank.example. This endpoint replaces the legacy connection and is part of the announced maintenance window detailed in STS-305.

The migration involves updating the endpoint configuration in card-gateway to point to auth2.northbank.example for all card authorization requests sent to NorthBank. No changes to the authorization request format or response handling are required. The service will validate TLS certificates against the new endpoint during the handshake.

## Reason

NorthBank is retiring legacy TLS endpoints and requires all acquiring partners to migrate to their new infrastructure. The new endpoint provides improved security posture and aligns with current industry standards for payment processing connections.

## Rollout

Deployment will occur at 22:00 UTC on 2026-04-03 during the scheduled maintenance window. Lena Vogel will execute the deployment, which involves updating the NorthBank endpoint configuration in card-gateway and restarting the service. The change will be applied to the production environment.

Monitoring will track authorization success rates and latency metrics during and after the deployment. The Merchant Experience team will monitor webhook delivery for payment events to ensure downstream systems receive notifications without delay.

## Rollback plan

If authorization failures or elevated latency occur after deployment, card-gateway will revert to the legacy endpoint configuration and restart the service. This rollback can be executed within minutes. Refer to RB-05 for detailed troubleshooting steps if authorization timeouts are observed.

## Approval

This change is approved by Daniel Okafor, lead of the Card Gateway team.

## Status

Scheduled for deployment at 22:00 UTC on 2026-04-03.
