# AirSpace Operation Edit Prefill Patch

This patch ensures that saved operation-planning information is displayed when
the user selects **Edit operation**.

It:

- Confirms the edit view passes `instance=operation`.
- Preserves POSTed values when validation fails.
- Restores saved checkbox groups and coordinates.
- Prepopulates the address-search helper from the saved venue and address.
- Does not overwrite user input or validation errors.

Install from the Django project root:

    python apply_operation_edit_prefill_patch.py
    python manage.py check
    python manage.py test airspace
    python manage.py test

No migration is required.
