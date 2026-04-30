from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Carga el banco de preguntas y deja lista la plantilla base de examen."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="exports/question_bank_export.csv",
            help="Ruta del CSV del banco de preguntas.",
        )
        parser.add_argument(
            "--preserve-ids",
            action="store_true",
            help="Conserva los question_id del CSV al restaurar una base vacia.",
        )

    def handle(self, *args, **options):
        call_command(
            "import_question_bank_updates",
            input=options["input"],
            preserve_ids=options["preserve_ids"],
            ensure_template=True,
        )
