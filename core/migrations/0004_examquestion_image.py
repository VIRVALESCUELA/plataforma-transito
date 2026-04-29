from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_studentanswer_selected_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="examquestion",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="questions/"),
        ),
    ]

