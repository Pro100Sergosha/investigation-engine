# Change CHG-1068: new Sentinel ID redirect URI

Document: CHG-1068

Date: 2026-04-07

Services: merchant-portal

## Description

This change updates the merchant-portal SSO redirect URI to https://portal.acmepay.example/auth/callback as part of moving the merchant portal to a new domain. The redirect URI is used by Sentinel ID to return merchants to the portal after authentication.

## Reason

The merchant portal is being migrated to a new domain. The SSO redirect URI must be updated in Sentinel ID configuration to match the new portal location. This ensures merchants can successfully log in after the domain migration is complete. See INC-401 for context on recent login issues.

## Rollout

The change was deployed at 08:30 UTC by Jonas Berg. The deployment updates the Sentinel ID redirect URI configuration for the merchant-portal service to the new callback endpoint.

## Rollback plan

If login failures occur after deployment, the redirect URI can be reverted to the previous value in Sentinel ID configuration. This requires coordination with the Sentinel ID provider to update the registered redirect URI. The merchant-portal service itself does not require code changes to rollback.

## Approval

This change was approved by Hannah Kim.

## Status

Deployed. The redirect URI is now configured as https://portal.acmepay.example/auth/callback in Sentinel ID.
