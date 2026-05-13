from django.db import migrations


OLD_TOPIC_NAME = "La y Los usuarios vulnerables"
NEW_TOPIC_NAME = "Las y Los usuarios vulnerables"


def rename_vulnerable_users_topic(apps, schema_editor):
    Topic = apps.get_model("core", "Topic")
    old_topic = Topic.objects.filter(name=OLD_TOPIC_NAME).first()
    if old_topic is None:
        return

    new_topic = Topic.objects.filter(name=NEW_TOPIC_NAME).first()
    if new_topic is not None:
        Question = apps.get_model("core", "Question")
        Question.objects.filter(topic=old_topic).update(topic=new_topic)
        old_topic.delete()
        return

    old_topic.name = NEW_TOPIC_NAME
    old_topic.save(update_fields=["name"])


def reverse_rename_vulnerable_users_topic(apps, schema_editor):
    Topic = apps.get_model("core", "Topic")
    topic = Topic.objects.filter(name=NEW_TOPIC_NAME).first()
    if topic is None or Topic.objects.filter(name=OLD_TOPIC_NAME).exists():
        return

    topic.name = OLD_TOPIC_NAME
    topic.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_backfill_examquestion_source_question"),
    ]

    operations = [
        migrations.RunPython(
            rename_vulnerable_users_topic,
            reverse_rename_vulnerable_users_topic,
        ),
    ]
