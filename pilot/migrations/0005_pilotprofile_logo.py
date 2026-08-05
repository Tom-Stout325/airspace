from django.core.validators import FileExtensionValidator
from django.db import migrations, models

import pilot.validators


class Migration(migrations.Migration):
    dependencies = [
        ("pilot", "0004_rename_license_number_pilotprofile_faa_certificate_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="pilotprofile",
            name="logo",
            field=models.ImageField(
                blank=True,
                help_text="JPG, PNG, or WebP. Maximum file size: 5 MB.",
                upload_to="pilot_logos/%Y/%m/",
                validators=[
                    FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"]),
                    pilot.validators.validate_logo_file_size,
                ],
            ),
        ),
    ]
