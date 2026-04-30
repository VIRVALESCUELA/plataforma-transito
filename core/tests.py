import csv
import tempfile
from datetime import timedelta

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    ActivationCode,
    ExamAttempt,
    ExamAttemptStatus,
    ExamQuestion,
    ExamTemplate,
    Inscripcion,
    Option,
    Profile,
    Question,
    Topic,
)
from .models import UserRole


class AuthFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="student", password="strong-pass-123"
        )

    def test_landing_is_public(self):
        response = self.client.get(reverse("core_web:landing"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("core_web:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.headers["Location"])

    def test_logout_clears_session_and_redirects(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("core_web:landing"))

        follow_response = self.client.get(reverse("core_web:dashboard"))
        self.assertEqual(follow_response.status_code, 302)
        self.assertIn(reverse("login"), follow_response.headers["Location"])
        self.assertNotIn("_auth_user_id", self.client.session)


class InscripcionTests(TestCase):
    def test_inscripcion_creates_record_and_redirects_to_whatsapp(self):
        payload = {
            "nombre": "Test Alumno",
            "comuna": "Santiago",
            "correo": "test@example.com",
            "telefono": "+56 9 1234 5678",
            "curso": "Curso base mecanico",
        }
        response = self.client.post(reverse("core_web:inscripcion"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("wa.me", response.content.decode())
        self.assertTrue(
            Inscripcion.objects.filter(nombre="Test Alumno", correo="test@example.com").exists()
        )

    def test_inscripcion_prefills_course_from_querystring(self):
        response = self.client.get(
            reverse("core_web:inscripcion") + "?curso=Curso%20intensivo"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'option value="Curso intensivo" selected')


class ExamApiSecurityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.student = user_model.objects.create_user(
            username="student-api", password="strong-pass-123"
        )
        self.admin = user_model.objects.create_superuser(
            username="admin-api",
            email="admin@example.com",
            password="strong-pass-123",
        )
        self.template = ExamTemplate.objects.create(
            name="Plantilla demo",
            total_questions=1,
            duration_minutes=45,
        )
        self.code = ActivationCode.objects.create(code="ACTIVA30", course_name="Clase B")
        profile = self.student.profile
        profile.access_activated_at = timezone.now()
        profile.access_expires_at = timezone.now() + timedelta(days=30)
        profile.activated_course_name = "Clase B"
        profile.save()
        self.question = Question.objects.create(text="Pregunta segura")
        Option.objects.create(question=self.question, text="A", is_correct=True)
        Option.objects.create(question=self.question, text="B", is_correct=False)

    def test_non_admin_cannot_create_questions(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("questions-list"),
            {
                "text": "Nueva pregunta",
                "difficulty": 1,
                "options": [
                    {"text": "A", "is_correct": True},
                    {"text": "B", "is_correct": False},
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_questions(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("questions-list"),
            {
                "text": "Nueva pregunta",
                "difficulty": 1,
                "options": [
                    {"text": "A", "is_correct": True},
                    {"text": "B", "is_correct": False},
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_finish_rejects_attempt_with_unanswered_questions(self):
        self.client.force_login(self.student)
        start_response = self.client.post(
            reverse("exams-start"),
            {"template_id": self.template.id},
            content_type="application/json",
        )
        self.assertEqual(start_response.status_code, 201)
        attempt_id = start_response.json()["id"]

        finish_response = self.client.post(
            reverse("exams-finish", args=[attempt_id]),
            content_type="application/json",
        )
        self.assertEqual(finish_response.status_code, 400)
        self.assertIn("sin responder", finish_response.json()["detail"])

    def test_cannot_start_duplicate_attempt_for_same_template(self):
        self.client.force_login(self.student)
        first_response = self.client.post(
            reverse("exams-start"),
            {"template_id": self.template.id},
            content_type="application/json",
        )
        self.assertEqual(first_response.status_code, 201)

        second_response = self.client.post(
            reverse("exams-start"),
            {"template_id": self.template.id},
            content_type="application/json",
        )
        self.assertEqual(second_response.status_code, 400)
        self.assertIn("Ya tienes un examen en curso", second_response.json()["detail"])


class ExamStudentFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.student = user_model.objects.create_user(
            username="student-web", password="strong-pass-123"
        )
        self.template = ExamTemplate.objects.create(
            name="Plantilla web",
            total_questions=1,
            duration_minutes=5,
        )
        profile = self.student.profile
        profile.access_activated_at = timezone.now()
        profile.access_expires_at = timezone.now() + timedelta(days=30)
        profile.activated_course_name = "Clase B"
        profile.save()
        self.question = Question.objects.create(text="Pregunta visible")
        Option.objects.create(question=self.question, text="Correcta", is_correct=True)
        Option.objects.create(question=self.question, text="Incorrecta", is_correct=False)

    def test_dashboard_marks_expired_attempts(self):
        expired_attempt = ExamAttempt.objects.create(
            student=self.student,
            template=self.template,
            started_at=timezone.now() - timedelta(minutes=10),
        )
        ExamQuestion.objects.create(
            attempt=expired_attempt,
            question_text=self.question.text,
            explanation="",
            topic="",
            difficulty=1,
            reference_law="",
            reference_book="",
            options=[
                {"text": "Correcta", "is_correct": True},
                {"text": "Incorrecta", "is_correct": False},
            ],
        )

        self.client.force_login(self.student)
        response = self.client.get(reverse("core_web:dashboard"))

        self.assertEqual(response.status_code, 200)
        expired_attempt.refresh_from_db()
        self.assertEqual(expired_attempt.status, ExamAttemptStatus.EXPIRADO)

    def test_dashboard_highlights_active_attempt_and_reanudar_action(self):
        active_attempt = ExamAttempt.objects.create(
            student=self.student,
            template=self.template,
            started_at=timezone.now() - timedelta(minutes=1),
        )
        ExamQuestion.objects.create(
            attempt=active_attempt,
            question_text=self.question.text,
            explanation="",
            topic="",
            difficulty=1,
            reference_law="",
            reference_book="",
            options=[
                {"text": "Correcta", "is_correct": True},
                {"text": "Incorrecta", "is_correct": False},
            ],
        )

        self.client.force_login(self.student)
        response = self.client.get(reverse("core_web:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Examen en curso")
        self.assertContains(response, "Reanudar examen")
        self.assertContains(response, "Reanudar intento")

    def test_attempt_detail_shows_remaining_time(self):
        active_attempt = ExamAttempt.objects.create(
            student=self.student,
            template=self.template,
            started_at=timezone.now() - timedelta(minutes=1),
        )
        ExamQuestion.objects.create(
            attempt=active_attempt,
            question_text=self.question.text,
            explanation="",
            topic="",
            difficulty=1,
            reference_law="",
            reference_book="",
            options=[
                {"text": "Correcta", "is_correct": True},
                {"text": "Incorrecta", "is_correct": False},
            ],
        )

        self.client.force_login(self.student)
        response = self.client.get(
            reverse("core_web:attempt-detail", args=[active_attempt.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tiempo restante:")

    def test_attempt_detail_shows_progress_summary_and_finish_confirmation(self):
        active_attempt = ExamAttempt.objects.create(
            student=self.student,
            template=self.template,
            started_at=timezone.now() - timedelta(minutes=1),
        )
        ExamQuestion.objects.create(
            attempt=active_attempt,
            question_text=self.question.text,
            explanation="",
            topic="",
            difficulty=1,
            reference_law="",
            reference_book="",
            options=[
                {"text": "Correcta", "is_correct": True},
                {"text": "Incorrecta", "is_correct": False},
            ],
        )

        self.client.force_login(self.student)
        response = self.client.get(
            reverse("core_web:attempt-detail", args=[active_attempt.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Avance")
        self.assertContains(response, "Pendientes")
        self.assertContains(response, "Guardar progreso")
        self.assertContains(response, "¿Deseas continuar?")
        self.assertContains(response, "exam-mobile-actions")


class ActivationFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="student-activation",
            password="strong-pass-123",
        )
        self.template = ExamTemplate.objects.create(
            name="Plantilla activacion",
            total_questions=1,
            duration_minutes=10,
        )
        self.code = ActivationCode.objects.create(
            code="CURSO30",
            course_name="Curso teorico clase B",
            duration_days=30,
        )
        self.question = Question.objects.create(text="Pregunta activable")
        Option.objects.create(question=self.question, text="Correcta", is_correct=True)
        Option.objects.create(question=self.question, text="Incorrecta", is_correct=False)

    def test_dashboard_shows_activation_form_without_access(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core_web:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activar curso")
        self.assertContains(response, "Codigo de activacion")
        self.assertNotContains(response, "Plantillas disponibles")

    def test_activation_page_is_available_for_logged_in_student(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core_web:activate-course"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activar curso teorico")
        self.assertContains(response, "Activar curso")

    def test_dashboard_can_activate_access_code(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("core_web:activate-course"),
            {"activation_code": "CURSO30"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.code.refresh_from_db()
        self.assertTrue(self.user.profile.has_active_exam_access())
        self.assertEqual(self.code.used_by, self.user)
        self.assertContains(response, "30 dias de acceso")
        self.assertContains(response, "Plantillas disponibles")

    def test_api_start_requires_active_access_code(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("exams-start"),
            {"template_id": self.template.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("acceso a examenes no esta activo", response.json()["detail"])

    def test_signup_page_does_not_show_activation_field(self):
        response = self.client.get(reverse("student_signup"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Codigo de activacion")

    def test_signup_accepts_six_character_password(self):
        response = self.client.post(
            reverse("student_signup"),
            {
                "username": "clave-corta",
                "first_name": "Clave",
                "last_name": "Corta",
                "email": "clave@example.com",
                "password1": "abc123",
                "password2": "abc123",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            get_user_model().objects.filter(username="clave-corta").exists()
        )
        user = get_user_model().objects.get(username="clave-corta")
        self.assertFalse(user.profile.has_active_exam_access())


class ExportQuestionBankCommandTests(TestCase):
    def test_exports_question_bank_to_csv(self):
        topic = Topic.objects.create(name="Normativa")
        question = Question.objects.create(
            text="¿Que indica esta senal?",
            topic=topic,
            difficulty=2,
            reference_law="Art. 12",
            reference_book="Capitulo 3",
            explanation="Debes reducir la velocidad y ceder el paso cuando corresponda.",
            is_active=True,
        )
        Option.objects.create(question=question, text="Ceda el paso", is_correct=True)
        Option.objects.create(question=question, text="Via libre", is_correct=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = f"{tmpdir}/preguntas.csv"
            call_command("export_question_bank", output=output_path)

            with open(output_path, newline="", encoding="utf-8-sig") as csvfile:
                rows = list(csv.DictReader(csvfile))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question_text"], "¿Que indica esta senal?")
        self.assertEqual(rows[0]["feedback"], question.explanation)
        self.assertEqual(rows[0]["option_1_text"], "Ceda el paso")
        self.assertEqual(rows[0]["option_1_is_correct"], "si")
        self.assertEqual(rows[0]["option_2_text"], "Via libre")
        self.assertEqual(rows[0]["correct_option_indexes"], "1")

    def test_imports_question_bank_updates_from_csv(self):
        topic = Topic.objects.create(name="Normativa")
        question = Question.objects.create(
            text="Que indica esta senal",
            topic=topic,
            difficulty=1,
            explanation="Texto sin corregir",
            is_active=True,
        )
        Option.objects.create(question=question, text="ceda el paso", is_correct=True)
        Option.objects.create(question=question, text="via libre", is_correct=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = f"{tmpdir}/preguntas_editadas.csv"
            with open(input_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=[
                        "question_id",
                        "topic",
                        "difficulty",
                        "is_active",
                        "question_text",
                        "reference_law",
                        "reference_book",
                        "feedback",
                        "option_1_text",
                        "option_1_is_correct",
                        "option_2_text",
                        "option_2_is_correct",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "question_id": question.id,
                        "topic": "Señales",
                        "difficulty": 2,
                        "is_active": "si",
                        "question_text": "¿Qué indica esta señal?",
                        "reference_law": "Art. 99",
                        "reference_book": "Capítulo 2",
                        "feedback": "Debes ceder el paso cuando corresponda.",
                        "option_1_text": "Ceda el paso",
                        "option_1_is_correct": "si",
                        "option_2_text": "Vía libre",
                        "option_2_is_correct": "no",
                    }
                )

            call_command("import_question_bank_updates", input=input_path)

        question.refresh_from_db()
        options = list(question.options.order_by("id"))

        self.assertEqual(question.topic.name, "Señales")
        self.assertEqual(question.text, "¿Qué indica esta señal?")
        self.assertEqual(question.difficulty, 2)
        self.assertEqual(question.reference_law, "Art. 99")
        self.assertEqual(question.reference_book, "Capítulo 2")
        self.assertEqual(question.explanation, "Debes ceder el paso cuando corresponda.")
        self.assertEqual(options[0].text, "Ceda el paso")
        self.assertTrue(options[0].is_correct)
        self.assertEqual(options[1].text, "Vía libre")
        self.assertFalse(options[1].is_correct)

    def test_import_creates_new_question_when_question_id_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = f"{tmpdir}/preguntas_nuevas.csv"
            with open(input_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=[
                        "question_id",
                        "topic",
                        "difficulty",
                        "is_active",
                        "question_text",
                        "reference_law",
                        "reference_book",
                        "feedback",
                        "option_1_text",
                        "option_1_is_correct",
                        "option_2_text",
                        "option_2_is_correct",
                        "option_3_text",
                        "option_3_is_correct",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "question_id": "",
                        "topic": "Mecánica",
                        "difficulty": 3,
                        "is_active": "si",
                        "question_text": "¿Cuál es la función del embrague?",
                        "reference_law": "",
                        "reference_book": "Capítulo 7",
                        "feedback": "Permite desacoplar temporalmente el motor de la transmisión.",
                        "option_1_text": "Conectar luces",
                        "option_1_is_correct": "no",
                        "option_2_text": "Desacoplar motor y transmisión",
                        "option_2_is_correct": "si",
                        "option_3_text": "Frenar el vehículo",
                        "option_3_is_correct": "no",
                    }
                )

            call_command("import_question_bank_updates", input=input_path)

        question = Question.objects.get(text="¿Cuál es la función del embrague?")
        options = list(question.options.order_by("id"))

        self.assertEqual(question.topic.name, "Mecánica")
        self.assertEqual(question.difficulty, 3)
        self.assertEqual(question.reference_book, "Capítulo 7")
        self.assertEqual(
            question.explanation,
            "Permite desacoplar temporalmente el motor de la transmisión.",
        )
        self.assertEqual(len(options), 3)
        self.assertEqual(options[1].text, "Desacoplar motor y transmisión")
        self.assertTrue(options[1].is_correct)

    def test_import_creates_question_when_csv_id_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = f"{tmpdir}/preguntas_restauradas.csv"
            with open(input_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=[
                        "question_id",
                        "topic",
                        "difficulty",
                        "is_active",
                        "question_text",
                        "reference_law",
                        "reference_book",
                        "feedback",
                        "image",
                        "option_1_text",
                        "option_1_is_correct",
                        "option_2_text",
                        "option_2_is_correct",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "question_id": "999",
                        "topic": "Señales",
                        "difficulty": 1,
                        "is_active": "si",
                        "question_text": "¿Qué significa esta señal preventiva?",
                        "reference_law": "",
                        "reference_book": "Capítulo 4",
                        "feedback": "Advierte una condición de riesgo en la vía.",
                        "image": "questions/p-123.png",
                        "option_1_text": "Peligro",
                        "option_1_is_correct": "si",
                        "option_2_text": "Estacionamiento permitido",
                        "option_2_is_correct": "no",
                    }
                )

            call_command("import_question_bank_updates", input=input_path)

        question = Question.objects.get(text="¿Qué significa esta señal preventiva?")
        self.assertNotEqual(question.pk, 999)
        self.assertEqual(question.image.name, "questions/p-123.png")
        self.assertEqual(question.options.count(), 2)

    def test_bootstrap_exam_data_imports_questions_and_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = f"{tmpdir}/bootstrap.csv"
            with open(input_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=[
                        "question_id",
                        "topic",
                        "difficulty",
                        "is_active",
                        "question_text",
                        "reference_law",
                        "reference_book",
                        "feedback",
                        "option_1_text",
                        "option_1_is_correct",
                        "option_2_text",
                        "option_2_is_correct",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "question_id": "",
                        "topic": "Normativa",
                        "difficulty": 1,
                        "is_active": "si",
                        "question_text": "Pregunta para bootstrap",
                        "reference_law": "",
                        "reference_book": "",
                        "feedback": "Retroalimentacion",
                        "option_1_text": "Correcta",
                        "option_1_is_correct": "si",
                        "option_2_text": "Incorrecta",
                        "option_2_is_correct": "no",
                    }
                )

            call_command("bootstrap_exam_data", input=input_path)

        template = ExamTemplate.objects.get(name="Examen clase B")
        self.assertEqual(template.total_questions, 35)
        self.assertEqual(template.duration_minutes, 45)
        self.assertTrue(template.show_feedback)
        self.assertTrue(Question.objects.filter(text="Pregunta para bootstrap").exists())


class ActivationCodeGeneratorCommandTests(TestCase):
    def test_generates_activation_codes_and_exports_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = f"{tmpdir}/codes.csv"
            call_command(
                "generate_activation_codes",
                count=3,
                course="Clase B",
                days=30,
                prefix="CLASEB",
                output=output_path,
            )

            with open(output_path, newline="", encoding="utf-8-sig") as csvfile:
                rows = list(csv.DictReader(csvfile))

        self.assertEqual(ActivationCode.objects.count(), 3)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["course_name"] == "Clase B" for row in rows))
        self.assertTrue(all(row["duration_days"] == "30" for row in rows))
        self.assertTrue(all(row["code"].startswith("CLASEB-") for row in rows))


class InscripcionManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="staff-user",
            password="strong-pass-123",
            is_staff=True,
        )
        self.inscripcion = Inscripcion.objects.create(
            nombre="Alumno Sucursal",
            comuna="Santiago",
            correo="sucursal@example.com",
            telefono="+56 9 1111 2222",
            curso="Curso intensivo",
        )
        self.student = user_model.objects.create_user(
            username="alumno-uno",
            password="strong-pass-123",
            first_name="Alumno",
        )
        self.student.profile.role = UserRole.ALUMNO
        self.student.profile.access_expires_at = timezone.now() + timedelta(days=10)
        self.student.profile.activated_course_name = "Clase B"
        self.student.profile.save()
        ActivationCode.objects.create(
            code="CLASEB-LIBRE1",
            course_name="Clase B",
            duration_days=30,
            is_enabled=True,
        )

    def test_staff_can_view_inscripciones_management(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core_web:manage-inscripciones"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inscripciones y codigos Clase B")
        self.assertContains(response, "Alumno Sucursal")
        self.assertContains(response, "Solicitudes de inscripcion")
        self.assertContains(response, "Registros en plataforma")
        self.assertContains(response, "Accesos activos")
        self.assertContains(response, "Codigos disponibles")

    def test_staff_can_generate_activation_code_from_inscripcion(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("core_web:manage-inscripciones"),
            {"action": "generate_code", "inscripcion_id": self.inscripcion.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.inscripcion.refresh_from_db()
        self.assertIsNotNone(self.inscripcion.activation_code)
        self.assertTrue(self.inscripcion.activation_code.code.startswith("CLASEB-"))
        self.assertEqual(self.inscripcion.activation_code.course_name, "Clase B")

    def test_staff_dashboard_shows_link_to_management_view(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core_web:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Abrir inscripciones pendientes")


class AdminLabelsTests(TestCase):
    def test_profile_and_inscripcion_have_clear_admin_labels(self):
        self.assertEqual(Profile._meta.verbose_name_plural, "Registros de plataforma")
        self.assertEqual(Inscripcion._meta.verbose_name_plural, "Solicitudes de inscripcion")
