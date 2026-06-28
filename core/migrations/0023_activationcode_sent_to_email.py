from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_fichaalumno_clases_contratadas"),
    ]

    operations = [
        migrations.AddField(
            model_name="activationcode",
            name="sent_to_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
