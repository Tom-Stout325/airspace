from django.db import migrations, models
import django.core.validators
import airspace.models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0010_dronezone_timezone_radius"),
    ]

    operations = [
        migrations.AddField(
            model_name="operationsplanning",
            name="operation_map",
            field=models.FileField(
                blank=True,
                help_text=(
                    "Upload an annotated operating-area map as PDF, PNG, JPG, JPEG, or WebP."
                ),
                upload_to=airspace.models.operation_map_upload_to,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"]
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="operationsplanning",
            name="operation_map_notes",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Optional notes describing map markings, boundaries, launch and recovery points, emergency landing areas, or other geographic details."
                ),
            ),
        ),
    ]
