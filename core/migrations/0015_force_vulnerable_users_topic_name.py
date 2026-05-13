from django.db import migrations


WRONG_TOPIC_NORMALIZED = "la y los usuarios vulnerables"
NEW_TOPIC_NAME = "Las y Los usuarios vulnerables"


def normalize_name(value):
    return " ".join((value or "").split()).casefold()


def force_vulnerable_users_topic_name(apps, schema_editor):
    Topic = apps.get_model("core", "Topic")
    Question = apps.get_model("core", "Question")

    matching_topics = [
        topic
        for topic in Topic.objects.filter(name__icontains="usuarios vulnerables")
        if normalize_name(topic.name) == WRONG_TOPIC_NORMALIZED
    ]
    if not matching_topics:
        return

    correct_topic = Topic.objects.filter(name=NEW_TOPIC_NAME).first()
    primary_topic = matching_topics[0]

    if correct_topic is None:
        primary_topic.name = NEW_TOPIC_NAME
        primary_topic.save(update_fields=["name"])
        correct_topic = primary_topic

    for topic in matching_topics:
        if topic.pk == correct_topic.pk:
            continue
        Question.objects.filter(topic=topic).update(topic=correct_topic)
        topic.delete()


def reverse_force_vulnerable_users_topic_name(apps, schema_editor):
    Topic = apps.get_model("core", "Topic")
    topic = Topic.objects.filter(name=NEW_TOPIC_NAME).first()
    if topic is None or Topic.objects.filter(name="La y Los usuarios vulnerables").exists():
        return

    topic.name = "La y Los usuarios vulnerables"
    topic.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_normalize_vulnerable_users_topic"),
    ]

    operations = [
        migrations.RunPython(
            force_vulnerable_users_topic_name,
            reverse_force_vulnerable_users_topic_name,
        ),
    ]
