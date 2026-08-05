# AirSpace Pilot Dashboard and Profile CRUD

This patch adds a mobile-first, user-scoped Pilot dashboard and Pilot Profile management workflow.

## Included

- Pilot dashboard showing the logged-in user's current information
- Profile completion indicator
- Create/update form for:
  - First name
  - Last name
  - Business name
  - Email
  - Street address
  - City
  - State
  - ZIP code
  - Phone
  - FAA certificate number
- Profile data deletion with confirmation
- User-scoped queries and tests
- Pilot URL namespace at `/pilot/`
- Invitation onboarding redirect to the Pilot Profile editor
- AirSpace portal Pilot Profile link updated to the Pilot dashboard
- Database migration for the new PilotProfile fields

The delete action removes the PilotProfile data and clears the user's name and phone, but deliberately preserves the login account and email address.

## Apply

From the AirSpace project root:

```bash
git apply --check AirSpace-pilot-dashboard-crud.patch
git apply AirSpace-pilot-dashboard-crud.patch
```

## Migrate and test

```bash
python manage.py migrate
python manage.py check
python manage.py test pilot accounts airspace -v 2
```

## URLs

- Dashboard: `/pilot/`
- Edit/create: `/pilot/profile/edit/`
- Delete profile data: `/pilot/profile/delete/`

## Notes

The existing `PilotProfile` model name and `request.user.pilot_profile` relationship are retained to avoid unnecessary renaming and migration complexity.
