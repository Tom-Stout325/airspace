from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0012_operationsplanning_flight_tracking_service"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalapplication",
            name="description_is_complete",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="approvalapplication",
            name="description_validated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
