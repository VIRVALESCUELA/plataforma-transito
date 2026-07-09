from datetime import time

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse

from core.models import FichaAlumno, FichaMovimiento

from .models import DrivingLesson, LessonStatus, ScheduleBlock, ScheduleOpening, ScheduleResource


class ScheduleGridTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="agenda-staff",
            email="agenda-staff@example.com",
            password="strong-pass-123",
            is_staff=True,
        )
        self.student = user_model.objects.create_user(
            username="agenda-student",
            email="agenda-student@example.com",
            password="strong-pass-123",
        )

    def test_requires_staff(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("agendamiento:grid"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("core_web:dashboard"), response.headers["Location"])

    def test_staff_can_view_continuous_grid(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("agendamiento:grid") + "?start=2026-06-01&days=30")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Agendamiento de clases")
        self.assertContains(response, "09:00")
        self.assertContains(response, "19:00")
        self.assertNotContains(response, "19:00-20:00")

    def test_staff_grid_defaults_to_15_days(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("agendamiento:grid") + "?start=2026-06-01")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["day_count"], 15)
        self.assertEqual(len(response.context["schedules"][0]["rows"]), 15)

    def test_staff_can_view_15_day_grid_from_range_selector(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("agendamiento:grid") + "?start=2026-06-01&days=15")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Agendamiento de clases")
        self.assertNotContains(response, "Vista completa")
        self.assertNotContains(response, "Vista 15 dias")
        self.assertEqual(len(response.context["schedules"][0]["rows"]), 15)

    def test_staff_can_search_past_lesson_by_ficha(self):
        DrivingLesson.objects.create(
            date="2026-05-04",
            slot_key="0900",
            start_time=time(9, 0),
            end_time=time(9, 45),
            ficha=5176,
            lesson_number=3,
            course_kind="12_MODULOS",
            status=LessonStatus.ABSENT,
            notes="Ausente por trabajo.",
            created_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("agendamiento:search") + "?search_ficha=5176")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "5176/3")
        self.assertContains(response, "Ausente alumno")
        self.assertContains(response, "Ausente por trabajo.")
        self.assertContains(response, "start=2026-05-04")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Escuela Virval <virvalescuela@gmail.com>",
    )
    def test_staff_can_send_schedule_email_for_ficha(self):
        FichaAlumno.objects.create(
            numero_ficha=5179,
            nombre="Alumno Correo",
            correo="alumno@example.com",
        )
        resource = ScheduleResource.objects.create(
            name="Auto 1",
            instructor="Instructor Correo",
            vehicle="ABC123",
        )
        DrivingLesson.objects.create(
            resource=resource,
            date="2026-07-01",
            slot_key="0900",
            start_time=time(9, 0),
            end_time=time(9, 45),
            ficha=5179,
            lesson_number=1,
            course_kind="12_MODULOS",
            created_by=self.staff,
        )
        DrivingLesson.objects.create(
            resource=resource,
            date="2026-07-02",
            slot_key="0945",
            start_time=time(9, 45),
            end_time=time(10, 30),
            ficha=5179,
            lesson_number=2,
            course_kind="12_MODULOS",
            created_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:search"),
            {
                "action": "send_schedule_email",
                "start": "2026-07-01",
                "days": "7",
                "ficha": "5179",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alumno@example.com"])
        self.assertIn("Tus clases practicas agendadas", mail.outbox[0].subject)
        self.assertIn("Instructor: Instructor Correo", mail.outbox[0].body)
        self.assertIn("Dias y horas agendadas:", mail.outbox[0].body)
        self.assertIn("Clase 1: 01/07/2026 a las 09:00", mail.outbox[0].body)
        self.assertIn("Clase 2: 02/07/2026 a las 09:45", mail.outbox[0].body)
        self.assertIn(
            "Cualquier cambio debe solicitarse con 48 horas de anticipacion.",
            mail.outbox[0].body,
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Escuela Virval <virvalescuela@gmail.com>",
    )
    def test_staff_can_edit_schedule_email_body_before_sending(self):
        FichaAlumno.objects.create(
            numero_ficha=5181,
            nombre="Alumno Editado",
            correo="editado@example.com",
        )
        DrivingLesson.objects.create(
            date="2026-07-03",
            slot_key="0900",
            start_time=time(9, 0),
            end_time=time(9, 45),
            ficha=5181,
            lesson_number=1,
            course_kind="12_MODULOS",
            created_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:search"),
            {
                "action": "send_schedule_email",
                "start": "2026-07-01",
                "days": "7",
                "ficha": "5181",
                "schedule_email_body": "Mensaje personalizado para este alumno.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].body, "Mensaje personalizado para este alumno.")

    def test_staff_can_open_whatsapp_message_for_ficha(self):
        FichaAlumno.objects.create(
            numero_ficha=5180,
            nombre="Alumno WhatsApp",
            correo="alumno@example.com",
            telefono="+56 9 1111 2222",
        )
        DrivingLesson.objects.create(
            date="2026-07-01",
            slot_key="0900",
            start_time=time(9, 0),
            end_time=time(9, 45),
            ficha=5180,
            lesson_number=1,
            course_kind="12_MODULOS",
            created_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("agendamiento:search") + "?search_ficha=5180")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enviar WhatsApp")
        self.assertContains(response, "https://wa.me/56911112222")

    def test_staff_can_create_lesson(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-01",
                "days": "30",
                "date": "2026-06-01",
                "slot_key": "0900",
                "ficha": "5176",
                "lesson_number": "1",
                "course_kind": "12_MODULOS",
            },
        )

        self.assertEqual(response.status_code, 302)
        lesson = DrivingLesson.objects.get(date="2026-06-01", slot_key="0900")
        self.assertEqual(lesson.ficha, 5176)
        self.assertEqual(lesson.lesson_number, 1)
        self.assertIsNotNone(lesson.resource)

    def test_staff_can_create_same_slot_for_different_resources(self):
        first = ScheduleResource.objects.create(
            name="Instructor A / Auto A",
            instructor="Instructor A",
            vehicle="Auto A",
            sort_order=1,
        )
        second = ScheduleResource.objects.create(
            name="Instructor B / Auto B",
            instructor="Instructor B",
            vehicle="Auto B",
            sort_order=2,
        )
        self.client.force_login(self.staff)

        for resource, ficha in ((first, "5176"), (second, "5177")):
            response = self.client.post(
                reverse("agendamiento:grid"),
                {
                    "action": "save_lesson",
                    "resource_id": str(resource.id),
                    "start": "2026-06-01",
                    "days": "30",
                    "date": "2026-06-01",
                    "slot_key": "0900",
                    "ficha": ficha,
                    "lesson_number": "1",
                    "course_kind": "12_MODULOS",
                },
            )
            self.assertEqual(response.status_code, 302)

        self.assertEqual(DrivingLesson.objects.filter(date="2026-06-01", slot_key="0900").count(), 2)

    def test_staff_can_manage_schedule_resources(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:resources"),
            {
                "action": "create",
                "name": "Juan / Auto ABCD-12",
                "instructor": "Juan",
                "vehicle": "ABCD-12",
                "color": "#2f80ed",
                "sort_order": "2",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        resource = ScheduleResource.objects.get(name="Juan / Auto ABCD-12")
        self.assertEqual(resource.instructor, "Juan")
        self.assertEqual(resource.color, "#2f80ed")
        self.assertTrue(resource.is_active)

        response = self.client.get(reverse("agendamiento:resources") + f"?edit={resource.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Guardar cambios")

        response = self.client.post(
            reverse("agendamiento:resources"),
            {
                "action": "edit",
                "resource_id": str(resource.id),
                "name": "Juan Perez / Auto ABCD-12",
                "instructor": "Juan Perez",
                "vehicle": "ABCD-12",
                "color": "#27ae60",
                "sort_order": "1",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        resource.refresh_from_db()
        self.assertEqual(resource.name, "Juan Perez / Auto ABCD-12")
        self.assertEqual(resource.color, "#27ae60")
        self.assertEqual(resource.sort_order, 1)

        response = self.client.post(
            reverse("agendamiento:resources"),
            {
                "action": "toggle",
                "resource_id": str(resource.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        resource.refresh_from_db()
        self.assertFalse(resource.is_active)

    def test_staff_can_save_lesson_status_and_comment(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-01",
                "days": "30",
                "date": "2026-06-01",
                "slot_key": "0900",
                "ficha": "5176",
                "lesson_number": "1",
                "course_kind": "12_MODULOS",
                "status": LessonStatus.ABSENT,
                "notes": "Alumno no se presento.",
            },
        )

        self.assertEqual(response.status_code, 302)
        lesson = DrivingLesson.objects.get(date="2026-06-01", slot_key="0900")
        self.assertEqual(lesson.status, LessonStatus.ABSENT)
        self.assertEqual(lesson.notes, "Alumno no se presento.")

    def test_staff_can_create_lesson_from_existing_ficha(self):
        ficha = FichaAlumno.objects.create(
            numero_ficha=5177,
            nombre="Alumno Agenda",
            correo="agenda@example.com",
            clases_contratadas=12,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-01",
                "days": "30",
                "date": "2026-06-01",
                "slot_key": "0945",
                "ficha_alumno": str(ficha.id),
                "lesson_number": "2",
                "course_kind": "12_MODULOS",
            },
        )

        self.assertEqual(response.status_code, 302)
        lesson = DrivingLesson.objects.get(date="2026-06-01", slot_key="0945")
        self.assertEqual(lesson.ficha_alumno, ficha)
        self.assertEqual(lesson.ficha, 5177)
        self.assertEqual(lesson.lesson_number, 2)

    def test_existing_ficha_cannot_exceed_sold_lesson_quota(self):
        ficha = FichaAlumno.objects.create(
            numero_ficha=5182,
            nombre="Alumno Cupo",
            correo="cupo@example.com",
            clases_contratadas=1,
        )
        DrivingLesson.objects.create(
            date="2026-06-01",
            slot_key="0900",
            start_time=time(9, 0),
            end_time=time(9, 45),
            ficha_alumno=ficha,
            ficha=5182,
            lesson_number=1,
            course_kind="OTRO",
            created_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-01",
                "days": "30",
                "date": "2026-06-01",
                "slot_key": "0945",
                "ficha_alumno": str(ficha.id),
                "lesson_number": "2",
                "course_kind": "12_MODULOS",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DrivingLesson.objects.filter(date="2026-06-01", slot_key="0945").exists())
        self.assertContains(response, "supera el cupo de la ficha 5182")

    def test_extra_lesson_movement_unlocks_one_more_schedule_slot(self):
        ficha = FichaAlumno.objects.create(
            numero_ficha=5183,
            nombre="Alumno Extra",
            correo="extra-agenda@example.com",
            clases_contratadas=1,
        )
        FichaMovimiento.objects.create(
            ficha=ficha,
            tipo=FichaMovimiento.Tipo.CLASE_EXTRA,
            concepto="Clase extra",
            monto=25000,
        )
        DrivingLesson.objects.create(
            date="2026-06-01",
            slot_key="0900",
            start_time=time(9, 0),
            end_time=time(9, 45),
            ficha_alumno=ficha,
            ficha=5183,
            lesson_number=1,
            course_kind="OTRO",
            created_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-01",
                "days": "30",
                "date": "2026-06-01",
                "slot_key": "0945",
                "ficha_alumno": str(ficha.id),
                "lesson_number": "2",
                "course_kind": "12_MODULOS",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(DrivingLesson.objects.filter(date="2026-06-01", slot_key="0945").exists())

    def test_staff_can_block_day(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "block_day",
                "start": "2026-06-01",
                "days": "30",
                "date": "2026-06-07",
                "reason": "Feriado",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ScheduleBlock.objects.filter(
                date="2026-06-07",
                scope=ScheduleBlock.Scope.DAY,
                reason="Feriado",
            ).exists()
        )

    def test_friday_work_slots_are_blocked_by_rule_without_label(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("agendamiento:grid") + "?start=2026-06-05&days=1")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "LABORAL")
        friday_cells = response.context["schedules"][0]["rows"][0]["cells"]
        blocked_slot_keys = {
            cell["slot"]["key"]
            for cell in friday_cells
            if cell["work_rule_blocked"]
        }
        self.assertEqual(blocked_slot_keys, {"1200", "1800", "1900"})

    def test_cannot_create_lesson_on_friday_work_blocked_slot(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-05",
                "days": "7",
                "date": "2026-06-05",
                "slot_key": "1800",
                "ficha": "5176",
                "lesson_number": "1",
                "course_kind": "12_MODULOS",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DrivingLesson.objects.filter(date="2026-06-05", slot_key="1800").exists())
        self.assertContains(response, "Ese horario esta bloqueado por regla de agenda.")

    def test_cannot_create_lesson_on_weekend(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-06",
                "days": "7",
                "date": "2026-06-06",
                "slot_key": "0900",
                "ficha": "5176",
                "lesson_number": "1",
                "course_kind": "12_MODULOS",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DrivingLesson.objects.filter(date="2026-06-06", slot_key="0900").exists())
        self.assertContains(response, "Ese horario esta bloqueado por regla de agenda.")

    def test_staff_can_open_weekend_slot_and_create_lesson(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "unblock",
                "start": "2026-06-06",
                "days": "7",
                "date": "2026-06-06",
                "slot_key": "0900",
                "notes": "Clase especial",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ScheduleOpening.objects.filter(
                date="2026-06-06",
                scope=ScheduleOpening.Scope.SLOT,
                slot_key="0900",
            ).exists()
        )

        response = self.client.post(
            reverse("agendamiento:grid"),
            {
                "action": "save_lesson",
                "start": "2026-06-06",
                "days": "7",
                "date": "2026-06-06",
                "slot_key": "0900",
                "ficha": "5176",
                "lesson_number": "1",
                "course_kind": "12_MODULOS",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(DrivingLesson.objects.filter(date="2026-06-06", slot_key="0900").exists())
