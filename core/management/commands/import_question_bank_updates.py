import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction

from core.models import ExamTemplate, Option, Question, Topic


def parse_yes_no(value):
    normalized = (value or "").strip().lower()
    if normalized in {"si", "sí", "true", "1", "yes", "y"}:
        return True
    if normalized in {"no", "false", "0", "n"}:
        return False
    raise ValueError(f"Valor booleano no reconocido: {value!r}")


class Command(BaseCommand):
    help = "Importa o actualiza el banco de preguntas desde un CSV exportado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="exports/question_bank_export.csv",
            help="Ruta del archivo CSV editado.",
        )
        parser.add_argument(
            "--preserve-ids",
            action="store_true",
            help=(
                "Crea preguntas nuevas usando el question_id del CSV cuando este "
                "disponible. Util para restaurar una base vacia desde el export."
            ),
        )
        parser.add_argument(
            "--ensure-template",
            action="store_true",
            help="Crea o actualiza la plantilla base Examen clase B.",
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

        for row_number, row in enumerate(rows, start=2):
            question_id = (row.get("question_id") or "").strip()
            question_text = (row.get("question_text") or "").strip()

            question = None
            if question_id:
                try:
                    question = (
                        Question.objects.select_related("topic")
                        .prefetch_related("options")
                        .get(pk=int(question_id))
                    )
                except (TypeError, ValueError) as exc:
                    raise CommandError(
                        f"Fila {row_number}: question_id invalido: {question_id!r}."
                    ) from exc
                except Question.DoesNotExist:
                    question = None

            creating_question = question is None
            if creating_question:
                if not question_text:
                    raise CommandError(
                        f"Fila {row_number}: las preguntas nuevas deben incluir question_text."
                    )
                if question_id and options["preserve_ids"]:
                    question = Question(pk=int(question_id))
                else:
                    question = Question()

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

            image_name = (row.get("image") or "").strip()
            if image_name:
                question.image = image_name

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

            existing_options = list(question.options.all().order_by("id"))
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

                if option_index <= len(existing_options):
                    option = existing_options[option_index - 1]
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

        if options["ensure_template"]:
            ExamTemplate.objects.update_or_create(
                name="Examen clase B",
                defaults={
                    "duration_minutes": 45,
                    "total_questions": 35,
                    "rules_json": {},
                    "show_feedback": True,
                },
            )

        if options["preserve_ids"]:
            sequence_sql = connection.ops.sequence_reset_sql(no_style(), [Question])
            if sequence_sql:
                with connection.cursor() as cursor:
                    for sql in sequence_sql:
                        cursor.execute(sql)

        self.stdout.write(
            self.style.SUCCESS(
                "Importacion completada: "
                f"{updated_questions} preguntas actualizadas, "
                f"{created_questions} preguntas creadas, "
                f"{updated_options} opciones actualizadas y "
                f"{created_options} opciones creadas desde {input_path}"
            )
        )
        if options["ensure_template"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Plantilla asegurada: Examen clase B, 35 preguntas, 45 minutos."
                )
            )
