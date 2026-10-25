# Change CHG-1058: fraud-scorer model v3.5 in shadow mode

Document: CHG-1058

Date: 2026-03-30

Services: fraud-scorer

## Description

fraud-scorer model v3.5 is deployed in shadow mode on the fraud-scorer service. In shadow mode, v3.5 scores every payment for fraud risk but does not affect payment decisions. Scores are logged for analysis without influencing whether payments are approved or declined. This deployment allows the Risk team to validate v3.5 behavior against production traffic before any switch to live scoring.

## Reason

Model v3.4 was rolled back following INC-201 due to false declines of legitimate payments. v3.5 represents the next iteration of the fraud-scoring model. Shadow mode deployment enables the Risk team to observe v3.5 performance on real payment data without customer impact, reducing risk before any production cutover.

## Rollout

v3.5 is deployed to shadow mode on the fraud-scorer service by Marco Bellini. The model will score payments in shadow mode for 7 days. During this period, the Risk team will monitor shadow scores, compare them against v3.4 decisions, and analyze any significant differences. At the end of 7 days, the team will decide whether to proceed with a live cutover, extend the shadow period, or roll back.

## Rollback plan

If issues are identified during the 7-day shadow period, v3.5 can be removed from shadow mode by reverting the deployment. Refer to RB-06 for detailed rollback procedures. No customer-facing changes occur during shadow mode, so rollback carries no customer impact.

## Approval

This change is approved by Ines Duarte, lead of the Risk team.

## Status

Deployed on 2026-03-30. Shadow mode observation in progress.
