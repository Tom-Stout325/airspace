from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0002_airport_faa_identifier"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="operationaircraft",
            name="one_primary_drone_per_operation",
        ),
        migrations.RemoveField(
            model_name="operationaircraft",
            name="display_order",
        ),
        migrations.RemoveField(
            model_name="operationaircraft",
            name="is_backup",
        ),
        migrations.RemoveField(
            model_name="operationaircraft",
            name="is_primary",
        ),
        migrations.RemoveField(
            model_name="operationaircraft",
            name="limitations",
        ),
        migrations.RemoveField(
            model_name="operationaircraft",
            name="planned_firmware_version",
        ),
        migrations.RemoveField(
            model_name="operationaircraft",
            name="role",
        ),
        migrations.RemoveField(
            model_name="operationaircraft",
            name="role_description",
        ),
        migrations.AddField(
            model_name="operationaircraft",
            name="current_firmware_installed",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Confirm that the aircraft and controller are running the "
                    "current manufacturer-approved firmware, unless a "
                    "documented operational reason requires another approved "
                    "version."
                ),
            ),
        ),
        migrations.AlterModelOptions(
            name="operationaircraft",
            options={"ordering": ["id"]},
        ),
        migrations.AlterField(
            model_name="operationaircraft",
            name="planned_payload",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Optional camera, sensor, lighting system, propeller "
                    "guards, parachute, Remote ID module, or other attached "
                    "equipment."
                ),
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="operationaircraft",
            name="operation_specific_safety_notes",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Optional safety information unique to this aircraft's use "
                    "during this operation. Examples include additional "
                    "lighting, propeller guards, payload handling, reduced "
                    "operating limits, special battery procedures, or "
                    "environmental restrictions. Leave blank when the standard "
                    "drone safety profile fully applies."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationaircraft",
            name="preflight_airworthiness_verified",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Confirm that the aircraft, batteries, propellers, motors, "
                    "sensors, controls, and attached equipment are in a "
                    "condition for safe operation."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationaircraft",
            name="registration_verified",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Confirm that the FAA registration is current, displayed "
                    "on the aircraft, and matches the aircraft record."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationaircraft",
            name="remote_id_verified",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Confirm that the aircraft's Remote ID information has "
                    "been checked and is operating as required."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="operationaircraft",
            name="safety_features_snapshot",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Snapshot copied automatically from the selected drone's "
                    "saved safety features."
                ),
            ),
        ),
    ]
