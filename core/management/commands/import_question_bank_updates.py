import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Option, Question, Topic


def parse_yes_no(value):
    normalized = (value or "").strip().lower()
    if normalized in {"si", "sí", "true", "1", "yes", "y"}:
        return True
    if normalized in {"no", "false", "0", "n"}:
        return False
    raise ValueError(f"Valor booleano no reconocido: {value!r}")


class Command(BaseCommand):
    help = "Importa actualizaciones del banco de preguntas desde un CSV exportado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            required=True,
            help="Ruta del archivo CSV editado.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        input_path = Path(options["input"])
        if not input_path.exists():
            raise CommandError(f"No existe el archivo: {input_path}")

        with input_path.open(newline="", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            rows = list(reader)

        updated_questions = 0
        created_questions = 0
        updated_options = 0
        created_options = 0

        for row in rows:
            question_id = (row.get("question_id") or "").strip()
            creating_question = not question_id

            if creating_question:
                question_text = (row.get("question_text") or "").strip()
                if not question_text:
                    raise CommandError(
                        "Las filas nuevas deben incluir question_text."
                    )
                question = Question()
            else:
                try:
                    question = Question.objects.select_related("topic").prefetch_related("options").get(
                        pk=int(question_id)
                    )
                except Question.DoesNotExist as exc:
                    raise CommandError(f"No existe la pregunta con id {question_id}.") from exc

            topic_name = (row.get("topic") or "").strip()
            if topic_name:
                topic, _ = Topic.objects.get_or_create(name=topic_name)
                question.topic = topic
            else:
                question.topic = None

            question.text = row.get("question_text", question.text)
            question.reference_law = row.get("reference_law", question.reference_law)
            question.reference_book = row.get("reference_book", question.reference_book)
            question.explanation = row.get("feedback", question.explanation)

            difficulty = (row.get("difficulty") or "").strip()
            if difficulty:
                question.difficulty = int(difficulty)

            is_active = row.get("is_active")
            if is_active not in {None, ""}:
                question.is_active = parse_yes_no(is_active)

            question.save()
            if creating_question:
                created_questions += 1
            else:
                updated_questions += 1

            options = list(question.options.all().order_by("id"))
            option_index = 1
            while True:
                option_text_key = f"option_{option_index}_text"
                option_correct_key = f"option_{option_index}_is_correct"
                if option_text_key not in row and option_correct_key not in row:
                    break

                option_text = row.get(option_text_key)
                option_correct = row.get(option_correct_key)
                has_text = option_text not in {None, ""}
                has_correct = option_correct not in {None, ""}

                if option_index <= len(options):
                    option = options[option_index - 1]
                    changed = False
                    if has_text:
                        option.text = option_text
                        changed = True
                    if has_correct:
                        option.is_correct = parse_yes_no(option_correct)
                        changed = True
                    if changed:
                        option.save()
                        updated_options += 1
                elif has_text:
                    if not has_correct:
                        raise CommandError(
                            f"La fila de la pregunta {question.pk} debe indicar si la nueva opcion {option_index} es correcta."
                        )
                    Option.objects.create(
                        question=question,
                        text=option_text,
                        is_correct=parse_yes_no(option_correct),
                    )
                    created_options += 1

                option_index += 1

            options_after = question.options.count()
            if options_after < 2:
                raise CommandError(
                    f"La pregunta {question.pk} debe tener al menos dos opciones."
                )

            correct_count = question.options.filter(is_correct=True).count()
            if correct_count == 0:
                raise CommandError(
                    f"La pregunta {question.pk} debe tener al menos una opcion correcta."
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Importacion completada: "
                f"{updated_questions} preguntas actualizadas, "
                f"{created_questions} preguntas creadas, "
                f"{updated_options} opciones actualizadas y "
                f"{created_options} opciones creadas desde {input_path}"
            )
        )
