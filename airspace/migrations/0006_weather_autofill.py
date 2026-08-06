from django.db import migrations, models

def populate_standard_weather(apps, schema_editor):
    OperationsPlanning = apps.get_model("airspace", "OperationsPlanning")
    OperationsPlanning.objects.filter(min_visibility_sm__isnull=True).update(min_visibility_sm="3.0")
    OperationsPlanning.objects.filter(minimum_distance_below_clouds_ft__isnull=True).update(minimum_distance_below_clouds_ft=500)
    OperationsPlanning.objects.filter(minimum_horizontal_cloud_clearance_ft__isnull=True).update(minimum_horizontal_cloud_clearance_ft=2000)

class Migration(migrations.Migration):
    dependencies = [("airspace", "0005_conops_application_constraint")]
    operations = [
        migrations.AddField(
            model_name="operationsplanning",
            name="uses_standard_part_107_weather_minimums",
            field=models.BooleanField(default=True, help_text="Use the standard Part 107 minimums of 3 statute miles flight visibility, 500 feet below clouds, and 2,000 feet horizontally from clouds."),
        ),
        migrations.RunPython(populate_standard_weather, migrations.RunPython.noop),
    ]
