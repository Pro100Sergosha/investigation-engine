# Change CHG-1052: two-factor authentication for portal admins

Document: CHG-1052

Date: 2026-03-20

Services: merchant-portal

## Description

This change implements two-factor authentication for admin users in the merchant-portal. Admin users must now provide a second authentication factor when logging in, in addition to their Sentinel ID credentials. The second factor is delivered via time-based one-time password (TOTP) to a registered authenticator app on the admin's device.

The change applies only to users with admin privileges in the merchant-portal. Standard merchant users are not affected and continue to use single-factor authentication via Sentinel ID.

## Reason

Admin users have elevated access to merchant accounts, including the ability to modify payment settings, view sensitive transaction data, and manage team members. Requiring two-factor authentication reduces the risk of unauthorized account takeover and protects merchant data from compromise.

## Rollout

The change was deployed on 2026-03-20 by Jonas Berg. Admin users are required to enroll in two-factor authentication on their next login. During enrollment, they scan a QR code with their authenticator app and verify the setup by entering a code. Enrollment takes approximately two minutes per user.

Merchants with multiple admin users must ensure each admin completes enrollment independently. The merchant-portal displays clear enrollment instructions and support documentation during the process.

## Rollback plan

If critical issues arise, the two-factor authentication requirement can be disabled via feature flag, reverting admin users to single-factor authentication. This rollback does not affect user data or settings. Rollback requires approval from the Merchant Experience team lead.

## Approval

This change was approved by Hannah Kim, lead of the Merchant Experience team.

## Status

Deployed and active.
