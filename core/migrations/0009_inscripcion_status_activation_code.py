from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_profile_access_fields_activationcode"),
    ]

    operations = [
        migrations.AddField(
            model_name="inscripcion",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDIENTE", "Pendiente"),
                    ("CONTACTADO", "Contactado"),
                    ("MATRICULADO", "Matriculado"),
                    ("DESCARTADO", "Descartado"),
                ],
                default="PENDIENTE",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="inscripcion",
            name="activation_code",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="core.activationcode",
            ),
        ),
    ]
