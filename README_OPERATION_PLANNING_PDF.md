# AirSpace Operation Planning PDF Patch

This patch adds a live, printable PDF report for each operation plan.

## Features

- **View / Print PDF** button on the operation detail page
- **Download PDF** button on the operation detail page
- Owner-only PDF access
- Letter-size, print-optimized layout
- AirSpace logo when available at:
  `static/images/AirSpace_logo.png`
- Repeating page footer with operation name and page numbers
- Current planning-completion summary
- Operation and mission details
- RPIC information
- Location, coordinates, nearest airport, and distance
- Assigned aircraft, readiness confirmations, and safety features
- Ground and air risk controls
- Lost-link and emergency procedures
- Weather, night operations, communications, and crew
- FAA waiver/approval planning information
- FAA submission and issued-approval information when available

The PDF is generated live from the current database record and is not
stored in the database.

## URLs

Inline view/print:

    /airspace/operations/<id>/planning-pdf/

Download:

    /airspace/operations/<id>/planning-pdf/?download=1

## Files

- `airspace/views.py`
- `airspace/urls.py`
- `airspace/test_pdf.py`
- `airspace/templates/airspace/operations_planning_detail.html`
- `airspace/templates/airspace/pdf/operation_planning_pdf.html`

## Install

Extract this ZIP into the Django project root and replace matching files.

WeasyPrint must already be installed and import successfully.

Then run:

    python manage.py check
    python manage.py test airspace
    python manage.py test

No migration is required.

## Notes

The report uses `static/images/AirSpace_logo.png` when Django's static-file
finders can locate it. If the logo is stored under another static path,
update the `finders.find(...)` path in `operation_planning_pdf()`.

The PDF response uses `Cache-Control: private, no-store` because planning
documents can contain pilot, aircraft, and operational information.
