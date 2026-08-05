# AirSpace invitation system patches

These patches were generated against the uploaded `AirSpace.zip` project and are intended for Django 5.2.

## Apply the patches

From the root of your AirSpace Git repository:

```bash
for patch in /path/to/AirSpace_invitation_patches/ordered/*.patch; do
    git apply --check "$patch"
    git apply "$patch"
done
```

Alternatively, apply the consolidated patch:

```bash
git apply --check AirSpace-invitation-system-all-in-one.patch
git apply AirSpace-invitation-system-all-in-one.patch
```

Do not apply both methods.

## Feature mapping

1. **Invitation model** — ordered patch 0001
2. **Secure token generation** — ordered patch 0002
3. **Admin invitation page and invitation email templates** — ordered patch 0003
4. **Invite acceptance and locked-email registration** — ordered patch 0004
5. **Public-registration restriction** — ordered patch 0004
6. **Automatic PilotProfile creation** — ordered patch 0004
7. **Post-registration Pilot Profile onboarding** — ordered patch 0004
8. **Invalid, expired, accepted, revoked, and duplicate handling** — ordered patches 0003–0004
9. **Admin navigation and Django admin registration** — ordered patch 0005
10. **Email delivery logging** — ordered patch 0006
11. **Gmail SMTP and invitation-expiry configuration** — ordered patch 0007
12. **Staff permissions and cross-user ownership tests** — ordered patch 0008

## Required environment variables

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=airspacewaiverapp@gmail.com
EMAIL_HOST_PASSWORD=<Google app password, without spaces>
DEFAULT_FROM_EMAIL=AirSpace <airspacewaiverapp@gmail.com>
INVITATION_EXPIRY_HOURS=72
```

For Heroku, set these as config vars. Never commit the Gmail app password.

## After applying

```bash
python manage.py makemigrations --check
python manage.py migrate
python manage.py check
python manage.py test accounts airspace
```

The code was syntax-checked with `python -m compileall`. Full database-backed tests were not run because the uploaded project is configured for PostgreSQL and no project database was included in the ZIP.

## New routes

- `/accounts/invitations/` — staff-only invitation management
- `/accounts/invite/<token>/` — invitation acceptance and registration
- `/accounts/onboarding/pilot-profile/` — first-login pilot setup
- `/accounts/register/` — now displays an invitation-required response and cannot create users

## Important behavior

- Invitation tokens are random, unique, single-use, and expire after the configured lifetime.
- Only staff users can send, resend, or revoke invitations.
- The invited email is displayed but disabled in the registration form.
- Account creation and invitation acceptance occur in one database transaction.
- A `PilotProfile` is automatically created for every accepted invitation.
- Failed and successful invitation-email attempts are recorded in Django admin.
- Existing AirSpace waiver views already scope records to `request.user`; tests were added to preserve this protection.
