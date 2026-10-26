# Change CHG-1022: new reports export page

Document: CHG-1022

Date: 2026-02-17

Services: merchant-portal

## Description

This change adds a reports export page to merchant-portal. The new page allows merchants to export their payments data in CSV and XLSX formats. Merchants can access the reports page from the main dashboard and select their desired export format and date range.

## Reason

Merchants have requested the ability to export payment data for reconciliation, accounting and business intelligence purposes. The reports export page addresses this need by providing a self-service mechanism to download transaction history in standard spreadsheet formats.

## Rollout

The change was deployed by Jonas Berg on 2026-02-17. The reports export page is now available to all merchants through merchant-portal.

## Rollback plan

If issues are identified after deployment, the reports export page can be disabled by removing the route from merchant-portal and redeploying. Merchants will see a message indicating the feature is temporarily unavailable. No data migration or database changes are required, so rollback carries no data risk.

## Approval

This change was approved by Hannah Kim, lead of the Merchant Experience team.

## Status

Deployed.
