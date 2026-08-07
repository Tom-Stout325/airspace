from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0008_ai_conops_v1"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalapplication",
            name="conops_source_updated_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    "Latest planning-source timestamp represented by the "
                    "currently generated AI CONOPS."
                ),
            ),
        ),
    ]
