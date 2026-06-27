from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


def seed_conceptos(apps, schema_editor):
    ConceptoGasto = apps.get_model("balance", "ConceptoGasto")
    conceptos = [
        ("Arriendo", "MANUAL"),
        ("Sueldos", "MANUAL"),
        ("Impuestos", "MANUAL"),
        ("Luz", "MANUAL"),
        ("Movistar", "MANUAL"),
        ("Polizas", "MANUAL"),
        ("Varios", "MANUAL"),
        ("Bencinas", "AUTOMATICO"),
        ("Mantenciones", "AUTOMATICO"),
    ]
    for index, (nombre, origen) in enumerate(conceptos, start=10):
        ConceptoGasto.objects.get_or_create(
            nombre=nombre,
            defaults={"origen": origen, "orden": index, "activo": True},
        )


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConceptoGasto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=80, unique=True)),
                ("origen", models.CharField(choices=[("MANUAL", "Manual"), ("AUTOMATICO", "Automatico")], default="MANUAL", max_length=12)),
                ("orden", models.PositiveSmallIntegerField(default=0)),
                ("activo", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Concepto de gasto",
                "verbose_name_plural": "Conceptos de gasto",
                "ordering": ["orden", "nombre"],
            },
        ),
        migrations.CreateModel(
            name="GastoMensual",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anio", models.PositiveSmallIntegerField(default=django.utils.timezone.localdate().year)),
                ("mes", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("monto", models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ("observacion", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("concepto", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="gastos_mensuales", to="balance.conceptogasto")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="balance_gastos_actualizados", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Gasto mensual",
                "verbose_name_plural": "Gastos mensuales",
                "ordering": ["-anio", "mes", "concepto__orden", "concepto__nombre"],
            },
        ),
        migrations.AddConstraint(
            model_name="gastomensual",
            constraint=models.UniqueConstraint(fields=("concepto", "anio", "mes"), name="unique_gasto_mensual_por_concepto"),
        ),
        migrations.AddConstraint(
            model_name="gastomensual",
            constraint=models.CheckConstraint(condition=models.Q(("mes__gte", 1), ("mes__lte", 12)), name="gasto_mensual_mes_valido"),
        ),
        migrations.RunPython(seed_conceptos, migrations.RunPython.noop),
    ]
