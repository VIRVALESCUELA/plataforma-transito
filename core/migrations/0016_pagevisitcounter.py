from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_force_vulnerable_users_topic_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="PageVisitCounter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("page", models.CharField(max_length=120, unique=True)),
                ("total", models.PositiveBigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Contador de visitas",
                "verbose_name_plural": "Contadores de visitas",
                "ordering": ["page"],
            },
        ),
    ]
