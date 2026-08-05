import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_invitation")]
    operations = [
        migrations.CreateModel(
            name="EmailDeliveryLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recipient", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=255)),
                ("status", models.CharField(choices=[("sent", "Sent"), ("failed", "Failed")], db_index=True, max_length=20)),
                ("error_message", models.TextField(blank=True)),
                ("attempted_at", models.DateTimeField(auto_now_add=True)),
                ("invitation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="delivery_logs", to="accounts.invitation")),
            ],
            options={"ordering": ["-attempted_at"]},
        )
    ]
