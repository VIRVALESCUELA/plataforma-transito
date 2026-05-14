from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0016_pagevisitcounter"),
    ]

    operations = [
        migrations.AddField(
            model_name="inscripcion",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="inscripcion",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="inscripcion",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDIENTE", "Pendiente"),
                    ("CONTACTADO", "Contactado"),
                    ("CLIENTE", "Cliente sin plataforma"),
                    ("MATRICULADO", "Matriculado"),
                    ("CUENTA_CREADA", "Cuenta creada"),
                    ("CURSO_ACTIVO", "Curso activo"),
                    ("DESCARTADO", "Descartado"),
                ],
                default="PENDIENTE",
                max_length=16,
            ),
        ),
    ]
