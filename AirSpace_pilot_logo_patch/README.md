# AirSpace Pilot Logo Patch

This patch adds an optional, user-scoped pilot or business logo to the Pilot Profile.

## Included

- JPG, PNG, and WebP uploads up to 5 MB.
- Current-logo preview, replacement, and Django's standard clear checkbox.
- Logo display on the Pilot Dashboard.
- Authenticated logo delivery scoped to the logged-in user.
- Pilot logo on generated CONOPS PDFs.
- AirSpace logo fallback when a pilot has not uploaded a logo.
- Storage-independent PDF embedding compatible with local media and S3.
- Database migration and user-isolation test coverage.

## Apply

Download and extract this ZIP into the AirSpace project directory. Then run:

```bash
git apply --check AirSpace_pilot_logo_patch/AirSpace-pilot-logo.patch
git apply AirSpace_pilot_logo_patch/AirSpace-pilot-logo.patch
python manage.py migrate
python manage.py check
python manage.py test pilot accounts airspace -v 2
```

The logo is optional and is not included in the profile-completion percentage.
