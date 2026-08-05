from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("pilot", "0002_alter_pilotprofile_options")]
    operations = [
        migrations.AddField(model_name="pilotprofile", name="business_name", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="pilotprofile", name="city", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="pilotprofile", name="state", field=models.CharField(blank=True, max_length=2)),
        migrations.AddField(model_name="pilotprofile", name="street_address", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="pilotprofile", name="zip_code", field=models.CharField(blank=True, max_length=10)),
    ]
