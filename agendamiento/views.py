from datetime import date, timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from .forms import ScheduleResourceForm
from .models import (
    CourseKind,
    DrivingLesson,
    LessonStatus,
    ScheduleBlock,
    ScheduleOpening,
    ScheduleResource,
)
from .slots import FRIDAY_WORK_BLOCKED_SLOT_KEYS, SCHEDULE_SLOTS, SLOT_BY_KEY
from core.models import FichaAlumno


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return bool(self.request.user and self.request.user.is_staff)

    def handle_no_permission(self):
        messages.error(self.request, "No tienes permisos para acceder a agendamiento.")
        return redirect("core_web:dashboard")


class ScheduleGridView(LoginRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "agendamiento/schedule_grid.html"
    login_url = reverse_lazy("login")
    redirect_field_name = "next"

    @method_decorator(never_cache)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def _parse_start_date(self):
        raw = self.request.GET.get("start")
        if not raw:
            return date.today()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return date.today()

    def _parse_day_count(self):
        raw = self.request.GET.get("days", "60")
        try:
            days = int(raw)
        except ValueError:
            days = 60
        return min(180, max(7, days))

    def _redirect_to_current_range(self):
        start = self.request.POST.get("start") or self.request.GET.get("start") or date.today().isoformat()
        days = self.request.POST.get("days") or self.request.GET.get("days") or "60"
        return redirect(f"{self.request.path}?start={start}&days={days}")

    def _redirect_to_search_ficha(self, ficha):
        start = self.request.POST.get("start") or self.request.GET.get("start") or date.today().isoformat()
        days = self.request.POST.get("days") or self.request.GET.get("days") or "60"
        return redirect(f"{reverse_lazy('agendamiento:search')}?start={start}&days={days}&search_ficha={ficha}")

    def _active_resources(self):
        if not ScheduleResource.objects.filter(is_active=True).exists():
            ScheduleResource.objects.get_or_create(
                name="Instructor 1 / Auto 1",
                defaults={
                    "instructor": "Instructor 1",
                    "vehicle": "Auto 1",
                    "sort_order": 1,
                    "is_active": True,
                },
            )
        return list(ScheduleResource.objects.filter(is_active=True).order_by("sort_order", "name"))

    def _get_resource(self, request):
        resource_id = request.POST.get("resource_id") or request.GET.get("resource_id")
        if resource_id:
            resource = ScheduleResource.objects.filter(pk=resource_id, is_active=True).first()
            if resource:
                return resource
        resources = self._active_resources()
        return resources[0] if resources else None

    def _slot_data(self, start_date, day_count, resources):
        end_date = start_date + timedelta(days=day_count - 1)
        resource_ids = [resource.id for resource in resources]
        lessons = {
            (lesson.resource_id, lesson.date, lesson.slot_key): lesson
            for lesson in DrivingLesson.objects.filter(
                date__range=(start_date, end_date),
                resource_id__in=resource_ids,
            )
        }
        resource_filter = Q(resource_id__in=resource_ids) | Q(resource__isnull=True)
        blocks = list(ScheduleBlock.objects.filter(resource_filter, date__range=(start_date, end_date)))
        openings = list(ScheduleOpening.objects.filter(resource_filter, date__range=(start_date, end_date)))
        day_blocks = {
            (block.resource_id, block.date): block for block in blocks if block.scope == ScheduleBlock.Scope.DAY
        }
        slot_blocks = {
            (block.resource_id, block.date, block.slot_key): block
            for block in blocks
            if block.scope == ScheduleBlock.Scope.SLOT
        }
        day_openings = {
            (opening.resource_id, opening.date): opening
            for opening in openings
            if opening.scope == ScheduleOpening.Scope.DAY
        }
        slot_openings = {
            (opening.resource_id, opening.date, opening.slot_key): opening
            for opening in openings
            if opening.scope == ScheduleOpening.Scope.SLOT
        }
        return lessons, day_blocks, slot_blocks, day_openings, slot_openings

    def _is_day_rule_blocked(self, lesson_date):
        return lesson_date.weekday() in {5, 6}

    def _get_day_value(self, mapping, resource_id, lesson_date):
        return mapping.get((resource_id, lesson_date)) or mapping.get((None, lesson_date))

    def _get_slot_value(self, mapping, resource_id, lesson_date, slot_key):
        return mapping.get((resource_id, lesson_date, slot_key)) or mapping.get((None, lesson_date, slot_key))

    def _is_rule_opened(self, lesson_date, slot_key, resource=None, day_openings=None, slot_openings=None):
        if day_openings is None or slot_openings is None:
            return ScheduleOpening.objects.filter(
                date=lesson_date,
                scope=ScheduleOpening.Scope.DAY,
                slot_key="",
                resource=resource,
            ).exists() or ScheduleOpening.objects.filter(
                date=lesson_date,
                scope=ScheduleOpening.Scope.SLOT,
                slot_key=slot_key,
                resource=resource,
            ).exists()
        resource_id = resource.id if resource else None
        return bool(
            self._get_day_value(day_openings, resource_id, lesson_date)
            or self._get_slot_value(slot_openings, resource_id, lesson_date, slot_key)
        )

    def _is_work_rule_blocked(self, lesson_date, slot_key, resource=None, day_openings=None, slot_openings=None):
        if self._is_rule_opened(lesson_date, slot_key, resource, day_openings, slot_openings):
            return False
        if self._is_day_rule_blocked(lesson_date):
            return True
        return lesson_date.weekday() == 4 and slot_key in FRIDAY_WORK_BLOCKED_SLOT_KEYS

    def _is_lesson_auto_completed(self, lesson, current_date, current_time):
        if lesson.status != LessonStatus.SCHEDULED:
            return False
        if lesson.date < current_date:
            return True
        return lesson.date == current_date and lesson.end_time <= current_time

    def _lesson_display_kind(self, lesson, current_date, current_time):
        if lesson.status == LessonStatus.ABSENT:
            return "absent"
        if lesson.status == LessonStatus.SCHOOL_SUSPENDED:
            return "school-suspended"
        if lesson.status == LessonStatus.STUDENT_RESCHEDULED:
            return "student-rescheduled"
        if lesson.status == LessonStatus.COMPLETED or self._is_lesson_auto_completed(
            lesson, current_date, current_time
        ):
            return "completed"
        return "lesson"

    def _search_lessons(self):
        ficha = self.request.GET.get("search_ficha", "").strip()
        lesson_date = self.request.GET.get("search_date", "").strip()
        status = self.request.GET.get("search_status", "").strip()
        has_search = bool(ficha or lesson_date or status)
        if not has_search:
            return [], has_search

        results = DrivingLesson.objects.select_related("ficha_alumno", "resource").order_by("-date", "-start_time")
        if ficha:
            results = results.filter(ficha=ficha)
        if lesson_date:
            try:
                results = results.filter(date=date.fromisoformat(lesson_date))
            except ValueError:
                results = results.none()
        if status in LessonStatus.values:
            results = results.filter(status=status)

        return list(results[:50]), has_search

    def _get_schedule_email_data(self, ficha_raw):
        try:
            ficha = int(ficha_raw)
        except (TypeError, ValueError):
            return None, [], ""

        ficha_alumno = FichaAlumno.objects.filter(numero_ficha=ficha).first()
        lessons = list(
            DrivingLesson.objects.select_related("resource")
            .filter(ficha=ficha, date__gte=timezone.localdate())
            .exclude(status=LessonStatus.ABSENT)
            .exclude(status=LessonStatus.SCHOOL_SUSPENDED)
            .order_by("date", "start_time", "lesson_number")[:30]
        )
        if not lessons:
            return ficha_alumno, lessons, ""

        nombre = ficha_alumno.nombre if ficha_alumno and ficha_alumno.nombre else "alumno"
        lines = [
            f"Hola {nombre},",
            "",
        ]
        instructors = []
        for lesson in lessons:
            instructor = lesson.resource.instructor if lesson.resource and lesson.resource.instructor else ""
            if instructor and instructor not in instructors:
                instructors.append(instructor)
        if len(instructors) == 1:
            lines.extend([f"Instructor: {instructors[0]}", ""])
        elif len(instructors) > 1:
            lines.extend([f"Instructores: {', '.join(instructors)}", ""])

        lines.extend(["Dias y horas agendadas:", ""])
        for lesson in lessons:
            status = "" if lesson.status == LessonStatus.SCHEDULED else f" ({lesson.get_status_display()})"
            lines.append(
                f"Clase {lesson.lesson_number}: {lesson.date.strftime('%d/%m/%Y')} "
                f"a las {lesson.start_time.strftime('%H:%M')}{status}"
            )

        lines.extend(
            [
                "",
                "Ante cualquier duda, contactanos por los canales oficiales. Cualquier cambio debe solicitarse con 48 horas de anticipacion.",
                "",
                "Virval Escuela de Conductores",
            ]
        )
        return ficha_alumno, lessons, "\n".join(lines)

    def _whatsapp_url(self, ficha_alumno, message):
        if not ficha_alumno or not ficha_alumno.telefono or not message:
            return ""
        digits = "".join(char for char in ficha_alumno.telefono if char.isdigit())
        if len(digits) == 9 and digits.startswith("9"):
            digits = f"56{digits}"
        if len(digits) < 10:
            return ""
        return f"https://wa.me/{digits}?text={quote(message)}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date = self._parse_start_date()
        day_count = self._parse_day_count()
        resources = self._active_resources()
        lessons, day_blocks, slot_blocks, day_openings, slot_openings = self._slot_data(
            start_date,
            day_count,
            resources,
        )
        now = timezone.localtime()
        schedules = []
        weekday_names = [
            "LUNES",
            "MARTES",
            "MIERCOLES",
            "JUEVES",
            "VIERNES",
            "SABADO",
            "DOMINGO",
        ]

        for resource in resources:
            rows = []
            for offset in range(day_count):
                current_date = start_date + timedelta(days=offset)
                resource_id = resource.id
                day_block = self._get_day_value(day_blocks, resource_id, current_date)
                day_opening = self._get_day_value(day_openings, resource_id, current_date)
                is_day_rule_blocked = self._is_day_rule_blocked(current_date)
                cells = []
                for slot in SCHEDULE_SLOTS:
                    lesson = lessons.get((resource_id, current_date, slot["key"]))
                    block = self._get_slot_value(slot_blocks, resource_id, current_date, slot["key"])
                    opening = day_opening or self._get_slot_value(
                        slot_openings,
                        resource_id,
                        current_date,
                        slot["key"],
                    )
                    is_work_rule_blocked = self._is_work_rule_blocked(
                        current_date,
                        slot["key"],
                        resource,
                        day_openings,
                        slot_openings,
                    )
                    visible_lesson = None if is_work_rule_blocked else lesson
                    cells.append(
                        {
                            "slot": slot,
                            "lesson": visible_lesson,
                            "block": block,
                            "opening": opening,
                            "work_rule_blocked": is_work_rule_blocked,
                            "kind": (
                                "blocked"
                                if is_work_rule_blocked
                                else self._lesson_display_kind(visible_lesson, now.date(), now.time())
                                if visible_lesson
                                else "blocked"
                                if block
                                else "open"
                            ),
                        }
                    )

                rows.append(
                    {
                        "date": current_date,
                        "label": current_date.strftime("%d/%b").lower(),
                        "weekday": weekday_names[current_date.weekday()],
                        "is_saturday": current_date.weekday() == 5,
                        "is_sunday": current_date.weekday() == 6,
                        "is_day_rule_blocked": is_day_rule_blocked,
                        "day_block": day_block,
                        "day_opening": day_opening,
                        "cells": cells,
                    }
                )
            schedules.append({"resource": resource, "rows": rows})

        context.update(
            {
                "slots": SCHEDULE_SLOTS,
                "schedules": schedules,
                "start_date": start_date,
                "day_count": day_count,
                "course_choices": CourseKind.choices,
                "status_choices": LessonStatus.choices,
                "day_options": [30, 60, 90, 120, 180],
                "fichas": FichaAlumno.objects.order_by("-numero_ficha")[:500],
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "save_lesson":
            return self._save_lesson(request)
        if action == "delete_lesson":
            return self._delete_lesson(request)
        if action == "block_slot":
            return self._block_slot(request)
        if action == "block_day":
            return self._block_day(request)
        if action == "unblock":
            return self._unblock(request)
        if action == "update_comment":
            return self._update_comment(request)
        if action == "send_schedule_email":
            return self._send_schedule_email(request)

        messages.error(request, "Accion de agendamiento no reconocida.")
        return self._redirect_to_current_range()

    def _get_slot(self, request):
        slot_key = request.POST.get("slot_key", "")
        return slot_key, SLOT_BY_KEY.get(slot_key)

    def _save_lesson(self, request):
        resource = self._get_resource(request)
        if resource is None:
            messages.error(request, "No hay instructor/auto activo para agendar.")
            return self._redirect_to_current_range()

        slot_key, slot = self._get_slot(request)
        if slot is None:
            messages.error(request, "Horario no valido.")
            return self._redirect_to_current_range()

        try:
            lesson_date = date.fromisoformat(request.POST.get("date", ""))
            lesson_number = int(request.POST.get("lesson_number", ""))
        except (TypeError, ValueError):
            messages.error(request, "Ingresa fecha y numero de clase validos.")
            return self._redirect_to_current_range()

        ficha_alumno = None
        ficha_alumno_id = request.POST.get("ficha_alumno")
        if ficha_alumno_id:
            ficha_alumno = FichaAlumno.objects.filter(pk=ficha_alumno_id).first()
            if ficha_alumno is None:
                messages.error(request, "La ficha seleccionada no existe.")
                return self._redirect_to_current_range()
            ficha = ficha_alumno.numero_ficha
        else:
            try:
                ficha = int(request.POST.get("ficha", ""))
            except (TypeError, ValueError):
                messages.error(request, "Ingresa una ficha valida.")
                return self._redirect_to_current_range()

        if ficha <= 0 or lesson_number <= 0:
            messages.error(request, "Ficha y clase deben ser mayores a cero.")
            return self._redirect_to_current_range()

        resource_filter = Q(resource=resource) | Q(resource__isnull=True)
        if ScheduleBlock.objects.filter(resource_filter, date=lesson_date, scope=ScheduleBlock.Scope.DAY).exists():
            messages.error(request, "El dia completo esta bloqueado.")
            return self._redirect_to_current_range()

        if ScheduleBlock.objects.filter(
            resource_filter,
            date=lesson_date,
            scope=ScheduleBlock.Scope.SLOT,
            slot_key=slot_key,
        ).exists():
            messages.error(request, "Ese horario esta bloqueado.")
            return self._redirect_to_current_range()

        if self._is_work_rule_blocked(lesson_date, slot_key, resource):
            messages.error(request, "Ese horario esta bloqueado por regla de agenda.")
            return self._redirect_to_current_range()

        status = request.POST.get("status") or LessonStatus.SCHEDULED
        if status not in LessonStatus.values:
            status = LessonStatus.SCHEDULED

        with transaction.atomic():
            DrivingLesson.objects.update_or_create(
                resource=resource,
                date=lesson_date,
                slot_key=slot_key,
                defaults={
                    "start_time": slot["start"],
                    "end_time": slot["end"],
                    "ficha_alumno": ficha_alumno,
                    "ficha": ficha,
                    "lesson_number": lesson_number,
                    "course_kind": request.POST.get("course_kind") or CourseKind.DOCE_MODULOS,
                    "status": status,
                    "is_completed": status == LessonStatus.COMPLETED,
                    "notes": request.POST.get("notes", "")[:240],
                    "created_by": request.user,
                },
            )

        messages.success(request, f"Clase {ficha}/{lesson_number} guardada.")
        return self._redirect_to_current_range()

    def _delete_lesson(self, request):
        resource = self._get_resource(request)
        DrivingLesson.objects.filter(
            resource=resource,
            date=request.POST.get("date"),
            slot_key=request.POST.get("slot_key"),
        ).delete()
        messages.success(request, "Clase liberada.")
        return self._redirect_to_current_range()

    def _block_slot(self, request):
        resource = self._get_resource(request)
        if resource is None:
            messages.error(request, "No hay instructor/auto activo para bloquear.")
            return self._redirect_to_current_range()

        slot_key, slot = self._get_slot(request)
        if slot is None:
            messages.error(request, "Horario no valido.")
            return self._redirect_to_current_range()
        try:
            block_date = date.fromisoformat(request.POST.get("date", ""))
        except ValueError:
            messages.error(request, "Fecha no valida.")
            return self._redirect_to_current_range()

        if self._is_work_rule_blocked(block_date, slot_key, resource):
            messages.info(request, "Ese horario ya esta bloqueado por regla de agenda.")
            return self._redirect_to_current_range()

        DrivingLesson.objects.filter(resource=resource, date=block_date, slot_key=slot_key).delete()
        ScheduleOpening.objects.filter(
            resource=resource,
            date=block_date,
            scope=ScheduleOpening.Scope.SLOT,
            slot_key=slot_key,
        ).delete()
        try:
            ScheduleBlock.objects.create(
                resource=resource,
                date=block_date,
                scope=ScheduleBlock.Scope.SLOT,
                slot_key=slot_key,
                reason=request.POST.get("reason", "")[:160],
                created_by=request.user,
            )
            messages.success(request, "Horario bloqueado.")
        except IntegrityError:
            messages.info(request, "Ese horario ya estaba bloqueado.")
        return self._redirect_to_current_range()

    def _block_day(self, request):
        resource = self._get_resource(request)
        if resource is None:
            messages.error(request, "No hay instructor/auto activo para bloquear.")
            return self._redirect_to_current_range()

        try:
            block_date = date.fromisoformat(request.POST.get("date", ""))
        except ValueError:
            messages.error(request, "Fecha no valida.")
            return self._redirect_to_current_range()

        DrivingLesson.objects.filter(resource=resource, date=block_date).delete()
        ScheduleOpening.objects.filter(resource=resource, date=block_date).delete()
        ScheduleBlock.objects.get_or_create(
            resource=resource,
            date=block_date,
            scope=ScheduleBlock.Scope.DAY,
            slot_key="",
            defaults={
                "reason": request.POST.get("reason", "")[:160],
                "created_by": request.user,
            },
        )
        messages.success(request, "Dia bloqueado.")
        return self._redirect_to_current_range()

    def _unblock(self, request):
        resource = self._get_resource(request)
        if resource is None:
            messages.error(request, "No hay instructor/auto activo para quitar bloqueo.")
            return self._redirect_to_current_range()

        slot_key = request.POST.get("slot_key", "")
        raw_date = request.POST.get("date")
        ScheduleBlock.objects.filter(resource=resource, date=raw_date, slot_key=slot_key).delete()

        try:
            opening_date = date.fromisoformat(raw_date or "")
        except ValueError:
            messages.error(request, "Fecha no valida.")
            return self._redirect_to_current_range()

        if slot_key and self._is_day_rule_blocked(opening_date):
            ScheduleOpening.objects.get_or_create(
                resource=resource,
                date=opening_date,
                scope=ScheduleOpening.Scope.SLOT,
                slot_key=slot_key,
                defaults={
                    "reason": request.POST.get("notes", "")[:160],
                    "created_by": request.user,
                },
            )
        elif slot_key and self._is_work_rule_blocked(opening_date, slot_key, resource):
            messages.info(request, "Ese bloqueo de jornada laboral se mantiene por regla de agenda.")
            return self._redirect_to_current_range()
        elif not slot_key and self._is_day_rule_blocked(opening_date):
            ScheduleOpening.objects.get_or_create(
                resource=resource,
                date=opening_date,
                scope=ScheduleOpening.Scope.DAY,
                slot_key="",
                defaults={
                    "reason": request.POST.get("reason", "")[:160],
                    "created_by": request.user,
                },
            )

        messages.success(request, "Bloqueo eliminado.")
        return self._redirect_to_current_range()

    def _update_comment(self, request):
        resource = self._get_resource(request)
        updated = DrivingLesson.objects.filter(
            resource=resource,
            date=request.POST.get("date"),
            slot_key=request.POST.get("slot_key"),
        ).update(notes=request.POST.get("notes", "")[:240])
        if updated:
            messages.success(request, "Comentario actualizado.")
        else:
            messages.info(request, "No hay clase para actualizar comentario.")
        return self._redirect_to_current_range()

    def _send_schedule_email(self, request):
        ficha_raw = request.POST.get("ficha", "").strip()
        ficha_alumno, lessons, body = self._get_schedule_email_data(ficha_raw)
        if ficha_alumno is None:
            messages.error(request, "No existe ficha de alumno para enviar correo.")
            return self._redirect_to_search_ficha(ficha_raw)
        if not ficha_alumno.correo:
            messages.error(request, "La ficha no tiene correo registrado.")
            return self._redirect_to_search_ficha(ficha_raw)
        if not lessons:
            messages.error(request, "No hay clases futuras para informar.")
            return self._redirect_to_search_ficha(ficha_raw)
        body = (request.POST.get("schedule_email_body") or body).strip()
        if not body:
            messages.error(request, "El mensaje del correo no puede estar vacio.")
            return self._redirect_to_search_ficha(ficha_raw)

        send_mail(
            "Tus clases practicas agendadas - Virval",
            body,
            settings.DEFAULT_FROM_EMAIL,
            [ficha_alumno.correo],
            fail_silently=False,
        )
        messages.success(request, f"Correo enviado a {ficha_alumno.correo}.")
        return self._redirect_to_search_ficha(ficha_raw)


class ScheduleMinimalGridView(ScheduleGridView):
    def _parse_day_count(self):
        return 15

    def _redirect_to_current_range(self):
        start = self.request.POST.get("start") or self.request.GET.get("start") or date.today().isoformat()
        return redirect(f"{self.request.path}?start={start}&days=15")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_minimal_view"] = True
        context["day_options"] = [15]
        return context


class ScheduleSearchView(ScheduleGridView):
    template_name = "agendamiento/schedule_search.html"

    def get_context_data(self, **kwargs):
        context = TemplateView.get_context_data(self, **kwargs)
        start_date = self._parse_start_date()
        day_count = self._parse_day_count()
        search_results, has_search = self._search_lessons()
        search_ficha = self.request.GET.get("search_ficha", "").strip()
        schedule_email_student = None
        schedule_email_lessons = []
        schedule_email_preview = ""
        schedule_whatsapp_url = ""
        if search_ficha:
            schedule_email_student, schedule_email_lessons, schedule_email_preview = self._get_schedule_email_data(
                search_ficha
            )
            schedule_whatsapp_url = self._whatsapp_url(schedule_email_student, schedule_email_preview)

        context.update(
            {
                "start_date": start_date,
                "day_count": day_count,
                "status_choices": LessonStatus.choices,
                "day_options": [30, 60, 90, 120, 180],
                "search_ficha": search_ficha,
                "search_date": self.request.GET.get("search_date", "").strip(),
                "search_status": self.request.GET.get("search_status", "").strip(),
                "search_results": search_results,
                "has_search": has_search,
                "schedule_email_student": schedule_email_student,
                "schedule_email_lessons": schedule_email_lessons,
                "schedule_email_preview": schedule_email_preview,
                "schedule_whatsapp_url": schedule_whatsapp_url,
                "schedule_email_can_send": bool(
                    schedule_email_student
                    and schedule_email_student.correo
                    and schedule_email_lessons
                    and schedule_email_preview
                ),
            }
        )
        return context


class ScheduleResourceManageView(LoginRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "agendamiento/resources_manage.html"
    login_url = reverse_lazy("login")
    redirect_field_name = "next"

    @method_decorator(never_cache)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        editing_resource = kwargs.get("editing_resource")
        form = kwargs.get("form")
        edit_id = self.request.GET.get("edit")
        if editing_resource is None and edit_id:
            editing_resource = ScheduleResource.objects.filter(pk=edit_id).first()
        if form is None:
            form = ScheduleResourceForm(instance=editing_resource)
        context.update(
            {
                "form": form,
                "editing_resource": editing_resource,
                "resources": ScheduleResource.objects.order_by("sort_order", "name"),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        resource = None
        if action in {"edit", "toggle"}:
            resource = ScheduleResource.objects.filter(pk=request.POST.get("resource_id")).first()
            if resource is None:
                messages.error(request, "El instructor/auto no existe.")
                return redirect("agendamiento:resources")

        if action == "toggle":
            resource.is_active = not resource.is_active
            resource.save(update_fields=["is_active"])
            messages.success(request, "Estado del recurso actualizado.")
            return redirect("agendamiento:resources")

        form = ScheduleResourceForm(request.POST, instance=resource)
        if not form.is_valid():
            messages.error(request, "Revisa los datos del instructor/auto.")
            return self.render_to_response(
                self.get_context_data(form=form, editing_resource=resource)
            )

        saved = form.save()
        messages.success(request, f"Recurso {saved.name} guardado.")
        return redirect("agendamiento:resources")
