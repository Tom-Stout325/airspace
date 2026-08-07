from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0006_weather_autofill"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalapplication",
            name="description_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="approvalapplication",
            name="ai_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="approvalapplication",
            name="ai_generation_model",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
