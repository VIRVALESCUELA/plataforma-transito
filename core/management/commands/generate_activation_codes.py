import csv
import secrets
from pathlib import Path

from django.core.management.base import BaseCommand

from core.models import ActivationCode


class Command(BaseCommand):
    help = "Genera codigos de activacion por lote para distribuir a alumnos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Cantidad de codigos a generar.",
        )
        parser.add_argument(
            "--course",
            default="Clase B",
            help="Nombre del curso asociado.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Cantidad de dias de acceso por codigo.",
        )
        parser.add_argument(
            "--prefix",
            default="CLASEB",
            help="Prefijo visible del codigo.",
        )
        parser.add_argument(
            "--output",
            default="exports/activation_codes_clase_b.csv",
            help="Ruta del CSV donde se guardaran los codigos generados.",
        )

    def _build_unique_code(self, prefix):
        while True:
            token = secrets.token_hex(3).upper()
            code = f"{prefix}-{token}"
            if not ActivationCode.objects.filter(code=code).exists():
                return code

    def handle(self, *args, **options):
        count = options["count"]
        if count <= 0:
            self.stderr.write("La cantidad debe ser mayor a cero.")
            return

        course_name = options["course"]
        duration_days = options["days"]
        prefix = options["prefix"].strip().upper().replace(" ", "")
        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        created_codes = []
        for _ in range(count):
            code = self._build_unique_code(prefix)
            activation = ActivationCode.objects.create(
                code=code,
                course_name=course_name,
                duration_days=duration_days,
                is_enabled=True,
            )
            created_codes.append(activation)

        with output_path.open("w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(
                csvfile,
                fieldnames=[
                    "code",
                    "course_name",
                    "duration_days",
                    "is_enabled",
                    "used_by",
                    "used_at",
                ],
            )
            writer.writeheader()
            for activation in created_codes:
                writer.writerow(
                    {
                        "code": activation.code,
                        "course_name": activation.course_name,
                        "duration_days": activation.duration_days,
                        "is_enabled": "si" if activation.is_enabled else "no",
                        "used_by": "",
                        "used_at": "",
                    }
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Se generaron {len(created_codes)} codigos para {course_name} en {output_path}"
            )
        )
