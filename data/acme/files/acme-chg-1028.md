# Change CHG-1028: card velocity rule

Document: CHG-1028

Date: 2026-02-27

Services: fraud-scorer

## Description

This change adds a card velocity rule to the fraud-scorer service. The rule sends payments for review when more than 5 payments in 10 minutes are detected on the same card. The rule operates alongside the existing fraud model to catch potential card testing or rapid-fire fraud patterns that may not be caught by the model alone.

## Reason

Card velocity is a common fraud indicator. Legitimate merchants rarely process more than 5 payments in 10 minutes on the same card. By flagging these transactions for review, we reduce fraud losses while maintaining merchant experience for normal payment patterns.

## Rollout

Marco Bellini deployed this change to the fraud-scorer service on 2026-02-27. The rule is active in production and applies to all incoming payments. Merchants will see flagged payments held in review status until the Risk team processes them.

## Rollback plan

If the rule causes excessive false positives or operational issues, the velocity check can be disabled by removing the rule configuration from fraud-scorer without requiring a code deployment. The fraud model will continue to operate normally. Rollback can be completed within 15 minutes.

## Approval

This change was approved by Ines Duarte, lead of the Risk team.

## Status

Deployed to production on 2026-02-27.
