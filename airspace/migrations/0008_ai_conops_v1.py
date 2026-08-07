from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("airspace", "0007_ai_conops_generation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="approvalapplication",
            name="description",
            field=models.TextField(
                blank=True,
                default="",
                help_text=(
                    "Concise Description of Operations intended for the FAA "
                    "application form."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="approvalapplication",
            name="locked_description",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Protect the reviewed Description of Operations from AI "
                    "regeneration."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="approvalapplication",
            name="ai_generation_model",
            field=models.CharField(
                blank=True,
                default="",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="approvalapplication",
            name="ai_generation_error",
            field=models.TextField(
                blank=True,
                default="",
            ),
        ),
        migrations.AddField(
            model_name="approvalapplication",
            name="ai_input_tokens",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="approvalapplication",
            name="ai_output_tokens",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="approvalapplication",
            name="ai_prompt_version",
            field=models.CharField(
                blank=True,
                default="",
                max_length=30,
            ),
        ),
    ]
