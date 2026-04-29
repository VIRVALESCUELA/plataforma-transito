import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from core.models import Question


class Command(BaseCommand):
    help = "Exporta el banco completo de preguntas a un CSV para planillas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="exports/question_bank_export.csv",
            help="Ruta del archivo CSV de salida.",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        questions = list(
            Question.objects.select_related("topic")
            .prefetch_related("options")
            .order_by("id")
        )
        max_options = max((question.options.count() for question in questions), default=0)

        headers = [
            "question_id",
            "topic",
            "difficulty",
            "is_active",
            "question_text",
            "reference_law",
            "reference_book",
            "feedback",
            "image",
            "total_options",
            "correct_option_indexes",
        ]
        for index in range(1, max_options + 1):
            headers.extend(
                [
                    f"option_{index}_text",
                    f"option_{index}_is_correct",
                ]
            )

        with output_path.open("w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()

            for question in questions:
                options_list = list(question.options.all().order_by("id"))
                correct_indexes = [
                    str(index)
                    for index, option in enumerate(options_list, start=1)
                    if option.is_correct
                ]
                row = {
                    "question_id": question.id,
                    "topic": question.topic.name if question.topic else "",
                    "difficulty": question.difficulty,
                    "is_active": "si" if question.is_active else "no",
                    "question_text": question.text,
                    "reference_law": question.reference_law,
                    "reference_book": question.reference_book,
                    "feedback": question.explanation,
                    "image": question.image.name if question.image else "",
                    "total_options": len(options_list),
                    "correct_option_indexes": ", ".join(correct_indexes),
                }

                for index, option in enumerate(options_list, start=1):
                    row[f"option_{index}_text"] = option.text
                    row[f"option_{index}_is_correct"] = "si" if option.is_correct else "no"

                writer.writerow(row)

        self.stdout.write(
            self.style.SUCCESS(
                f"Se exportaron {len(questions)} preguntas a {output_path}"
            )
        )
