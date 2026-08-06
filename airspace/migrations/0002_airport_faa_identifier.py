from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="airport",
            name="faa_identifier",
            field=models.CharField(
                blank=True,
                help_text="FAA location identifier from APT_BASE.ARPT_ID.",
                max_length=10,
                null=True,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="airport",
            name="icao",
            field=models.CharField(
                blank=True,
                help_text="ICAO identifier when assigned.",
                max_length=4,
                null=True,
                unique=True,
            ),
        ),
    ]
