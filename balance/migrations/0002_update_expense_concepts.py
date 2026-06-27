from django.db import migrations


def update_expense_concepts(apps, schema_editor):
    ConceptoGasto = apps.get_model("balance", "ConceptoGasto")
    renames = {
        "Sueldos": "Sueldo",
        "Bencinas": "Bencina",
        "Mantenciones": "Repuestos",
    }
    for old_name, new_name in renames.items():
        concept = ConceptoGasto.objects.filter(nombre=old_name).first()
        if concept and not ConceptoGasto.objects.filter(nombre=new_name).exclude(pk=concept.pk).exists():
            concept.nombre = new_name
            concept.save(update_fields=["nombre"])

    conceptos = [
        ("Arriendo", "MANUAL", 10),
        ("Sueldo", "MANUAL", 20),
        ("Cotizaciones", "MANUAL", 30),
        ("Impuestos", "MANUAL", 40),
        ("Contador", "MANUAL", 50),
        ("Internet", "MANUAL", 60),
        ("Luz", "MANUAL", 70),
        ("Agua", "MANUAL", 80),
        ("Polizas", "MANUAL", 90),
        ("Bencina", "AUTOMATICO", 100),
        ("Repuestos", "AUTOMATICO", 110),
        ("Varios", "MANUAL", 120),
    ]
    for nombre, origen, orden in conceptos:
        ConceptoGasto.objects.update_or_create(
            nombre=nombre,
            defaults={"origen": origen, "orden": orden, "activo": True},
        )

    manuales_permitidos = {
        "Arriendo",
        "Sueldo",
        "Cotizaciones",
        "Impuestos",
        "Contador",
        "Internet",
        "Luz",
        "Agua",
        "Polizas",
        "Varios",
    }
    ConceptoGasto.objects.filter(origen="MANUAL").exclude(
        nombre__in=manuales_permitidos,
    ).exclude(nombre__istartswith="Varios").update(activo=False)


class Migration(migrations.Migration):

    dependencies = [
        ("balance", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(update_expense_concepts, migrations.RunPython.noop),
    ]
