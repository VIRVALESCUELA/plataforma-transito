import csv
import tempfile
from datetime import date, timedelta
from io import BytesIO
from zipfile import ZipFile

from django.core.management import call_command
from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import FichaAlumnoForm, FichaMovimientoForm
from .models import (
    ActivationCode,
    ExamAttempt,
    ExamAttemptStatus,
    ExamQuestion,
    ExamTemplate,
    FichaAlumno,
    FichaMovimiento,
    Inscripcion,
    Option,
    PageVisitCounter,
    Profile,
    Question,
    StudentAnswer,
    Topic,
)
from .models import UserRole
from .services import generate_exam_attempt, get_student_exam_progress, grade_single_answer
from .web_views import add_material_paths_to_exam_progress


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


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.student = get_user_model().objects.create_user(
            username="student-reset@example.com",
            email="student-reset@example.com",
            password="old-pass-123",
        )

    def test_login_links_to_password_reset(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, reverse("password_reset"))
        self.assertContains(response, "Olvidaste tu contraseña?")

    def test_student_can_request_password_reset_from_public_form(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": "student-reset@example.com"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["student-reset@example.com"])
        self.assertIn("/accounts/reset/", mail.outbox[0].body)


class PageVisitCounterTests(TestCase):
    def test_students_page_increments_visit_counter(self):
        url = reverse("core_web:alumnos")

        first_response = self.client.get(url)
        second_response = self.client.get(url)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        counter = PageVisitCounter.objects.get(page="alumnos")
        self.assertEqual(counter.total, 2)
        self.assertContains(second_response, "Visitas a esta pagina: 2")


class SignupInscripcionLinkTests(TestCase):
    def test_signup_with_activation_code_links_inscripcion_and_activates_course(self):
        activation = ActivationCode.objects.create(
            code="CLASEB-LINK1",
            course_name="Curso teorico",
            duration_days=30,
        )
        inscripcion = Inscripcion.objects.create(
            nombre="Ana Conductora",
            comuna="Santiago",
            correo="ana@example.com",
            telefono="+56 9 1111 2222",
            curso="Curso teorico",
            status=Inscripcion.Status.MATRICULADO,
            activation_code=activation,
        )

        response = self.client.post(
            reverse("student_signup"),
            {
                "first_name": "",
                "last_name": "",
                "email": "ana@example.com",
                "activation_code": "CLASEB-LINK1",
                "password1": "strong-pass-123",
                "password2": "strong-pass-123",
            },
        )

        self.assertRedirects(response, reverse("core_web:dashboard"))
        user = get_user_model().objects.get(username="ana@example.com")
        activation.refresh_from_db()
        inscripcion.refresh_from_db()
        profile = user.profile
        self.assertEqual(inscripcion.user, user)
        self.assertEqual(inscripcion.status, Inscripcion.Status.CURSO_ACTIVO)
        self.assertEqual(activation.used_by, user)
        self.assertTrue(profile.has_active_exam_access())
        self.assertEqual(user.first_name, "Ana")
        self.assertEqual(user.last_name, "Conductora")


class InscripcionTests(TestCase):
    def test_inscripcion_creates_record_and_redirects_to_whatsapp(self):
        payload = {
            "nombre": "Test Alumno",
            "comuna": "Santiago",
            "direccion": "Av. Principal 1234",
            "correo": "test@example.com",
            "telefono": "+56 9 1234 5678",
            "curso": "Curso base mecanico",
        }
        response = self.client.post(reverse("core_web:inscripcion"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("wa.me", response.headers["Location"])
        self.assertTrue(
            Inscripcion.objects.filter(nombre="Test Alumno", correo="test@example.com").exists()
        )
        self.assertEqual(
            Inscripcion.objects.get(nombre="Test Alumno").direccion,
            "Av. Principal 1234",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["virvalescuela@gmail.com"])
        self.assertIn("Test Alumno", mail.outbox[0].body)
        self.assertIn("Av. Principal 1234", mail.outbox[0].body)
        self.assertIn("Curso base mecanico", mail.outbox[0].body)

    def test_duplicate_inscripcion_post_reuses_recent_record(self):
        payload = {
            "nombre": "Test Alumno",
            "comuna": "Santiago",
            "direccion": "Av. Principal 1234",
            "correo": "test@example.com",
            "telefono": "+56 9 1234 5678",
            "curso": "Curso base mecanico",
        }

        first_response = self.client.post(reverse("core_web:inscripcion"), payload)
        second_response = self.client.post(reverse("core_web:inscripcion"), payload)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(
            Inscripcion.objects.filter(nombre="Test Alumno", correo="test@example.com").count(),
            1,
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_inscripcion_prefills_course_from_querystring(self):
        response = self.client.get(
            reverse("core_web:inscripcion") + "?curso=Curso%20intensivo"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'option value="Curso intensivo" selected')


class FichaAlumnoFormTests(TestCase):
    def test_course_field_is_select_with_balance_products(self):
        form = FichaAlumnoForm()

        choices = dict(form.fields["curso"].choices)

        self.assertIn("Clase extra", choices)
        self.assertIn("Ensayo sicotecnico", choices)
        self.assertIn("Simulador", choices)
        self.assertIn("Libro", choices)

    def test_course_field_preserves_legacy_value_when_editing(self):
        ficha = FichaAlumno.objects.create(
            nombre="Alumno antiguo",
            curso="Producto historico",
        )
        form = FichaAlumnoForm(instance=ficha)

        self.assertIn("Producto historico", dict(form.fields["curso"].choices))

    def test_movimiento_form_classifies_concept(self):
        form = FichaMovimientoForm(
            data={
                "fecha": "2026-06-01",
                "concepto": "Clase extra",
                "monto": "25000",
                "forma_pago": "EFECTIVO",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        movimiento = form.save(commit=False)
        self.assertEqual(movimiento.tipo, FichaMovimiento.Tipo.CLASE_EXTRA)


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

    def test_dashboard_can_start_exam_for_selected_topic(self):
        topic_normas = Topic.objects.create(name="Normas de circulación")
        topic_mecanica = Topic.objects.create(name="Mecánica básica")
        normas_question = Question.objects.create(
            text="Pregunta de normas",
            topic=topic_normas,
        )
        Option.objects.create(question=normas_question, text="Correcta", is_correct=True)
        Option.objects.create(question=normas_question, text="Incorrecta", is_correct=False)
        mecanica_question = Question.objects.create(
            text="Pregunta de mecanica",
            topic=topic_mecanica,
        )
        Option.objects.create(question=mecanica_question, text="Correcta", is_correct=True)
        Option.objects.create(question=mecanica_question, text="Incorrecta", is_correct=False)

        self.client.force_login(self.student)
        response = self.client.post(
            reverse("core_web:dashboard"),
            {
                "template_id": self.template.id,
                "topic_id": topic_normas.id,
            },
        )

        self.assertEqual(response.status_code, 302)
        attempt = ExamAttempt.objects.latest("id")
        self.assertEqual(attempt.exam_questions.count(), 1)
        self.assertEqual(attempt.exam_questions.first().topic, topic_normas.name)

    def test_generated_exam_does_not_repeat_same_question_text(self):
        self.template.total_questions = 2
        self.template.save(update_fields=["total_questions"])
        self.question.is_active = False
        self.question.save(update_fields=["is_active"])

        for index in range(2):
            question = Question.objects.create(text="Pregunta duplicada")
            Option.objects.create(question=question, text="Correcta", is_correct=True)
            Option.objects.create(question=question, text="Incorrecta", is_correct=False)

        unique_question = Question.objects.create(text="Pregunta unica")
        Option.objects.create(question=unique_question, text="Correcta", is_correct=True)
        Option.objects.create(question=unique_question, text="Incorrecta", is_correct=False)

        attempt = generate_exam_attempt(self.student, self.template)

        question_texts = list(
            attempt.exam_questions.values_list("question_text", flat=True)
        )
        self.assertEqual(len(question_texts), 2)
        self.assertEqual(len(set(question_texts)), 2)

    def test_generated_exam_keeps_admin_option_order(self):
        self.question.options.all().delete()
        Option.objects.create(question=self.question, text="Primera", is_correct=False)
        Option.objects.create(question=self.question, text="Segunda", is_correct=True)
        Option.objects.create(question=self.question, text="Tercera", is_correct=False)

        attempt = generate_exam_attempt(self.student, self.template)

        options = attempt.exam_questions.get().options
        self.assertEqual(
            [option["text"] for option in options],
            ["Primera", "Segunda", "Tercera"],
        )
        self.assertEqual(
            [index for index, option in enumerate(options) if option["is_correct"]],
            [1],
        )

    def test_selected_small_topic_is_completed_with_other_small_topics(self):
        self.template.total_questions = 3
        self.template.save(update_fields=["total_questions"])
        topic_efficient = Topic.objects.create(name="Conducción eficiente")
        topic_convivencia = Topic.objects.create(name="Convivencia Vial")
        topic_general = Topic.objects.create(name="Normas de circulación")

        efficient_question = Question.objects.create(
            text="Pregunta de conduccion eficiente",
            topic=topic_efficient,
        )
        Option.objects.create(question=efficient_question, text="Correcta", is_correct=True)
        Option.objects.create(question=efficient_question, text="Incorrecta", is_correct=False)

        for index in range(2):
            question = Question.objects.create(
                text=f"Pregunta convivencia {index}",
                topic=topic_convivencia,
            )
            Option.objects.create(question=question, text="Correcta", is_correct=True)
            Option.objects.create(question=question, text="Incorrecta", is_correct=False)

        for index in range(3):
            question = Question.objects.create(
                text=f"Pregunta normas {index}",
                topic=topic_general,
            )
            Option.objects.create(question=question, text="Correcta", is_correct=True)
            Option.objects.create(question=question, text="Incorrecta", is_correct=False)

        self.client.force_login(self.student)
        response = self.client.post(
            reverse("core_web:dashboard"),
            {
                "template_id": self.template.id,
                "topic_id": topic_efficient.id,
            },
        )

        self.assertEqual(response.status_code, 302)
        attempt = ExamAttempt.objects.latest("id")
        topics = set(attempt.exam_questions.values_list("topic", flat=True))
        self.assertEqual(attempt.exam_questions.count(), 3)
        self.assertEqual(topics, {topic_efficient.name, topic_convivencia.name})


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
        self.assertNotContains(response, "Evaluacion teorica")

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
        self.assertContains(response, "Evaluacion teorica")

    def test_activation_extends_active_access_without_resetting_progress(self):
        first_expiration = timezone.now() + timedelta(days=12)
        profile, _ = Profile.objects.get_or_create(user=self.user)
        profile.access_activated_at = timezone.now() - timedelta(days=5)
        profile.access_expires_at = first_expiration
        profile.activated_course_name = "Curso teorico clase B"
        profile.save()
        attempt = ExamAttempt.objects.create(
            student=self.user,
            template=self.template,
            status=ExamAttemptStatus.ENTREGADO,
            score=100,
        )
        exam_question = ExamQuestion.objects.create(
            attempt=attempt,
            source_question=self.question,
            question_text=self.question.text,
            options=[{"text": "Correcta", "is_correct": True}],
        )
        StudentAnswer.objects.create(
            exam_question=exam_question,
            selected_index=0,
            selected_indexes=[0],
            is_correct=True,
        )
        extension_code = ActivationCode.objects.create(
            code="EXT30",
            course_name="Curso teorico clase B",
            duration_days=30,
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("core_web:activate-course"),
            {"activation_code": "EXT30"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        extension_code.refresh_from_db()
        self.assertEqual(extension_code.used_by, self.user)
        self.assertAlmostEqual(
            profile.access_expires_at,
            first_expiration + timedelta(days=30),
            delta=timedelta(seconds=2),
        )
        self.assertEqual(ExamAttempt.objects.filter(student=self.user).count(), 1)
        self.assertEqual(StudentAnswer.objects.filter(exam_question=exam_question).count(), 1)

    def test_api_start_requires_active_access_code(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("exams-start"),
            {"template_id": self.template.id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("acceso a examenes no esta activo", response.json()["detail"])

    def test_signup_page_shows_optional_activation_field(self):
        response = self.client.get(reverse("student_signup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Codigo de activacion")
        self.assertContains(response, "Opcional")

    def test_signup_accepts_six_character_password(self):
        response = self.client.post(
            reverse("student_signup"),
            {
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
            get_user_model().objects.filter(username="clave@example.com").exists()
        )
        user = get_user_model().objects.get(username="clave@example.com")
        self.assertFalse(user.profile.has_active_exam_access())


class FreeActivationCodeAdminTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="masterdj",
            email="masterdj@example.com",
            password="strong-pass-123",
            is_staff=True,
        )
        self.student = user_model.objects.create_user(
            username="student-free",
            email="student-free@example.com",
            password="strong-pass-123",
        )

    def test_staff_can_generate_free_activation_codes(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("core_web:free-activation-codes"),
            {
                "count": 2,
                "days": 30,
                "prefix": "LIBRE",
                "course_name": "Clase B",
            },
        )

        self.assertEqual(response.status_code, 200)
        codes = ActivationCode.objects.filter(code__startswith="LIBRE-")
        self.assertEqual(codes.count(), 2)
        self.assertEqual(codes.filter(used_by__isnull=True).count(), 2)
        self.assertContains(response, "Codigos generados")

    def test_staff_can_email_free_activation_codes_to_external_recipient(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("core_web:free-activation-codes"),
            {
                "count": 1,
                "days": 30,
                "prefix": "EXT",
                "course_name": "Clase B",
                "recipient_email": "otraescuela@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        code = ActivationCode.objects.get(code__startswith="EXT-")
        self.assertEqual(code.used_by, None)
        self.assertEqual(code.sent_to_email, "otraescuela@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["otraescuela@example.com"])
        self.assertIn(code.code, mail.outbox[0].body)
        self.assertContains(response, "Lote enviado a otraescuela@example.com")
        self.assertContains(response, "Codigos libres creados")
        self.assertContains(response, "otraescuela@example.com")

    def test_staff_can_delete_unused_free_activation_code(self):
        code = ActivationCode.objects.create(
            code="BORRAR-123",
            course_name="Clase B",
            sent_to_email="externo@example.com",
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("core_web:free-activation-codes"),
            {
                "action": "delete_code",
                "activation_id": code.id,
            },
        )

        self.assertRedirects(response, reverse("core_web:free-activation-codes"))
        self.assertFalse(ActivationCode.objects.filter(pk=code.pk).exists())

    def test_staff_cannot_delete_used_free_activation_code(self):
        code = ActivationCode.objects.create(
            code="USADO-123",
            course_name="Clase B",
            sent_to_email="externo@example.com",
            used_by=self.student,
            used_at=timezone.now(),
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("core_web:free-activation-codes"),
            {
                "action": "delete_code",
                "activation_id": code.id,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ActivationCode.objects.filter(pk=code.pk).exists())
        self.assertContains(response, "No se puede eliminar un codigo que ya fue usado.")

    def test_non_staff_cannot_generate_free_activation_codes(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("core_web:free-activation-codes"))

        self.assertRedirects(response, reverse("core_web:dashboard"))


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
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["sucursal@example.com"])
        self.assertIn(self.inscripcion.activation_code.code, mail.outbox[0].body)
        self.assertIn("Instrucciones", mail.outbox[0].body)

    def test_staff_can_add_30_days_with_generated_code_for_same_student(self):
        student = get_user_model().objects.create_user(
            username="sucursal@example.com",
            email="sucursal@example.com",
            password="strong-pass-123",
        )
        profile = student.profile
        first_expiration = timezone.now() + timedelta(days=8)
        profile.access_expires_at = first_expiration
        profile.activated_course_name = "Clase B"
        profile.save()
        activation = ActivationCode.objects.create(
            code="CLASEB-EXTEND1",
            course_name="Clase B",
            duration_days=30,
            is_enabled=True,
        )
        self.inscripcion.activation_code = activation
        self.inscripcion.save(update_fields=["activation_code"])

        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("core_web:manage-inscripciones"),
            {"action": "add_30_days", "inscripcion_id": self.inscripcion.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        activation.refresh_from_db()
        profile.refresh_from_db()
        self.inscripcion.refresh_from_db()
        self.assertEqual(activation.used_by, student)
        self.assertEqual(self.inscripcion.user, student)
        self.assertAlmostEqual(
            profile.access_expires_at,
            first_expiration + timedelta(days=30),
            delta=timedelta(seconds=2),
        )
        self.assertContains(response, "Se agregaron 30 dias")

    def test_staff_add_30_days_creates_new_code_when_generated_code_was_used(self):
        student = get_user_model().objects.create_user(
            username="sucursal@example.com",
            email="sucursal@example.com",
            password="strong-pass-123",
        )
        used_activation = ActivationCode.objects.create(
            code="CLASEB-USED1",
            course_name="Clase B",
            duration_days=30,
            is_enabled=True,
            used_by=student,
            used_at=timezone.now(),
        )
        self.inscripcion.activation_code = used_activation
        self.inscripcion.save(update_fields=["activation_code"])
        initial_count = ActivationCode.objects.count()

        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("core_web:manage-inscripciones"),
            {"action": "add_30_days", "inscripcion_id": self.inscripcion.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ActivationCode.objects.count(), initial_count + 1)
        new_activation = ActivationCode.objects.exclude(pk=used_activation.pk).latest("created_at")
        self.assertEqual(new_activation.used_by, student)
        student.profile.refresh_from_db()
        self.assertTrue(student.profile.has_active_exam_access())

    def test_staff_add_30_days_does_not_crash_when_user_has_other_inscripcion(self):
        student = get_user_model().objects.create_user(
            username="sucursal@example.com",
            email="sucursal@example.com",
            password="strong-pass-123",
        )
        other_inscripcion = Inscripcion.objects.create(
            nombre="Alumno Sucursal Original",
            comuna="Santiago",
            correo="sucursal@example.com",
            telefono="+56 9 2222 3333",
            curso="Curso teorico",
            user=student,
        )
        first_expiration = timezone.now() - timedelta(days=3)
        student.profile.access_expires_at = first_expiration
        student.profile.save()
        activation = ActivationCode.objects.create(
            code="CLASEB-DUP1",
            course_name="Clase B",
            duration_days=30,
            is_enabled=True,
        )
        self.inscripcion.activation_code = activation
        self.inscripcion.save(update_fields=["activation_code"])

        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("core_web:manage-inscripciones"),
            {"action": "add_30_days", "inscripcion_id": self.inscripcion.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        activation.refresh_from_db()
        self.inscripcion.refresh_from_db()
        other_inscripcion.refresh_from_db()
        student.profile.refresh_from_db()
        self.assertEqual(activation.used_by, student)
        self.assertIsNone(self.inscripcion.user)
        self.assertEqual(self.inscripcion.status, Inscripcion.Status.CURSO_ACTIVO)
        self.assertEqual(other_inscripcion.user, student)
        self.assertTrue(student.profile.has_active_exam_access())
        self.assertContains(response, "Se agregaron 30 dias")

    def test_staff_can_open_internal_management_view_from_dashboard_nav(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core_web:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("core_web:internal-management"))
        self.assertNotContains(response, reverse("balance:dashboard"))
        self.assertNotContains(response, reverse("agendamiento:grid"))

        management_response = self.client.get(reverse("core_web:internal-management"))
        self.assertEqual(management_response.status_code, 200)
        self.assertContains(management_response, "Inscripciones pendientes")
        self.assertContains(management_response, "Gestionar fichas")
        self.assertContains(management_response, "Balance mensual")
        self.assertContains(management_response, "Agendamiento")
        self.assertContains(management_response, "Auditar alumnos")
        self.assertContains(management_response, "Crear codigos libres")

    def test_export_center_is_only_for_superuser(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core_web:export-center"))

        self.assertRedirects(response, reverse("core_web:dashboard"))

        superuser = get_user_model().objects.create_superuser(
            username="owner",
            email="owner@example.com",
            password="strong-pass-123",
        )
        self.client.force_login(superuser)
        response = self.client.get(reverse("core_web:internal-management"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("core_web:export-center"))

        response = self.client.get(reverse("core_web:export-center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Exportaciones")
        self.assertContains(response, reverse("core_web:export-download", args=["fichas"]))
        self.assertContains(response, reverse("core_web:export-download", args=["gestion"]))
        self.assertContains(response, reverse("core_web:export-download", args=["odo"]))
        self.assertContains(response, reverse("core_web:export-download", args=["balance"]))

    def test_superuser_can_export_fichas_zip(self):
        superuser = get_user_model().objects.create_superuser(
            username="owner-export",
            email="owner-export@example.com",
            password="strong-pass-123",
        )
        ficha = FichaAlumno.objects.create(
            numero_ficha=5199,
            nombre="Alumno exportado",
            correo="exportado@example.com",
            curso="Curso intensivo",
            valor_pagado=120000,
        )
        FichaMovimiento.sync_pago_inicial(ficha)
        self.client.force_login(superuser)

        response = self.client.get(reverse("core_web:export-download", args=["fichas"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"fichas.csv", "movimientos_fichas.csv"},
            )
            fichas_csv = archive.read("fichas.csv").decode("utf-8-sig")
            movimientos_csv = archive.read("movimientos_fichas.csv").decode("utf-8-sig")
        self.assertIn("Alumno exportado", fichas_csv)
        self.assertIn("exportado@example.com", fichas_csv)
        self.assertIn("Curso intensivo", movimientos_csv)

    def test_superuser_can_export_gestion_zip(self):
        superuser = get_user_model().objects.create_superuser(
            username="owner-gestion",
            email="owner-gestion@example.com",
            password="strong-pass-123",
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse("core_web:export-download", args=["gestion"]))

        self.assertEqual(response.status_code, 200)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "alumnos.csv",
                    "inscripciones.csv",
                    "codigos_activacion.csv",
                    "intentos_examen.csv",
                },
            )
            inscripciones_csv = archive.read("inscripciones.csv").decode("utf-8-sig")
            codigos_csv = archive.read("codigos_activacion.csv").decode("utf-8-sig")
        self.assertIn("Alumno Sucursal", inscripciones_csv)
        self.assertIn("CLASEB-LIBRE1", codigos_csv)

    def test_superuser_can_export_odo_zip(self):
        from odo.models import Vehicle

        superuser = get_user_model().objects.create_superuser(
            username="owner-odo",
            email="owner-odo@example.com",
            password="strong-pass-123",
        )
        Vehicle.objects.create(
            owner=superuser,
            plate="ABCD12",
            alias="Auto escuela",
            current_odometer=12345,
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse("core_web:export-download", args=["odo"]))

        self.assertEqual(response.status_code, 200)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertIn("vehiculos.csv", archive.namelist())
            vehicles_csv = archive.read("vehiculos.csv").decode("utf-8-sig")
        self.assertIn("ABCD12", vehicles_csv)
        self.assertIn("Auto escuela", vehicles_csv)

    def test_superuser_can_export_balance_zip(self):
        from balance.models import ConceptoGasto, GastoMensual

        superuser = get_user_model().objects.create_superuser(
            username="owner-balance",
            email="owner-balance@example.com",
            password="strong-pass-123",
        )
        FichaAlumno.objects.create(
            numero_ficha=5201,
            fecha_inscripcion=date(2026, 1, 10),
            nombre="Alumno balance",
            curso="Curso intensivo",
            valor_pagado=180000,
        )
        concepto = ConceptoGasto.objects.create(nombre="Arriendo export", orden=1)
        GastoMensual.objects.create(
            concepto=concepto,
            anio=2026,
            mes=1,
            monto=500000,
            updated_by=superuser,
        )
        self.client.force_login(superuser)

        response = self.client.get(
            reverse("core_web:export-download", args=["balance"]) + "?anio=2026"
        )

        self.assertEqual(response.status_code, 200)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "resumen_mensual.csv",
                    "ingresos_por_producto.csv",
                    "gastos_por_concepto.csv",
                    "conceptos_gasto.csv",
                    "gastos_manuales_detalle.csv",
                },
            )
            resumen_csv = archive.read("resumen_mensual.csv").decode("utf-8-sig")
            gastos_csv = archive.read("gastos_por_concepto.csv").decode("utf-8-sig")
        self.assertIn("180000", resumen_csv)
        self.assertIn("Arriendo export", gastos_csv)

    def test_staff_can_view_student_audit_list_and_profile(self):
        self.client.force_login(self.staff)

        list_response = self.client.get(reverse("core_web:staff-students"))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Gestion interna de alumnos")
        self.assertContains(list_response, "Alumno")

        detail_response = self.client.get(
            reverse("core_web:staff-student-audit", args=[self.student.pk])
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Vista de auditoria solo lectura")
        self.assertContains(detail_response, "Examenes del alumno")

    def test_staff_can_create_ficha_from_inscripcion(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("core_web:fichas"),
            {
                "action": "create_from_inscripcion",
                "inscripcion_id": self.inscripcion.id,
                "numero_ficha": "5176",
                "fecha_inscripcion": "2026-06-01",
                "nombre": self.inscripcion.nombre,
                "correo": self.inscripcion.correo,
                "telefono": self.inscripcion.telefono,
                "direccion": "Av. Principal 1234",
                "curso": self.inscripcion.curso,
                "rut": "12.345.678-9",
                "fecha_nacimiento": "2000-06-01",
                "valor_pagado": "120000",
                "forma_pago": "TRANSFERENCIA",
            },
        )

        self.assertRedirects(response, reverse("core_web:fichas"))
        ficha = FichaAlumno.objects.get(numero_ficha=5176)
        self.assertEqual(ficha.inscripcion, self.inscripcion)
        self.assertEqual(ficha.correo, self.inscripcion.correo)
        self.assertEqual(ficha.direccion, "Av. Principal 1234")
        self.assertEqual(ficha.valor_pagado, 120000)
        movimiento = ficha.movimientos.get()
        self.assertEqual(movimiento.concepto, self.inscripcion.curso)
        self.assertEqual(movimiento.monto, 120000)

    def test_ficha_create_form_shows_next_correlative_number(self):
        FichaAlumno.objects.create(numero_ficha=1, nombre="Alumno uno")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("core_web:fichas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="numero_ficha"')
        self.assertContains(response, 'value="2"')

    def test_staff_can_edit_existing_ficha(self):
        ficha = FichaAlumno.objects.create(
            numero_ficha=5177,
            nombre="Nombre Malo",
            correo="mal@example.com",
            telefono="+56 9 1111 2222",
            curso="Curso intensivo",
            fecha_inscripcion=date(2026, 6, 1),
            fecha_nacimiento=date(2000, 6, 1),
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("core_web:fichas") + f"?edit={ficha.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Editar ficha 5177")
        self.assertContains(response, 'value="2026-06-01"')
        self.assertContains(response, 'value="2000-06-01"')

        response = self.client.post(
            reverse("core_web:fichas"),
            {
                "action": "edit",
                "ficha_id": ficha.id,
                "numero_ficha": "5177",
                "fecha_inscripcion": "2026-06-01",
                "nombre": "Nombre Corregido",
                "correo": "bien@example.com",
                "telefono": "912345678",
                "curso": "Curso intensivo",
                "rut": "12.345.678-9",
                "fecha_nacimiento": "2000-06-01",
                "valor_pagado": "130000",
                "forma_pago": "EFECTIVO",
            },
        )

        self.assertRedirects(response, reverse("core_web:fichas"))
        ficha.refresh_from_db()
        self.assertEqual(ficha.nombre, "Nombre Corregido")
        self.assertEqual(ficha.correo, "bien@example.com")
        self.assertEqual(ficha.telefono, "+56 9 1234 5678")
        self.assertEqual(ficha.valor_pagado, 130000)
        movimiento = ficha.movimientos.get()
        self.assertEqual(movimiento.concepto, "Curso intensivo")
        self.assertEqual(movimiento.monto, 130000)

    def test_staff_can_view_complete_fichas_list(self):
        ficha = FichaAlumno.objects.create(
            numero_ficha=5188,
            fecha_inscripcion=date(2026, 6, 3),
            nombre="Alumno listado",
            correo="listado@example.com",
            telefono="+56 9 9999 8888",
            direccion="Av. Completa 456",
            curso="Curso intensivo",
            rut="11.111.111-1",
            fecha_nacimiento=date(1999, 5, 4),
            valor_pagado=150000,
            forma_pago="TRANSFERENCIA",
            observaciones="Ficha completa",
        )
        FichaMovimiento.sync_pago_inicial(ficha)
        self.client.force_login(self.staff)

        management_response = self.client.get(reverse("core_web:fichas"))
        self.assertContains(management_response, reverse("core_web:fichas-list"))

        response = self.client.get(reverse("core_web:fichas-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ficha 5188")
        self.assertContains(response, "listado@example.com")
        self.assertContains(response, "Av. Completa 456")
        self.assertContains(response, "Ficha completa")
        self.assertContains(response, "Curso intensivo")
        self.assertContains(response, "Editar ficha")

    def test_staff_can_search_fichas_list_by_text_fields(self):
        FichaAlumno.objects.create(
            numero_ficha=5201,
            nombre="Rush Alumno",
            correo="rush@example.com",
            telefono="+56 9 1111 2222",
            rut="11.111.111-1",
            curso="Curso profesional",
        )
        FichaAlumno.objects.create(
            numero_ficha=5202,
            nombre="Alumno oculto",
            correo="oculto@example.com",
            telefono="+56 9 3333 4444",
            rut="22.222.222-2",
            curso="Curso base",
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("core_web:fichas-list"), {"q": "rush"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="rush"')
        self.assertContains(response, "1 resultado para")
        self.assertContains(response, "Ficha 5201")
        self.assertNotContains(response, "Ficha 5202")

        rut_response = self.client.get(
            reverse("core_web:fichas-list"), {"q": "11.111.111"}
        )

        self.assertContains(rut_response, "Ficha 5201")
        self.assertNotContains(rut_response, "Ficha 5202")

    def test_staff_can_search_fichas_list_by_numero_ficha(self):
        FichaAlumno.objects.create(numero_ficha=5201, nombre="Ficha exacta")
        FichaAlumno.objects.create(numero_ficha=5202, nombre="Otra ficha")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("core_web:fichas-list"), {"q": "5201"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ficha 5201")
        self.assertNotContains(response, "Ficha 5202")

    def test_staff_sees_empty_search_message_on_fichas_list(self):
        FichaAlumno.objects.create(numero_ficha=5201, nombre="Ficha existente")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("core_web:fichas-list"), {"q": "sin-match"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '0 resultados para "sin-match"')
        self.assertContains(response, 'No se encontraron fichas para "sin-match".')
        self.assertNotContains(response, "Ficha 5201")

    def test_staff_can_add_movimiento_to_existing_ficha(self):
        ficha = FichaAlumno.objects.create(
            numero_ficha=5178,
            nombre="Alumno con extra",
            correo="extra@example.com",
            curso="Curso base mecanico",
            valor_pagado=180000,
        )
        FichaMovimiento.sync_pago_inicial(ficha)
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("core_web:fichas"),
            {
                "action": "add_movimiento",
                "ficha_id": ficha.id,
                "fecha": "2026-06-10",
                "concepto": "Clase extra",
                "monto": "25000",
                "forma_pago": "TRANSFERENCIA",
                "observaciones": "Clase extra ficha 5178",
            },
        )

        self.assertRedirects(response, reverse("core_web:fichas") + f"?edit={ficha.id}")
        extra = ficha.movimientos.get(concepto="Clase extra")
        self.assertEqual(extra.tipo, FichaMovimiento.Tipo.CLASE_EXTRA)
        self.assertEqual(extra.monto, 25000)

    def test_staff_can_audit_exam_detail_without_answer_actions(self):
        template = ExamTemplate.objects.create(
            name="Examen auditoria",
            total_questions=1,
            duration_minutes=45,
        )
        attempt = ExamAttempt.objects.create(
            student=self.student,
            template=template,
            status=ExamAttemptStatus.EN_CURSO,
        )
        ExamQuestion.objects.create(
            attempt=attempt,
            question_text="Pregunta auditada",
            topic="Normas",
            options=[
                {"text": "Correcta", "is_correct": True},
                {"text": "Incorrecta", "is_correct": False},
            ],
        )

        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("core_web:staff-exam-audit", args=[attempt.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vista de auditoria")
        self.assertContains(response, "Pregunta auditada")
        self.assertNotContains(response, "Guardar progreso")
        self.assertNotContains(response, "Finalizar y calificar")


class AdminLabelsTests(TestCase):
    def test_profile_and_inscripcion_have_clear_admin_labels(self):
        self.assertEqual(Profile._meta.verbose_name_plural, "Registros de plataforma")
        self.assertEqual(Inscripcion._meta.verbose_name_plural, "Solicitudes de inscripcion")


class StudentProgressTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.student = user_model.objects.create_user(
            username="progress-student",
            password="strong-pass-123",
        )
        profile = self.student.profile
        profile.access_activated_at = timezone.now()
        profile.access_expires_at = timezone.now() + timedelta(days=30)
        profile.activated_course_name = "Clase B"
        profile.save()
        self.topic_normas = Topic.objects.create(name="Normas")
        self.topic_senales = Topic.objects.create(name="Senales")
        self.template = ExamTemplate.objects.create(
            name="Examen clase B",
            total_questions=2,
            duration_minutes=45,
        )

    def _create_question(self, text, topic):
        question = Question.objects.create(text=text, topic=topic)
        Option.objects.create(question=question, text="Correcta", is_correct=True)
        Option.objects.create(question=question, text="Incorrecta", is_correct=False)
        return question

    def _create_delivered_attempt(self, answered_questions):
        attempt = ExamAttempt.objects.create(
            student=self.student,
            template=self.template,
            status=ExamAttemptStatus.ENTREGADO,
            score=0,
            finished_at=timezone.now(),
        )
        correct_count = 0
        for question, is_correct in answered_questions:
            exam_question = ExamQuestion.objects.create(
                attempt=attempt,
                source_question=question,
                question_text=question.text,
                topic=question.topic.name,
                options=[
                    {"text": "Correcta", "is_correct": True},
                    {"text": "Incorrecta", "is_correct": False},
                ],
            )
            StudentAnswer.objects.create(
                exam_question=exam_question,
                selected_index=0 if is_correct else 1,
                selected_indexes=[0 if is_correct else 1],
                is_correct=is_correct,
            )
            correct_count += 1 if is_correct else 0
        attempt.score = int(round((correct_count / len(answered_questions)) * 100))
        attempt.save(update_fields=["score"])
        return attempt

    def test_progress_calculates_general_coverage_and_topics(self):
        q1 = self._create_question("Normas 1", self.topic_normas)
        q2 = self._create_question("Normas 2", self.topic_normas)
        q3 = self._create_question("Senales 1", self.topic_senales)
        self._create_question("Senales 2", self.topic_senales)
        self._create_delivered_attempt([(q1, True), (q2, False), (q3, True)])

        progress = get_student_exam_progress(self.student)

        self.assertEqual(progress["coverage_percent"], 75)
        self.assertEqual(progress["general_percent"], 67)
        self.assertEqual(progress["failed_pending_count"], 1)
        topic_percentages = {
            topic["topic"]: topic["percent"] for topic in progress["topics"]
        }
        self.assertEqual(topic_percentages["Normas"], 50)
        self.assertEqual(topic_percentages["Senales"], 100)

    def test_progress_includes_topics_without_answers(self):
        self._create_question("Normas 1", self.topic_normas)
        self._create_question("Senales 1", self.topic_senales)

        progress = get_student_exam_progress(self.student)

        topics = {topic["topic"]: topic for topic in progress["topics"]}
        self.assertEqual(topics["Normas"]["answered"], 0)
        self.assertEqual(topics["Normas"]["percent"], 0)
        self.assertEqual(topics["Normas"]["coverage_percent"], 0)
        self.assertEqual(topics["Senales"]["answered"], 0)

    def test_progress_topics_are_ordered_by_course_chapters(self):
        topic_names = [
            "Anexo-Definiciones",
            "Conduccion eficiente",
            "Siniestros de transito",
            "Normas de circulacion",
            "Informaciones importantes",
            "La persona en el transito",
            "Los principios de la conduccion",
            "Convivencia vial",
            "Conduccion en circunstancias especiales",
            "La y los usuarios vulnerables",
        ]
        for topic_name in topic_names:
            topic = Topic.objects.create(name=topic_name)
            self._create_question(f"{topic_name} pregunta", topic)

        progress = get_student_exam_progress(self.student)

        ordered_topics = [
            topic["topic"]
            for topic in progress["topics"]
            if topic["topic"] in topic_names
        ]
        self.assertEqual(
            ordered_topics,
            [
                "Siniestros de transito",
                "Los principios de la conduccion",
                "Convivencia vial",
                "La persona en el transito",
                "La y los usuarios vulnerables",
                "Normas de circulacion",
                "Conduccion en circunstancias especiales",
                "Conduccion eficiente",
                "Informaciones importantes",
                "Anexo-Definiciones",
            ],
        )

    def test_anexo_definiciones_includes_all_material_links(self):
        progress = {
            "topics": [
                {
                    "topic": "Anexo-Definiciones",
                    "answered": 0,
                    "correct": 0,
                    "percent": 0,
                    "coverage_percent": 0,
                    "bank_total": 0,
                }
            ]
        }

        progress = add_material_paths_to_exam_progress(progress)

        materials = progress["topics"][0]["materials"]
        self.assertEqual(
            [material["label"] for material in materials],
            ["Glosario", "Senales", "Disposiciones"],
        )

    def test_new_attempt_prioritizes_unseen_questions_before_repeats(self):
        q1 = self._create_question("Vista", self.topic_normas)
        q2 = self._create_question("Nueva", self.topic_normas)
        self._create_delivered_attempt([(q1, True)])

        attempt = generate_exam_attempt(self.student, self.template)

        selected_ids = {
            exam_question.source_question_id
            for exam_question in attempt.exam_questions.all()
        }
        self.assertIn(q2.id, selected_ids)


class AnswerGradingTests(TestCase):
    def test_multi_answer_requires_all_correct_options(self):
        user_model = get_user_model()
        student = user_model.objects.create_user(
            username="multi-answer-student",
            password="strong-pass-123",
        )
        template = ExamTemplate.objects.create(name="Examen multi", total_questions=1)
        attempt = ExamAttempt.objects.create(student=student, template=template)
        exam_question = ExamQuestion.objects.create(
            attempt=attempt,
            question_text="Seleccione dos respuestas correctas",
            options=[
                {"text": "Correcta A", "is_correct": True},
                {"text": "Incorrecta", "is_correct": False},
                {"text": "Correcta B", "is_correct": True},
            ],
        )

        partial_feedback = grade_single_answer(exam_question, [0], include_feedback=True)
        exam_question.answer.refresh_from_db()

        self.assertFalse(partial_feedback["is_correct"])
        self.assertFalse(exam_question.answer.is_correct)

        complete_feedback = grade_single_answer(exam_question, [0, 2], include_feedback=True)
        exam_question.answer.refresh_from_db()

        self.assertTrue(complete_feedback["is_correct"])
        self.assertTrue(exam_question.answer.is_correct)
