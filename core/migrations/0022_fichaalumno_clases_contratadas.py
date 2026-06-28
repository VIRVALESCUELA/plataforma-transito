from django.db import migrations, models


PRACTICAL_LESSON_QUOTAS = {
    "Curso base mecanico": 12,
    "Curso intensivo": 8,
    "Curso rush": 10,
    "Curso domicilio": 8,
    "Help me!": 1,
    "Full automatico": 1,
    "Clase extra": 1,
}


def backfill_clases_contratadas(apps, schema_editor):
    FichaAlumno = apps.get_model("core", "FichaAlumno")
    for ficha in FichaAlumno.objects.all().only("id", "curso", "clases_contratadas").iterator():
        quota = PRACTICAL_LESSON_QUOTAS.get(ficha.curso or "", 0)
        if quota:
            ficha.clases_contratadas = quota
            ficha.save(update_fields=["clases_contratadas"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_fichaalumno_direccion_inscripcion_direccion"),
    ]

    operations = [
        migrations.AddField(
            model_name="fichaalumno",
            name="clases_contratadas",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Cantidad de clases practicas incluidas en el curso vendido.",
            ),
        ),
        migrations.RunPython(backfill_clases_contratadas, migrations.RunPython.noop),
    ]
