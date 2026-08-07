from django.db import migrations, models


VALID_TIME_ZONES = {
    "SST",
    "HAST",
    "AKST",
    "PST",
    "MST",
    "CST",
    "EST",
    "AST",
    "CHST",
}

LEGACY_TIME_ZONE_MAP = {
    "Samoa Standard Time": "SST",
    "Samoa Standard Time (SST)": "SST",
    "Hawaii-Aleutian Standard Time": "HAST",
    "Hawaii-Aleutian Standard Time (HAST)": "HAST",
    "Alaska Standard Time": "AKST",
    "Alaska Standard Time (AKST)": "AKST",
    "Pacific Standard Time": "PST",
    "Pacific Standard Time (PST)": "PST",
    "Pacific": "PST",
    "Mountain Standard Time": "MST",
    "Mountain Standard Time (MST)": "MST",
    "Mountain": "MST",
    "Central Standard Time": "CST",
    "Central Standard Time (CST)": "CST",
    "Central": "CST",
    "Eastern Standard Time": "EST",
    "Eastern Standard Time (EST)": "EST",
    "Eastern": "EST",
    "Atlantic Standard Time": "AST",
    "Atlantic Standard Time (AST)": "AST",
    "Atlantic": "AST",
    "Chamorro Standard Time": "CHST",
    "Chamorro Standard Time (CHST)": "CHST",
}


def normalize_existing_time_zones(apps, schema_editor):
    OperationsPlanning = apps.get_model(
        "airspace",
        "OperationsPlanning",
    )

    for operation in OperationsPlanning.objects.exclude(
        local_time_zone="",
    ).iterator():
        current = (operation.local_time_zone or "").strip()

        if current in VALID_TIME_ZONES:
            continue

        normalized = LEGACY_TIME_ZONE_MAP.get(current)

        if normalized is None:
            upper = current.upper()
            for code in VALID_TIME_ZONES:
                if code in upper:
                    normalized = code
                    break

        # Preserve database validity even when an old custom IANA value cannot
        # be safely mapped to the exact DroneZone selection. The user can then
        # choose the correct FAA option when editing the operation.
        operation.local_time_zone = normalized or ""
        operation.save(update_fields=["local_time_zone"])


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0009_conops_source_freshness"),
    ]

    operations = [
        migrations.RunPython(
            normalize_existing_time_zones,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="operationsplanning",
            name="local_time_zone",
            field=models.CharField(
                blank=True,
                choices=[
                    ("SST", "Samoa Standard Time (SST) [UTC-11]"),
                    (
                        "HAST",
                        "Hawaii-Aleutian Standard Time (HAST) [UTC-10]",
                    ),
                    (
                        "AKST",
                        "Alaska Standard Time (AKST) [UTC-9]",
                    ),
                    (
                        "PST",
                        "Pacific Standard Time (PST) [UTC-8]",
                    ),
                    (
                        "MST",
                        "Mountain Standard Time (MST) [UTC-7]",
                    ),
                    (
                        "CST",
                        "Central Standard Time (CST) [UTC-6]",
                    ),
                    (
                        "EST",
                        "Eastern Standard Time (EST) [UTC-5]",
                    ),
                    (
                        "AST",
                        "Atlantic Standard Time (AST) [UTC-4]",
                    ),
                    (
                        "CHST",
                        "Chamorro Standard Time (CHST) [UTC+10]",
                    ),
                ],
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="operationsplanning",
            name="dronezone_radius",
            field=models.CharField(
                blank=True,
                choices=[
                    ("0.1_nm", "1/10th NM"),
                    ("0.25_nm", "1/4th NM"),
                    ("0.5_nm", "1/2 NM"),
                    ("0.75_nm", "3/4th NM"),
                    ("1_nm", "1 NM"),
                    ("1_2_nm", "1-2 NM"),
                    ("2_3_nm", "2-3 NM"),
                    (
                        "blanket_wide_area",
                        "Blanket Area / Wide Area",
                    ),
                ],
                max_length=30,
            ),
        ),
    ]
