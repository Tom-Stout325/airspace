from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0004_approval_workflow"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="approvalapplication",
            constraint=models.UniqueConstraint(
                fields=("approval",),
                name="unique_application_per_operation_approval",
            ),
        ),
    ]
