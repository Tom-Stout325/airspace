#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path.cwd()
FORMS = ROOT / "airspace" / "forms.py"
VIEWS = ROOT / "airspace" / "views.py"

MARKER = "AIRSPACE_OPERATION_EDIT_PREFILL"


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def patch_views(text):
    old = (
        '    form = OperationsPlanningForm(request.POST or None, '
        'instance=operation, user=request.user)\n'
    )
    new = (
        '    form = OperationsPlanningForm(\n'
        '        request.POST if request.method == "POST" else None,\n'
        '        instance=operation,\n'
        '        user=request.user,\n'
        '    )\n'
    )

    if old in text:
        return text.replace(old, new, 1)

    if (
        "def operations_planning_edit" in text
        and "instance=operation" in text
    ):
        return text

    fail(
        "Could not confirm that operations_planning_edit() passes "
        "instance=operation to OperationsPlanningForm."
    )


def patch_forms(text):
    if MARKER in text:
        return text

    anchor = (
        '        self.user = user\n\n'
        '        self.fields["pilot_profile"].queryset = (\n'
    )

    addition = (
        '        self.user = user\n\n'
        '        # AIRSPACE_OPERATION_EDIT_PREFILL\n'
        '        # Explicitly restore values for fields declared directly on\n'
        '        # the form. Only unbound edit forms are changed, so submitted\n'
        '        # values and validation errors are never overwritten.\n'
        '        if self.instance and self.instance.pk and not self.is_bound:\n'
        '            stored_value_fields = (\n'
        '                "timeframe",\n'
        '                "purpose_operations",\n'
        '                "ground_environment",\n'
        '                "prepared_procedures",\n'
        '                "location_latitude",\n'
        '                "location_longitude",\n'
        '                "launch_latitude",\n'
        '                "launch_longitude",\n'
        '            )\n\n'
        '            for field_name in stored_value_fields:\n'
        '                if field_name not in self.fields:\n'
        '                    continue\n\n'
        '                value = getattr(self.instance, field_name, None)\n\n'
        '                if field_name in {\n'
        '                    "timeframe",\n'
        '                    "purpose_operations",\n'
        '                    "ground_environment",\n'
        '                    "prepared_procedures",\n'
        '                }:\n'
        '                    value = list(value or [])\n\n'
        '                self.initial[field_name] = value\n\n'
        '            address_parts = [\n'
        '                getattr(self.instance, "venue_name", "") or "",\n'
        '                getattr(self.instance, "street_address", "") or "",\n'
        '                getattr(self.instance, "location_city", "") or "",\n'
        '                getattr(self.instance, "location_state", "") or "",\n'
        '                getattr(self.instance, "zip_code", "") or "",\n'
        '            ]\n'
        '            self.initial["address_search"] = ", ".join(\n'
        '                part.strip()\n'
        '                for part in address_parts\n'
        '                if part and part.strip()\n'
        '            )\n\n'
        '        self.fields["pilot_profile"].queryset = (\n'
    )

    if anchor not in text:
        fail(
            "Could not find OperationsPlanningForm.__init__() insertion point."
        )

    return text.replace(anchor, addition, 1)


def main():
    if not FORMS.exists():
        fail(f"File not found: {FORMS}")
    if not VIEWS.exists():
        fail(f"File not found: {VIEWS}")

    forms_text = FORMS.read_text(encoding="utf-8")
    views_text = VIEWS.read_text(encoding="utf-8")

    FORMS.write_text(patch_forms(forms_text), encoding="utf-8")
    VIEWS.write_text(patch_views(views_text), encoding="utf-8")

    print("AirSpace operation edit prefill patch applied.")
    print("Updated: airspace/forms.py")
    print("Updated: airspace/views.py")
    print("No migration is required.")


if __name__ == "__main__":
    main()
