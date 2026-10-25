# Change CHG-1040: new email provider for merchant notifications

Document: CHG-1040

Date: 2026-03-10

Services: notifications

## Description

This change migrates merchant notification emails from the current email provider to MailRelay. Prior to deployment, sender authentication records have been configured: SPF and DKIM are now in place to ensure proper email authentication and deliverability.

The notifications service will be updated to route all merchant-facing emails through MailRelay endpoints. This includes payment confirmations, settlement reports, and alert notifications that merchants receive at their registered email addresses.

## Reason

MailRelay provides improved deliverability rates and better compliance with email authentication standards. The new provider offers enhanced monitoring and reporting capabilities for merchant communications, reducing the risk of notifications being filtered as spam or rejected by recipient mail servers.

## Rollout

Jonas Berg will execute the deployment on 2026-03-10. The change involves updating configuration in the notifications service to point SMTP connections to MailRelay infrastructure. SPF and DKIM records have already been validated in DNS to support this transition.

The deployment will be performed during standard maintenance windows to minimize any service interruption. Merchant notification queues will be monitored during and after the cutover to ensure emails are being delivered successfully through the new provider.

## Rollback plan

If issues arise with MailRelay delivery, the notifications service configuration can be reverted to the previous email provider within minutes. DNS records for SPF and DKIM will remain in place and do not require changes for rollback. A rollback would restore SMTP endpoints to the prior provider's infrastructure.

## Approval

This change has been approved by Hannah Kim, lead of the Merchant Experience team.

## Status

Scheduled for deployment on 2026-03-10.
