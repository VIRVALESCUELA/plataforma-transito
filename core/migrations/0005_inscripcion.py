from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_examquestion_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="Inscripcion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=150)),
                ("comuna", models.CharField(max_length=120)),
                ("correo", models.EmailField(max_length=254)),
                ("telefono", models.CharField(max_length=30)),
                ("curso", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
