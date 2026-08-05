from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("drones", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="DroneSafetyProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("brand", models.CharField(choices=[("DJI", "DJI"), ("DJI Enterprise", "DJI Enterprise"), ("Autel", "Autel"), ("Skydio", "Skydio"), ("Other", "Other")], default="DJI", max_length=50)),
                ("model_name", models.CharField(max_length=100)),
                ("full_display_name", models.CharField(max_length=150, unique=True)),
                ("year_released", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("is_enterprise", models.BooleanField(default=False)),
                ("safety_features", models.TextField()),
                ("aka_names", models.CharField(blank=True, max_length=255)),
                ("active", models.BooleanField(default=True)),
            ],
            options={"verbose_name": "Drone Safety Profile", "verbose_name_plural": "Drone Safety Profiles", "ordering": ["brand", "model_name"]},
        ),
        migrations.AddConstraint(model_name="dronesafetyprofile", constraint=models.UniqueConstraint(fields=("brand", "model_name"), name="uniq_dronesafetyprofile_brand_model")),
        migrations.AddField(
            model_name="drone", name="safety_profile",
            field=models.ForeignKey(blank=True, help_text="Catalog profile used to populate this drone's safety features.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="drones", to="drones.dronesafetyprofile"),
        ),
    ]
