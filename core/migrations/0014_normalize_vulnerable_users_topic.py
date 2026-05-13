from django.db import migrations


OLD_TOPIC_NAMES = [
    "La y Los usuarios vulnerables",
    "La y los usuarios vulnerables",
    "la y los usuarios vulnerables",
]
NEW_TOPIC_NAME = "Las y Los usuarios vulnerables"


def normalize_vulnerable_users_topic(apps, schema_editor):
    Topic = apps.get_model("core", "Topic")
    Question = apps.get_model("core", "Question")

    new_topic = Topic.objects.filter(name__iexact=NEW_TOPIC_NAME).first()
    old_topics = Topic.objects.filter(name__in=OLD_TOPIC_NAMES)

    if new_topic is None:
        topic = old_topics.first()
        if topic is None:
            return

        topic.name = NEW_TOPIC_NAME
        topic.save(update_fields=["name"])
        new_topic = topic
        old_topics = Topic.objects.filter(name__in=OLD_TOPIC_NAMES).exclude(pk=new_topic.pk)

    for old_topic in old_topics:
        Question.objects.filter(topic=old_topic).update(topic=new_topic)
        old_topic.delete()


def reverse_normalize_vulnerable_users_topic(apps, schema_editor):
    Topic = apps.get_model("core", "Topic")
    topic = Topic.objects.filter(name=NEW_TOPIC_NAME).first()
    if topic is None or Topic.objects.filter(name="La y Los usuarios vulnerables").exists():
        return

    topic.name = "La y Los usuarios vulnerables"
    topic.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_rename_vulnerable_users_topic"),
    ]

    operations = [
        migrations.RunPython(
            normalize_vulnerable_users_topic,
            reverse_normalize_vulnerable_users_topic,
        ),
    ]
