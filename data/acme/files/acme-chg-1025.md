# Change CHG-1025: run report exports as background jobs

Document: CHG-1025

Date: 2026-02-26

Services: merchant-portal, notifications

## Description

This change implements background job processing for report exports in the merchant-portal service, as a follow-up to INC-203. Previously, merchants initiated report exports through the web interface and waited for synchronous processing, which caused performance degradation during peak usage.

With this change, when a merchant requests a report export, the merchant-portal service queues the export as a background job. The export processing happens asynchronously. Once complete, the notifications service sends an email to the merchant containing a download link. The merchant can then retrieve the generated report at their convenience.

The background jobs are processed by a worker pool that scales independently of the web request handlers. This decouples report generation from the merchant portal's request-response cycle.

## Reason

INC-203 identified that synchronous report exports were blocking merchant portal requests and contributing to slow page load times. Moving exports to background jobs reduces latency for all merchant portal users and improves the overall user experience. The download link delivery via email provides merchants with a clear notification and direct access to their reports.

## Rollout

Deployed by Jonas Berg on 2026-02-26. The change affects the merchant-portal and notifications services. Merchants will see a confirmation message when they request a report export, informing them that they will receive a download link by email once the export completes.

## Rollback plan

If issues arise, the deployment can be rolled back by reverting the merchant-portal and notifications service versions to their previous releases. This will restore synchronous report export behavior. Merchants with pending background jobs will receive notification emails with download links for any exports that completed before rollback.

## Approval

Approved by Hannah Kim, lead of the Merchant Experience team.

## Status

Deployed.
