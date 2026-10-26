# Change CHG-1055: upgrade the 3-D Secure library

Document: CHG-1055

Date: 2026-03-25

Services: card-gateway

## Description

This change upgrades the 3-D Secure library in card-gateway to version 2.4.1. The 3-D Secure library handles authentication challenges for card payments and is a critical component of the Card Gateway team's payment authorization flow.

## Reason

The upgrade to version 2.4.1 includes performance improvements and bug fixes that enhance the reliability of 3-D Secure challenge handling. These improvements reduce latency in the authorization path and improve compatibility with issuer systems.

## Rollout

Lena Vogel deployed this change on 2026-03-25. The deployment followed standard procedures for card-gateway updates, with monitoring of authorization success rates and challenge response times during the rollout window.

## Rollback plan

In the event of elevated error rates or failed challenges, the change can be rolled back by reverting the library version to the previous release and redeploying card-gateway. Rollback can be executed within minutes if needed. The Card Gateway team maintains runbooks for rapid rollback procedures.

## Approval

This change was approved by Daniel Okafor, lead of the Card Gateway team.

## Status

The change was rolled back on 2026-03-26 during INC-303. See INC-303 for details on the incident that prompted the rollback.
