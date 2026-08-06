from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0003_simplify_operation_aircraft"),
    ]

    operations = [
        migrations.RenameField(
            model_name="operationapproval",
            old_name="requested_relief",
            new_name="requested_operation",
        ),
        migrations.RenameField(
            model_name="operationapproval",
            old_name="safety_case",
            new_name="safety_justification",
        ),
        migrations.RemoveField(
            model_name="operationapproval",
            name="regulation_requested",
        ),
        migrations.AlterField(
            model_name="operationapproval",
            name="status",
            field=models.CharField(
                choices=[
                    ("planning", "Planning"),
                    ("ready", "Ready to Submit"),
                    ("submitted", "Submitted"),
                    ("faa_review", "FAA Review"),
                    (
                        "additional_information",
                        "Additional Information Requested",
                    ),
                    ("approved", "Approved"),
                    ("denied", "Denied"),
                    ("expired", "Expired"),
                    ("withdrawn", "Withdrawn"),
                ],
                default="planning",
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="operationapproval",
            name="requested_operation",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Describe exactly what permission or authorization is "
                    "requested for this operation."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationapproval",
            name="safety_justification",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Explain why the proposed operation can be conducted "
                    "safely."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationapproval",
            name="risk_mitigations",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Describe the personnel, procedures, equipment, and "
                    "operational controls that reduce the risks created by "
                    "the requested operation."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationapproval",
            name="equivalent_level_of_safety",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Explain how the proposed controls provide a level of "
                    "safety equal to or greater than compliance with the "
                    "regulation."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationapproval",
            name="special_provisions",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Record special provisions, conditions, or operating "
                    "limitations included in the issued FAA approval."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationapproval",
            name="reviewer_notes",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Optional notes about FAA correspondence, reviewer "
                    "requests, or internal follow-up."
                ),
            ),
        ),
    ]
