# AirSpace CONOPS Generation and Review Patch

This patch adds deterministic CONOPS generation and section-by-section
review for each required FAA waiver or approval.

## Workflow

On the operation detail page, each FAA approval now includes:

    Build / Review CONOPS

Opening the workspace:

1. Creates one `ApprovalApplication` for the selected approval.
2. Generates structured CONOPS sections from the current operation plan.
3. Opens a review screen where each section can be edited and marked
   complete.
4. Automatically protects any manually edited section from regeneration.
5. Allows unlocked sections to be regenerated after planning data changes.

## Generated sections

- Operation Overview and Purpose
- Requested FAA Waiver / Approval
- Dates, Location, Altitude, and Airspace
- Remote Pilot and Crew
- Aircraft and Safety Systems
- Operational Area and Containment
- Ground and Air Risk Controls
- Lost-Link and Emergency Procedures
- Weather and Night Operations
- Safety Justification
- Approval-Specific Risk Mitigations
- Equivalent Level of Safety
- Operational Commitment

Generation is template-driven and does not call an AI service. The text is
built only from the saved operation, aircraft, pilot, risk, emergency, and
approval information.

## Regeneration safety

- New sections are generated automatically.
- Unlocked sections can be refreshed from current planning data.
- Locked sections are never overwritten.
- Editing a section automatically locks it when the review is saved.
- The complete combined draft is synchronized to
  `ApprovalApplication.description`.

## Files

- `airspace/models.py`
- `airspace/conops.py`
- `airspace/views.py`
- `airspace/urls.py`
- `airspace/test_conops.py`
- `airspace/migrations/0005_conops_application_constraint.py`
- `airspace/templates/airspace/conops_review.html`
- `airspace/templates/airspace/operations_planning_detail.html`

## Install

Extract into the Django project root and replace matching files.

Then run:

    python manage.py migrate
    python manage.py check
    python manage.py test airspace
    python manage.py test

## Database note

The migration enforces one `ApprovalApplication` per
`OperationApproval`. If duplicate applications were manually created
before installing this patch, remove or consolidate the duplicates before
running the migration.
