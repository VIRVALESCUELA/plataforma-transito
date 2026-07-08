import csv
from datetime import timedelta
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.conf import settings
from django.db import DatabaseError
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import DetailView, FormView, ListView, TemplateView, View
from urllib.parse import quote
import secrets
import unicodedata

from .forms import (
    ActivationCodeForm,
    FichaAlumnoForm,
    FichaMovimientoForm,
    InscripcionForm,
    StudentSignupForm,
)
from .models import (
    ActivationCode,
    ExamAttempt,
    ExamAttemptStatus,
    ExamTemplate,
    FichaAlumno,
    FichaMovimiento,
    Inscripcion,
    PageVisitCounter,
    Profile,
    Topic,
    UserRole,
)
from .services import (
    activate_code_for_user,
    check_and_expire_attempt,
    generate_exam_attempt,
    get_remaining_seconds,
    get_student_exam_progress,
    grade_attempt,
    grade_single_answer,
    repeat_exam_attempt,
    send_activation_code_email,
    send_inscripcion_notification_email,
    user_has_active_exam_access,
)

User = get_user_model()

TOPIC_MATERIALS = {
    "siniestros de transito": [
        {"label": "Capitulo 1", "path": "core/materiales/capitulo-1.pdf"}
    ],
    "los principios de la conduccion": [
        {"label": "Capitulo 2", "path": "core/materiales/capitulo-2.pdf"}
    ],
    "convivencia vial": [
        {"label": "Capitulo 3", "path": "core/materiales/capitulo-3.pdf"}
    ],
    "la persona en el transito": [
        {"label": "Capitulo 4", "path": "core/materiales/capitulo-4.pdf"}
    ],
    "la y los usuarios vulnerables": [
        {"label": "Capitulo 5", "path": "core/materiales/capitulo-5.pdf"}
    ],
    "las y los usuarios vulnerables": [
        {"label": "Capitulo 5", "path": "core/materiales/capitulo-5.pdf"}
    ],
    "normas de circulacion": [
        {"label": "Capitulo 6", "path": "core/materiales/capitulo-6.pdf"}
    ],
    "conduccion en circunstancias especiales": [
        {"label": "Capitulo 7", "path": "core/materiales/capitulo-7.pdf"}
    ],
    "conduccion eficiente": [
        {"label": "Capitulo 8", "path": "core/materiales/capitulo-8.pdf"}
    ],
    "informaciones importantes": [
        {"label": "Capitulo 9", "path": "core/materiales/capitulo-9.pdf"}
    ],
    "anexo-definiciones": [
        {"label": "Glosario", "path": "core/materiales/glosario.pdf"},
        {"label": "Senales", "path": "core/materiales/senales.pdf"},
        {
            "label": "Disposiciones",
            "path": "core/materiales/disposiciones-vehículos.pdf",
        },
    ],
    "anexo definiciones": [
        {"label": "Glosario", "path": "core/materiales/glosario.pdf"},
        {"label": "Senales", "path": "core/materiales/senales.pdf"},
        {
            "label": "Disposiciones",
            "path": "core/materiales/disposiciones-vehículos.pdf",
        },
    ],
}


def _normalize_topic_name(name):
    decomposed = unicodedata.normalize("NFKD", name or "")
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_accents.casefold().split())


def add_material_paths_to_exam_progress(exam_progress):
    if not exam_progress:
        return exam_progress

    topic_ids_by_name = {
        _normalize_topic_name(topic.name): topic.id for topic in Topic.objects.all()
    }
    for topic in exam_progress.get("topics", []):
        normalized_name = _normalize_topic_name(topic.get("topic", ""))
        topic["topic_id"] = topic_ids_by_name.get(normalized_name)
        topic["materials"] = TOPIC_MATERIALS.get(
            normalized_name
        ) or []
    return exam_progress


def add_history_summary_to_attempts(attempts):
    def _format_attempt_duration(attempt):
        if not attempt.started_at or not attempt.finished_at:
            return "En curso" if attempt.status == ExamAttemptStatus.EN_CURSO else "--"
        seconds = int((attempt.finished_at - attempt.started_at).total_seconds())
        if seconds <= 0:
            return "--"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min"
        hours, remaining_minutes = divmod(minutes, 60)
        return f"{hours}h {remaining_minutes}m"

    total_attempts = len(attempts)
    for index, attempt in enumerate(attempts, start=1):
        topics = []
        seen_topics = set()
        for exam_question in attempt.exam_questions.all():
            topic = (exam_question.topic or "Sin tema").strip() or "Sin tema"
            if topic not in seen_topics:
                seen_topics.add(topic)
                topics.append(topic)

        attempt.exam_number = total_attempts - index + 1
        attempt.question_count = attempt.exam_questions.count()
        attempt.duration_label = _format_attempt_duration(attempt)
        attempt.topic_count = len(topics)
        attempt.topic_summary = topics[0] if len(topics) == 1 else "Todos los temas"
        attempt.topic_detail = ", ".join(topics[:3])
        if len(topics) > 3:
            attempt.topic_detail = f"{attempt.topic_detail} y {len(topics) - 3} mas"
        attempt.is_approved = (
            attempt.status == ExamAttemptStatus.ENTREGADO
            and attempt.score is not None
            and attempt.score >= 85
        )
        attempt.is_failed = (
            attempt.status == ExamAttemptStatus.ENTREGADO
            and attempt.score is not None
            and attempt.score < 85
        )
    return attempts


class StudentSignupView(FormView):
    template_name = "registration/signup.html"
    form_class = StudentSignupForm
    success_url = reverse_lazy("core_web:dashboard")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        if form.cleaned_data.get("activation_instance"):
            messages.success(
                self.request,
                "Registro exitoso. Tu cuenta quedo enlazada y el curso fue activado.",
            )
        elif getattr(form, "linked_inscripcion", None):
            messages.success(
                self.request,
                "Registro exitoso. Tu cuenta quedo enlazada a tu inscripcion.",
            )
        else:
            messages.success(
                self.request,
                "Registro exitoso. Ahora ingresa tu codigo de activacion desde el panel para habilitar los examenes.",
            )
        return super().form_valid(form)

class InscripcionCreateView(FormView):
    template_name = "core/inscripcion_form.html"
    form_class = InscripcionForm
    success_url = reverse_lazy("core_web:inscripcion")
    duplicate_window = timedelta(minutes=10)

    def get_initial(self):
        initial = super().get_initial()
        curso = self.request.GET.get("curso")
        if curso:
            initial["curso"] = curso
        return initial

    def _get_recent_duplicate(self, form):
        data = form.cleaned_data
        threshold = timezone.now() - self.duplicate_window
        return (
            Inscripcion.objects.filter(
                nombre__iexact=data["nombre"].strip(),
                comuna__iexact=data["comuna"].strip(),
                direccion__iexact=(data.get("direccion") or "").strip(),
                correo__iexact=data["correo"].strip(),
                telefono=data["telefono"].strip(),
                curso=data.get("curso") or "",
                created_at__gte=threshold,
            )
            .order_by("-created_at")
            .first()
        )

    def form_valid(self, form):
        # Aseguramos persistencia antes de redirigir a WhatsApp.
        with transaction.atomic():
            inscripcion = self._get_recent_duplicate(form)
            created = inscripcion is None
            if created:
                inscripcion = form.save()
        if created:
            send_inscripcion_notification_email(inscripcion)
        messages.success(self.request, "Hemos recibido tu solicitud. Te contactaremos pronto.")

        # Numero fijo para recibir la inscripcion por WhatsApp
        whatsapp_number = "56992734999"
        curso = inscripcion.curso or "No especificado"
        message = (
            "Nueva inscripcion de curso:\n"
            f"Nombre: {inscripcion.nombre}\n"
            f"Comuna: {inscripcion.comuna}\n"
            f"Direccion: {inscripcion.direccion or 'No especificada'}\n"
            f"Correo: {inscripcion.correo}\n"
            f"Telefono: {inscripcion.telefono}\n"
            f"Curso: {curso}"
        )
        whatsapp_url = f"https://wa.me/{whatsapp_number}?text={quote(message)}"
        return redirect(whatsapp_url)

    def form_invalid(self, form):
        messages.error(self.request, "Revisa los datos ingresados e intenta nuevamente.")
        return super().form_invalid(form)

class LandingView(TemplateView):
    template_name = "core/home.html"

class StudentsLandingView(TemplateView):
    template_name = "core/alumnos.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            counter, _ = PageVisitCounter.objects.get_or_create(page="alumnos")
            PageVisitCounter.objects.filter(pk=counter.pk).update(total=F("total") + 1)
            counter.refresh_from_db(fields=["total"])
            context["visit_count"] = counter.total
        except DatabaseError:
            context["visit_count"] = None
        return context

class BlogView(TemplateView):
    template_name = "core/blog.html"


class PrivateAreaMixin(LoginRequiredMixin):
    """
    Forces authentication for student-only screens and disables caching
    so logged-out sessions don't keep showing stale content.
    """

    login_url = reverse_lazy("login")
    redirect_field_name = "next"

    @method_decorator(never_cache)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return bool(self.request.user and self.request.user.is_staff)

    def handle_no_permission(self):
        messages.error(self.request, "No tienes permisos para acceder a esta seccion.")
        return redirect("core_web:dashboard")


class SuperuserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return bool(self.request.user and self.request.user.is_superuser)

    def handle_no_permission(self):
        messages.error(self.request, "Solo el administrador dueno puede acceder a exportaciones.")
        return redirect("core_web:dashboard")


def _format_export_value(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _csv_bytes(headers, rows):
    output = StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_format_export_value(value) for value in row])
    return output.getvalue().encode("utf-8")


def _zip_response(filename, files):
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for file_name, content in files:
            zip_file.writestr(file_name, content)
    response = HttpResponse(archive.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class PublicLogoutView(View):
    """
    Custom logout that always sends users back to the public landing page.
    """

    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        logout(request)
        messages.info(request, "Sesion finalizada.")
        response = redirect("core_web:landing")
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response


class InscripcionManagementView(PrivateAreaMixin, StaffRequiredMixin, TemplateView):
    template_name = "core/inscripciones_manage.html"

    def _build_code(self, prefix="CLASEB"):
        prefix = prefix.strip().upper().replace(" ", "")
        while True:
            code = f"{prefix}-{secrets.token_hex(3).upper()}"
            if not ActivationCode.objects.filter(code=code).exists():
                return code

    def _get_inscripcion_user(self, inscripcion):
        if inscripcion.user_id:
            return inscripcion.user

        email = (inscripcion.correo or "").strip()
        if not email:
            return None

        return (
            User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
            .order_by("id")
            .first()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        context["summary_cards"] = [
            {
                "label": "Solicitudes de inscripcion",
                "value": Inscripcion.objects.count(),
                "tone": "background: #e8f5e9; color: #1b5e20;",
            },
            {
                "label": "Registros en plataforma",
                "value": Profile.objects.filter(role="ALUMNO").count(),
                "tone": "background: #e3f2fd; color: #0d47a1;",
            },
            {
                "label": "Accesos activos",
                "value": Profile.objects.filter(
                    role="ALUMNO",
                    access_expires_at__isnull=False,
                    access_expires_at__gte=now,
                ).count(),
                "tone": "background: #fff3cd; color: #8a6d3b;",
            },
            {
                "label": "Codigos disponibles",
                "value": ActivationCode.objects.filter(
                    is_enabled=True,
                    used_by__isnull=True,
                    course_name="Clase B",
                ).count(),
                "tone": "background: #fce4ec; color: #ad1457;",
            },
        ]
        context["inscripciones"] = (
            Inscripcion.objects.select_related("activation_code", "user", "ficha_alumno")
            .order_by("-created_at")
        )
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        inscripcion = get_object_or_404(Inscripcion, pk=request.POST.get("inscripcion_id"))

        if action == "generate_code":
            if inscripcion.activation_code_id is None:
                activation = ActivationCode.objects.create(
                    code=self._build_code(),
                    course_name="Clase B",
                    duration_days=30,
                    is_enabled=True,
                )
                inscripcion.activation_code = activation
                if inscripcion.status == Inscripcion.Status.PENDIENTE:
                    inscripcion.status = Inscripcion.Status.CONTACTADO
                inscripcion.save(update_fields=["activation_code", "status"])
                activation_url = request.build_absolute_uri(
                    reverse("core_web:alumnos")
                )
                email_sent = send_activation_code_email(
                    inscripcion,
                    activation,
                    activation_url=activation_url,
                )
                messages.success(
                    request,
                    f"Codigo {activation.code} generado para {inscripcion.nombre}.",
                )
                if email_sent:
                    messages.success(
                        request,
                        f"Correo enviado a {inscripcion.correo}.",
                    )
                else:
                    messages.warning(
                        request,
                        "El codigo fue generado, pero no se pudo enviar el correo automaticamente.",
                    )
            else:
                messages.info(
                    request,
                    f"Esta inscripcion ya tiene el codigo {inscripcion.activation_code.code}.",
                )
            return redirect("core_web:manage-inscripciones")

        if action == "add_30_days":
            student = self._get_inscripcion_user(inscripcion)
            if student is None:
                messages.error(
                    request,
                    "No existe una cuenta de alumno con el correo de esta inscripcion.",
                )
                return redirect("core_web:manage-inscripciones")

            activation = inscripcion.activation_code
            if (
                activation is None
                or activation.used_by_id is not None
                or not activation.is_enabled
            ):
                activation = ActivationCode.objects.create(
                    code=self._build_code(),
                    course_name="Clase B",
                    duration_days=30,
                    is_enabled=True,
                )

            activation, profile = activate_code_for_user(student, activation)
            messages.success(
                request,
                (
                    f"Se agregaron {activation.duration_days} dias a {student.email or student.username}. "
                    f"Nuevo vencimiento: {timezone.localtime(profile.access_expires_at).strftime('%d/%m/%Y')}."
                ),
            )
            return redirect("core_web:manage-inscripciones")

        if action == "update_status":
            new_status = request.POST.get("status")
            if new_status not in Inscripcion.Status.values:
                messages.error(request, "Estado de inscripcion no valido.")
            else:
                inscripcion.status = new_status
                inscripcion.save(update_fields=["status"])
                messages.success(
                    request,
                    f"Estado actualizado a {inscripcion.get_status_display()} para {inscripcion.nombre}.",
                )
            return redirect("core_web:manage-inscripciones")

        messages.error(request, "Accion no reconocida.")
        return redirect("core_web:manage-inscripciones")


class FreeActivationCodeView(PrivateAreaMixin, StaffRequiredMixin, TemplateView):
    template_name = "core/free_activation_codes.html"

    def _build_code(self, prefix="LIBRE"):
        prefix = prefix.strip().upper().replace(" ", "") or "LIBRE"
        while True:
            code = f"{prefix}-{secrets.token_hex(3).upper()}"
            if not ActivationCode.objects.filter(code=code).exists():
                return code

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        free_codes = (
            ActivationCode.objects.filter(inscripcion__isnull=True)
            .select_related("used_by")
            .order_by("-created_at")
        )
        context["available_codes_count"] = free_codes.filter(
            is_enabled=True,
            used_by__isnull=True,
            course_name="Clase B",
        ).count()
        context["free_codes"] = free_codes[:200]
        context["generated_codes"] = kwargs.get("generated_codes", [])
        context["form_values"] = kwargs.get(
            "form_values",
            {
                "count": 10,
                "days": 30,
                "prefix": "LIBRE",
                "course_name": "Clase B",
                "recipient_email": "",
            },
        )
        return context

    def _send_codes_email(self, recipient_email, generated_codes):
        first_code = generated_codes[0]
        subject = f"Codigos de acceso Virval - {first_code.course_name or 'Curso'}"
        codes_text = "\n".join(activation.code for activation in generated_codes)
        message = (
            "Hola,\n\n"
            "Te enviamos los codigos de activacion solicitados para acceso a la plataforma Virval.\n\n"
            f"Curso: {first_code.course_name or 'General'}\n"
            f"Duracion por codigo: {first_code.duration_days} dias\n\n"
            "Codigos:\n"
            f"{codes_text}\n\n"
            "Cada codigo puede usarse una sola vez. Si la cuenta ya tiene acceso activo, "
            "los dias se suman a su fecha actual de vencimiento.\n\n"
            "Saludos,\n"
            "Escuela Virval\n"
        )
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient_email],
            fail_silently=False,
        )

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "generate")
        if action == "delete_code":
            activation = get_object_or_404(
                ActivationCode,
                pk=request.POST.get("activation_id"),
                inscripcion__isnull=True,
            )
            if activation.used_by_id or activation.used_at:
                messages.error(request, "No se puede eliminar un codigo que ya fue usado.")
            else:
                code = activation.code
                activation.delete()
                messages.success(request, f"Codigo {code} eliminado.")
            return redirect("core_web:free-activation-codes")

        try:
            count = int(request.POST.get("count", 10))
            days = int(request.POST.get("days", 30))
        except ValueError:
            messages.error(request, "La cantidad y los dias deben ser numeros validos.")
            return self.render_to_response(self.get_context_data())

        prefix = (request.POST.get("prefix") or "LIBRE").strip().upper().replace(" ", "")
        course_name = (request.POST.get("course_name") or "Clase B").strip()
        recipient_email = (request.POST.get("recipient_email") or "").strip().lower()
        form_values = {
            "count": count,
            "days": days,
            "prefix": prefix or "LIBRE",
            "course_name": course_name,
            "recipient_email": recipient_email,
        }

        if count < 1 or count > 100:
            messages.error(request, "Puedes generar entre 1 y 100 codigos por vez.")
            return self.render_to_response(self.get_context_data(form_values=form_values))
        if days < 1 or days > 365:
            messages.error(request, "Los dias deben estar entre 1 y 365.")
            return self.render_to_response(self.get_context_data(form_values=form_values))
        if recipient_email:
            try:
                validate_email(recipient_email)
            except ValidationError:
                messages.error(request, "Ingresa un correo valido para enviar el lote.")
                return self.render_to_response(self.get_context_data(form_values=form_values))

        generated_codes = []
        with transaction.atomic():
            for _index in range(count):
                activation = ActivationCode.objects.create(
                    code=self._build_code(prefix),
                    course_name=course_name,
                    duration_days=days,
                    is_enabled=True,
                    sent_to_email=recipient_email,
                )
                generated_codes.append(activation)

        messages.success(request, f"Se generaron {len(generated_codes)} codigos libres.")
        if recipient_email:
            if settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
                messages.warning(
                    request,
                    "Los codigos fueron creados, pero el correo esta en modo consola y no se envia a Gmail.",
                )
            else:
                try:
                    self._send_codes_email(recipient_email, generated_codes)
                    messages.success(request, f"Lote enviado a {recipient_email}.")
                except Exception:
                    messages.warning(
                        request,
                        "Los codigos fueron creados, pero no se pudo enviar el correo automaticamente.",
                    )
        return self.render_to_response(
            self.get_context_data(
                generated_codes=generated_codes,
                form_values=form_values,
            )
        )


class StaffInternalManagementView(PrivateAreaMixin, StaffRequiredMixin, TemplateView):
    template_name = "core/staff_internal_management.html"


class ExportCenterView(PrivateAreaMixin, SuperuserRequiredMixin, TemplateView):
    template_name = "core/export_center.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fichas_count"] = FichaAlumno.objects.count()
        context["inscripciones_count"] = Inscripcion.objects.count()
        context["students_count"] = Profile.objects.filter(role=UserRole.ALUMNO).count()
        try:
            from odo.models import Vehicle

            context["odo_vehicles_count"] = Vehicle.objects.count()
        except Exception:
            context["odo_vehicles_count"] = None
        return context


class ExportDownloadView(PrivateAreaMixin, SuperuserRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        export_kind = kwargs.get("kind")
        if export_kind == "fichas":
            return self._export_fichas()
        if export_kind == "gestion":
            return self._export_gestion()
        if export_kind == "odo":
            return self._export_odo()
        if export_kind == "balance":
            return self._export_balance()
        messages.error(request, "Exportacion no disponible.")
        return redirect("core_web:export-center")

    def _export_year(self):
        current_year = timezone.localdate().year
        try:
            year = int(self.request.GET.get("anio", current_year))
        except (TypeError, ValueError):
            year = current_year
        return max(2013, min(year, current_year + 1))

    def _export_fichas(self):
        fichas = (
            FichaAlumno.objects.select_related("inscripcion", "user")
            .annotate(
                total_movimientos=Sum("movimientos__monto"),
                cantidad_movimientos=Count("movimientos", distinct=True),
            )
            .order_by("numero_ficha")
        )
        fichas_csv = _csv_bytes(
            [
                "id",
                "numero_ficha",
                "fecha_inscripcion",
                "nombre",
                "correo",
                "telefono",
                "direccion",
                "curso",
                "clases_contratadas",
                "clases_extra_vendidas",
                "cupo_clases_practicas",
                "rut",
                "fecha_nacimiento",
                "edad",
                "valor_pagado_inicial",
                "forma_pago_inicial",
                "total_movimientos",
                "cantidad_movimientos",
                "inscripcion_id",
                "user_id",
                "observaciones",
                "created_at",
                "updated_at",
            ],
            (
                [
                    ficha.id,
                    ficha.numero_ficha,
                    ficha.fecha_inscripcion,
                    ficha.nombre,
                    ficha.correo,
                    ficha.telefono,
                    ficha.direccion,
                    ficha.curso,
                    ficha.clases_contratadas,
                    ficha.clases_extra_vendidas,
                    ficha.cupo_clases_practicas,
                    ficha.rut,
                    ficha.fecha_nacimiento,
                    ficha.edad,
                    ficha.valor_pagado,
                    ficha.get_forma_pago_display() if ficha.forma_pago else "",
                    ficha.total_movimientos if ficha.total_movimientos is not None else ficha.valor_pagado,
                    ficha.cantidad_movimientos,
                    ficha.inscripcion_id,
                    ficha.user_id,
                    ficha.observaciones,
                    ficha.created_at,
                    ficha.updated_at,
                ]
                for ficha in fichas
            ),
        )
        movimientos = FichaMovimiento.objects.select_related("ficha").order_by(
            "ficha__numero_ficha", "fecha", "id"
        )
        movimientos_csv = _csv_bytes(
            [
                "id",
                "ficha_id",
                "numero_ficha",
                "fecha",
                "tipo",
                "concepto",
                "monto",
                "es_inicial",
                "forma_pago",
                "observaciones",
                "created_at",
                "updated_at",
            ],
            (
                [
                    movimiento.id,
                    movimiento.ficha_id,
                    movimiento.ficha.numero_ficha,
                    movimiento.fecha,
                    movimiento.get_tipo_display(),
                    movimiento.concepto,
                    movimiento.monto,
                    movimiento.es_inicial,
                    movimiento.get_forma_pago_display() if movimiento.forma_pago else "",
                    movimiento.observaciones,
                    movimiento.created_at,
                    movimiento.updated_at,
                ]
                for movimiento in movimientos
            ),
        )
        return _zip_response(
            "exportacion_fichas.zip",
            [
                ("fichas.csv", fichas_csv),
                ("movimientos_fichas.csv", movimientos_csv),
            ],
        )

    def _export_gestion(self):
        attempts = (
            ExamAttempt.objects.select_related("student", "template")
            .order_by("student__username", "-started_at")
        )
        profiles = (
            Profile.objects.select_related("user")
            .filter(role=UserRole.ALUMNO)
            .annotate(
                attempt_count=Count("user__examattempt", distinct=True),
                delivered_count=Count(
                    "user__examattempt",
                    filter=Q(user__examattempt__status=ExamAttemptStatus.ENTREGADO),
                    distinct=True,
                ),
                average_score=Avg(
                    "user__examattempt__score",
                    filter=Q(user__examattempt__status=ExamAttemptStatus.ENTREGADO),
                ),
            )
            .order_by("user__username")
        )
        alumnos_csv = _csv_bytes(
            [
                "user_id",
                "username",
                "email",
                "nombre",
                "apellido",
                "rol",
                "access_activated_at",
                "access_expires_at",
                "curso_activado",
                "acceso_activo",
                "intentos",
                "examenes_entregados",
                "promedio",
                "date_joined",
                "last_login",
            ],
            (
                [
                    profile.user_id,
                    profile.user.username,
                    profile.user.email,
                    profile.user.first_name,
                    profile.user.last_name,
                    profile.get_role_display(),
                    profile.access_activated_at,
                    profile.access_expires_at,
                    profile.activated_course_name,
                    profile.has_active_exam_access(),
                    profile.attempt_count,
                    profile.delivered_count,
                    profile.average_score,
                    profile.user.date_joined,
                    profile.user.last_login,
                ]
                for profile in profiles
            ),
        )
        inscripciones = (
            Inscripcion.objects.select_related("activation_code", "user", "ficha_alumno")
            .order_by("-created_at")
        )
        inscripciones_csv = _csv_bytes(
            [
                "id",
                "created_at",
                "nombre",
                "comuna",
                "direccion",
                "correo",
                "telefono",
                "curso",
                "estado",
                "activation_code",
                "user_id",
                "numero_ficha",
            ],
            (
                [
                    inscripcion.id,
                    inscripcion.created_at,
                    inscripcion.nombre,
                    inscripcion.comuna,
                    inscripcion.direccion,
                    inscripcion.correo,
                    inscripcion.telefono,
                    inscripcion.curso,
                    inscripcion.get_status_display(),
                    inscripcion.activation_code.code if inscripcion.activation_code else "",
                    inscripcion.user_id,
                    inscripcion.ficha_alumno.numero_ficha
                    if hasattr(inscripcion, "ficha_alumno")
                    else "",
                ]
                for inscripcion in inscripciones
            ),
        )
        codigos = ActivationCode.objects.select_related("used_by").order_by("-created_at")
        codigos_csv = _csv_bytes(
            [
                "id",
                "code",
                "course_name",
                "duration_days",
                "is_enabled",
                "sent_to_email",
                "used_by_id",
                "used_by",
                "used_at",
                "created_at",
            ],
            (
                [
                    code.id,
                    code.code,
                    code.course_name,
                    code.duration_days,
                    code.is_enabled,
                    code.sent_to_email,
                    code.used_by_id,
                    code.used_by.username if code.used_by else "",
                    code.used_at,
                    code.created_at,
                ]
                for code in codigos
            ),
        )
        intentos_csv = _csv_bytes(
            [
                "id",
                "student_id",
                "student_username",
                "template",
                "status",
                "started_at",
                "finished_at",
                "score",
            ],
            (
                [
                    attempt.id,
                    attempt.student_id,
                    attempt.student.username,
                    attempt.template.name,
                    attempt.get_status_display(),
                    attempt.started_at,
                    attempt.finished_at,
                    attempt.score,
                ]
                for attempt in attempts
            ),
        )
        return _zip_response(
            "exportacion_gestion.zip",
            [
                ("alumnos.csv", alumnos_csv),
                ("inscripciones.csv", inscripciones_csv),
                ("codigos_activacion.csv", codigos_csv),
                ("intentos_examen.csv", intentos_csv),
            ],
        )

    def _export_odo(self):
        from odo.models import (
            FuelEntry,
            MaintenanceAlert,
            MaintenanceRecord,
            MaintenanceSchedule,
            OdometerReading,
            Vehicle,
            VehicleAccess,
            VehicleDocument,
        )

        vehicles = Vehicle.objects.select_related("owner").order_by("plate")
        vehiculos_csv = _csv_bytes(
            [
                "id",
                "patente",
                "alias",
                "marca",
                "modelo",
                "anio",
                "odometro_actual",
                "owner_id",
                "owner",
                "created_at",
                "updated_at",
            ],
            (
                [
                    vehicle.id,
                    vehicle.plate,
                    vehicle.alias,
                    vehicle.brand,
                    vehicle.model,
                    vehicle.year,
                    vehicle.current_odometer,
                    vehicle.owner_id,
                    vehicle.owner.username,
                    vehicle.created_at,
                    vehicle.updated_at,
                ]
                for vehicle in vehicles
            ),
        )
        accesos_csv = _csv_bytes(
            ["id", "vehicle_id", "patente", "user_id", "usuario", "email", "created_at"],
            (
                [
                    access.id,
                    access.vehicle_id,
                    access.vehicle.plate,
                    access.user_id,
                    access.user.username,
                    access.user.email,
                    access.created_at,
                ]
                for access in VehicleAccess.objects.select_related("vehicle", "user").order_by(
                    "vehicle__plate", "user__username"
                )
            ),
        )
        documentos_csv = _csv_bytes(
            [
                "id",
                "vehicle_id",
                "patente",
                "tipo",
                "archivo",
                "emitido",
                "vence",
                "estado",
                "notas",
                "uploaded_by_id",
                "uploaded_by",
                "created_at",
            ],
            (
                [
                    document.id,
                    document.vehicle_id,
                    document.vehicle.plate,
                    document.get_document_type_display(),
                    document.file.name,
                    document.issued_at,
                    document.expires_at,
                    document.status_label,
                    document.notes,
                    document.uploaded_by_id,
                    document.uploaded_by.username if document.uploaded_by else "",
                    document.created_at,
                ]
                for document in VehicleDocument.objects.select_related(
                    "vehicle", "uploaded_by"
                ).order_by("vehicle__plate", "document_type")
            ),
        )
        odometros_csv = _csv_bytes(
            ["id", "vehicle_id", "patente", "fecha", "odometro", "origen", "notas", "created_by", "created_at"],
            (
                [
                    reading.id,
                    reading.vehicle_id,
                    reading.vehicle.plate,
                    reading.date,
                    reading.odometer,
                    reading.get_source_display(),
                    reading.notes,
                    reading.created_by.username if reading.created_by else "",
                    reading.created_at,
                ]
                for reading in OdometerReading.objects.select_related(
                    "vehicle", "created_by"
                ).order_by("vehicle__plate", "-date")
            ),
        )
        combustible_csv = _csv_bytes(
            [
                "id",
                "vehicle_id",
                "patente",
                "fecha",
                "odometro",
                "litros",
                "precio_litro",
                "costo_total",
                "notas",
                "created_by",
                "created_at",
            ],
            (
                [
                    entry.id,
                    entry.vehicle_id,
                    entry.vehicle.plate,
                    entry.date,
                    entry.odometer,
                    entry.liters,
                    entry.price_per_liter,
                    entry.total_cost,
                    entry.notes,
                    entry.created_by.username if entry.created_by else "",
                    entry.created_at,
                ]
                for entry in FuelEntry.objects.select_related("vehicle", "created_by").order_by(
                    "vehicle__plate", "-date"
                )
            ),
        )
        programaciones_csv = _csv_bytes(
            [
                "id",
                "vehicle_id",
                "patente",
                "nombre",
                "vence_km",
                "vence_fecha",
                "estado",
                "notas",
                "created_at",
                "updated_at",
            ],
            (
                [
                    schedule.id,
                    schedule.vehicle_id,
                    schedule.vehicle.plate,
                    schedule.name,
                    schedule.due_odometer,
                    schedule.due_date,
                    schedule.get_status_display(),
                    schedule.notes,
                    schedule.created_at,
                    schedule.updated_at,
                ]
                for schedule in MaintenanceSchedule.objects.select_related("vehicle").order_by(
                    "vehicle__plate", "status", "due_date"
                )
            ),
        )
        mantenciones_csv = _csv_bytes(
            [
                "id",
                "vehicle_id",
                "patente",
                "schedule_id",
                "nombre",
                "fecha",
                "odometro",
                "costo",
                "notas",
                "created_by",
                "created_at",
            ],
            (
                [
                    record.id,
                    record.vehicle_id,
                    record.vehicle.plate,
                    record.schedule_id,
                    record.name,
                    record.date,
                    record.odometer,
                    record.cost,
                    record.notes,
                    record.created_by.username if record.created_by else "",
                    record.created_at,
                ]
                for record in MaintenanceRecord.objects.select_related(
                    "vehicle", "created_by"
                ).order_by("vehicle__plate", "-date")
            ),
        )
        alertas_csv = _csv_bytes(
            [
                "id",
                "vehicle_id",
                "patente",
                "schedule_id",
                "tipo",
                "severidad",
                "estado",
                "umbral",
                "mensaje",
                "created_at",
            ],
            (
                [
                    alert.id,
                    alert.vehicle_id,
                    alert.vehicle.plate,
                    alert.schedule_id,
                    alert.get_kind_display(),
                    alert.get_severity_display(),
                    alert.get_status_display(),
                    alert.threshold_value,
                    alert.message,
                    alert.created_at,
                ]
                for alert in MaintenanceAlert.objects.select_related(
                    "vehicle", "schedule"
                ).order_by("vehicle__plate", "-created_at")
            ),
        )
        return _zip_response(
            "exportacion_odo.zip",
            [
                ("vehiculos.csv", vehiculos_csv),
                ("accesos.csv", accesos_csv),
                ("documentos.csv", documentos_csv),
                ("odometros.csv", odometros_csv),
                ("combustible.csv", combustible_csv),
                ("programaciones_mantencion.csv", programaciones_csv),
                ("mantenciones_realizadas.csv", mantenciones_csv),
                ("alertas.csv", alertas_csv),
            ],
        )

    def _export_balance(self):
        from balance.models import ConceptoGasto, GastoMensual
        from balance.views import (
            MONTHS,
            automatic_expense_rows,
            manual_expense_rows,
            product_rows_for_year,
        )

        year = self._export_year()
        product_rows = product_rows_for_year(year)
        manual_rows = manual_expense_rows(year)
        automatic_rows = automatic_expense_rows(year)

        income_by_month = {month: 0 for month, _ in MONTHS}
        product_count_by_month = {month: 0 for month, _ in MONTHS}
        for row in product_rows:
            for month, value in row["meses"].items():
                income_by_month[month] += value["total"]
                product_count_by_month[month] += value["cantidad"]

        expenses_by_month = {month: 0 for month, _ in MONTHS}
        for row in manual_rows + automatic_rows:
            for item in row["meses"]:
                expenses_by_month[item["numero"]] += item["monto"]

        resumen_csv = _csv_bytes(
            ["anio", "mes", "mes_nombre", "ingresos", "gastos", "resultado", "productos"],
            (
                [
                    year,
                    month,
                    name,
                    income_by_month[month],
                    expenses_by_month[month],
                    income_by_month[month] - expenses_by_month[month],
                    product_count_by_month[month],
                ]
                for month, name in MONTHS
            ),
        )
        product_headers = [
            "anio",
            "producto",
            "cantidad_total",
            "ingreso_total",
            "precio_promedio",
        ]
        for month, name in MONTHS:
            product_headers.extend([f"{month:02d}_{name}_cantidad", f"{month:02d}_{name}_ingreso"])
        ingresos_csv = _csv_bytes(
            product_headers,
            (
                [
                    year,
                    row["nombre"],
                    row["cantidad_total"],
                    row["ingreso_total"],
                    row["precio_promedio"],
                    *[
                        value
                        for month, _name in MONTHS
                        for value in (
                            row["meses"][month]["cantidad"],
                            row["meses"][month]["total"],
                        )
                    ],
                ]
                for row in product_rows
            ),
        )
        expense_headers = ["anio", "concepto", "origen", "total"]
        for month, name in MONTHS:
            expense_headers.append(f"{month:02d}_{name}")
        gastos_rows = []
        for row in manual_rows:
            gastos_rows.append(
                [
                    year,
                    row["concepto"].nombre,
                    row["concepto"].get_origen_display(),
                    row["total"],
                    *[item["monto"] for item in row["meses"]],
                ]
            )
        for row in automatic_rows:
            gastos_rows.append(
                [
                    year,
                    row["nombre"],
                    "Automatico",
                    row["total"],
                    *[item["monto"] for item in row["meses"]],
                ]
            )
        gastos_csv = _csv_bytes(expense_headers, gastos_rows)
        conceptos_csv = _csv_bytes(
            ["id", "nombre", "origen", "orden", "activo"],
            (
                [
                    concepto.id,
                    concepto.nombre,
                    concepto.get_origen_display(),
                    concepto.orden,
                    concepto.activo,
                ]
                for concepto in ConceptoGasto.objects.order_by("orden", "nombre")
            ),
        )
        gastos_detalle_csv = _csv_bytes(
            [
                "id",
                "concepto_id",
                "concepto",
                "anio",
                "mes",
                "monto",
                "observacion",
                "updated_by_id",
                "updated_by",
                "created_at",
                "updated_at",
            ],
            (
                [
                    gasto.id,
                    gasto.concepto_id,
                    gasto.concepto.nombre,
                    gasto.anio,
                    gasto.mes,
                    gasto.monto,
                    gasto.observacion,
                    gasto.updated_by_id,
                    gasto.updated_by.username if gasto.updated_by else "",
                    gasto.created_at,
                    gasto.updated_at,
                ]
                for gasto in GastoMensual.objects.select_related(
                    "concepto", "updated_by"
                ).order_by("-anio", "mes", "concepto__orden", "concepto__nombre")
            ),
        )
        return _zip_response(
            f"exportacion_balance_{year}.zip",
            [
                ("resumen_mensual.csv", resumen_csv),
                ("ingresos_por_producto.csv", ingresos_csv),
                ("gastos_por_concepto.csv", gastos_csv),
                ("conceptos_gasto.csv", conceptos_csv),
                ("gastos_manuales_detalle.csv", gastos_detalle_csv),
            ],
        )


class FichaAlumnoManagementView(PrivateAreaMixin, StaffRequiredMixin, TemplateView):
    template_name = "core/fichas_manage.html"

    def _find_user_for_inscripcion(self, inscripcion):
        if inscripcion.user_id:
            return inscripcion.user
        email = (inscripcion.correo or "").strip()
        if not email:
            return None
        return (
            User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
            .order_by("id")
            .first()
        )

    def _initial_from_inscripcion(self, inscripcion):
        return {
            "fecha_inscripcion": timezone.localdate(inscripcion.created_at),
            "nombre": inscripcion.nombre,
            "correo": inscripcion.correo,
            "telefono": inscripcion.telefono,
            "direccion": inscripcion.direccion,
            "curso": inscripcion.curso,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        editing_ficha = kwargs.get("editing_ficha")
        form = kwargs.get("form")
        edit_id = self.request.GET.get("edit")
        if editing_ficha is None and edit_id:
            editing_ficha = get_object_or_404(FichaAlumno, pk=edit_id)
        if form is None:
            if editing_ficha is not None:
                form = FichaAlumnoForm(instance=editing_ficha)
            else:
                form = FichaAlumnoForm(
                    initial={"numero_ficha": FichaAlumno.next_numero_ficha()}
                )
        context["next_numero_ficha"] = FichaAlumno.next_numero_ficha()
        context["total_fichas"] = FichaAlumno.objects.count()
        context["last_ficha"] = (
            FichaAlumno.objects.filter(numero_ficha__isnull=False)
            .order_by("-numero_ficha")
            .first()
        )
        context["inscripciones_sin_ficha"] = (
            Inscripcion.objects.filter(ficha_alumno__isnull=True)
            .select_related("user")
            .order_by("-created_at")
        )
        context["form"] = form
        context["movimiento_form"] = kwargs.get("movimiento_form") or FichaMovimientoForm()
        context["editing_ficha"] = editing_ficha
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "add_movimiento":
            ficha = get_object_or_404(FichaAlumno, pk=request.POST.get("ficha_id"))
            movimiento_form = FichaMovimientoForm(request.POST)
            if not movimiento_form.is_valid():
                messages.error(request, "Revisa los datos del movimiento.")
                return self.render_to_response(
                    self.get_context_data(
                        editing_ficha=ficha,
                        movimiento_form=movimiento_form,
                    )
                )
            movimiento = movimiento_form.save(commit=False)
            movimiento.ficha = ficha
            movimiento.save()
            messages.success(request, f"Movimiento agregado a ficha {ficha.numero_ficha}.")
            return redirect(f"{reverse('core_web:fichas')}?edit={ficha.id}")

        ficha = None
        inscripcion = None
        initial = {}

        if action == "edit":
            ficha = get_object_or_404(FichaAlumno, pk=request.POST.get("ficha_id"))
        elif action == "create_from_inscripcion":
            inscripcion = get_object_or_404(Inscripcion, pk=request.POST.get("inscripcion_id"))
            initial = self._initial_from_inscripcion(inscripcion)

        form = FichaAlumnoForm(request.POST or None, instance=ficha, initial=initial)
        if not form.is_valid():
            messages.error(request, "Revisa los datos de la ficha.")
            return self.render_to_response(
                self.get_context_data(form=form, editing_ficha=ficha)
            )
        ficha = form.save(commit=False)
        if inscripcion is not None:
            ficha.inscripcion = inscripcion
            ficha.user = self._find_user_for_inscripcion(inscripcion)
        ficha.save()
        FichaMovimiento.sync_pago_inicial(ficha)
        messages.success(request, f"Ficha {ficha.numero_ficha} guardada.")
        return redirect("core_web:fichas")


class FichaAlumnoListView(PrivateAreaMixin, StaffRequiredMixin, TemplateView):
    template_name = "core/fichas_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fichas"] = (
            FichaAlumno.objects.select_related("inscripcion", "user")
            .prefetch_related("movimientos")
            .annotate(
                total_movimientos=Sum("movimientos__monto"),
                cantidad_movimientos=Count("movimientos", distinct=True),
            )
            .order_by("-numero_ficha")
        )
        context["total_fichas"] = FichaAlumno.objects.count()
        context["last_ficha"] = (
            FichaAlumno.objects.filter(numero_ficha__isnull=False)
            .order_by("-numero_ficha")
            .first()
        )
        return context


class StaffStudentManagementView(PrivateAreaMixin, StaffRequiredMixin, TemplateView):
    template_name = "core/staff_students.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        students = (
            Profile.objects.filter(role=UserRole.ALUMNO)
            .select_related("user")
            .annotate(
                attempt_count=Count("user__examattempt", distinct=True),
                delivered_count=Count(
                    "user__examattempt",
                    filter=Q(user__examattempt__status=ExamAttemptStatus.ENTREGADO),
                    distinct=True,
                ),
                average_score=Avg(
                    "user__examattempt__score",
                    filter=Q(
                        user__examattempt__status=ExamAttemptStatus.ENTREGADO,
                        user__examattempt__score__isnull=False,
                    ),
                ),
            )
            .order_by("-access_expires_at", "user__first_name", "user__username")
        )
        context["students"] = students
        context["active_students_count"] = students.filter(
            access_expires_at__isnull=False,
            access_expires_at__gte=now,
        ).count()
        context["total_students_count"] = students.count()
        return context


class StaffStudentAuditView(PrivateAreaMixin, StaffRequiredMixin, TemplateView):
    template_name = "core/staff_student_audit.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        student = get_object_or_404(User, pk=kwargs["user_id"])
        profile, _ = Profile.objects.get_or_create(user=student)
        attempts = list(
            ExamAttempt.objects.filter(student=student)
            .select_related("template")
            .order_by("-started_at")
        )
        for attempt in attempts:
            check_and_expire_attempt(attempt)

        context["audit_student"] = student
        context["profile"] = profile
        context["attempts"] = attempts
        context["exam_progress"] = get_student_exam_progress(student)
        context["access_expires_in_days"] = (
            max(0, (profile.access_expires_at.date() - timezone.now().date()).days)
            if profile.access_expires_at
            else None
        )
        return context


class CourseActivationView(PrivateAreaMixin, TemplateView):
    template_name = "core/activate_course.html"

    def _get_profile(self):
        profile = getattr(self.request.user, "profile", None)
        if profile is None:
            profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile

    def _activate_code(self, code):
        activation = ActivationCode.objects.get(code=code)
        return activate_code_for_user(self.request.user, activation)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self._get_profile()
        context["profile"] = profile
        context["has_exam_access"] = profile.has_active_exam_access()
        context["activation_form"] = kwargs.get(
            "activation_form", ActivationCodeForm(user=self.request.user)
        )
        context["access_expires_in_days"] = (
            max(0, (profile.access_expires_at.date() - timezone.now().date()).days)
            if profile.access_expires_at
            else None
        )
        return context

    def post(self, request, *args, **kwargs):
        form = ActivationCodeForm(request.POST, user=request.user)
        if form.is_valid():
            activation, _profile = self._activate_code(
                form.cleaned_data["activation_instance"].code
            )
            messages.success(
                request,
                f"Codigo activado correctamente. Se agregaron {activation.duration_days} dias de acceso a tus examenes.",
            )
            return redirect("core_web:dashboard")

        messages.error(request, "No fue posible activar el curso. Revisa tu codigo.")
        context = self.get_context_data(activation_form=form)
        return self.render_to_response(context)


class ExamDashboardView(PrivateAreaMixin, TemplateView):
    template_name = "core/dashboard.html"

    def _get_profile(self):
        profile = getattr(self.request.user, "profile", None)
        if profile is None:
            profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile

    def _activate_code(self, code):
        activation = ActivationCode.objects.get(code=code)
        _activation, profile = activate_code_for_user(self.request.user, activation)
        return profile

    def _get_attempts(self):
        attempts = list(
            ExamAttempt.objects.filter(student=self.request.user)
            .select_related("template")
            .order_by("-started_at")
        )
        for attempt in attempts:
            check_and_expire_attempt(attempt)
        return attempts

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self._get_profile()
        has_exam_access = profile.has_active_exam_access()
        attempts = self._get_attempts() if has_exam_access else []
        active_attempt = next(
            (attempt for attempt in attempts if attempt.status == ExamAttemptStatus.EN_CURSO),
            None,
        ) if has_exam_access else None
        templates = list(ExamTemplate.objects.all())
        for template in templates:
            template.active_attempt = next(
                (
                    attempt
                    for attempt in attempts
                    if attempt.template_id == template.id
                    and attempt.status == ExamAttemptStatus.EN_CURSO
                ),
                None,
            )

        context["templates"] = templates
        context["default_exam_template"] = templates[0] if templates else None
        context["attempts"] = attempts
        context["active_attempt"] = active_attempt
        context["average_score"] = (
            sum(
                attempt.score
                for attempt in attempts
                if attempt.status == ExamAttemptStatus.ENTREGADO
                and attempt.score is not None
            )
            / max(
                1,
                sum(
                    1
                    for attempt in attempts
                    if attempt.status == ExamAttemptStatus.ENTREGADO
                    and attempt.score is not None
                ),
            )
            if any(
                attempt.status == ExamAttemptStatus.ENTREGADO
                and attempt.score is not None
                for attempt in attempts
            )
            else None
        )
        delivered_attempts = [
            attempt
            for attempt in attempts
            if attempt.status == ExamAttemptStatus.ENTREGADO and attempt.score is not None
        ]
        exam_progress = get_student_exam_progress(self.request.user) if has_exam_access else None
        context["exam_progress"] = add_material_paths_to_exam_progress(exam_progress)
        context["total_attempts"] = len(attempts)
        context["approved_attempts"] = sum(1 for attempt in delivered_attempts if attempt.score >= 85)
        context["failed_attempts"] = sum(1 for attempt in delivered_attempts if attempt.score < 85)
        def _format_duration(seconds_total: float) -> str:
            minutes_total = int(seconds_total // 60)
            hours, minutes = divmod(minutes_total, 60)
            return f"{hours}h {minutes}m"

        total_exam_seconds = 0
        for att in delivered_attempts:
            if att.started_at and att.finished_at:
                delta = att.finished_at - att.started_at
                if delta.total_seconds() > 0:
                    total_exam_seconds += delta.total_seconds()

        context["time_in_exam"] = _format_duration(total_exam_seconds)
        context["platform_hours_sum"] = round(total_exam_seconds / 3600, 1) if total_exam_seconds else 0
        context["student"] = self.request.user
        context["profile"] = profile
        context["has_exam_access"] = has_exam_access
        context["activation_form"] = kwargs.get(
            "activation_form", ActivationCodeForm(user=self.request.user)
        )
        context["access_expires_in_days"] = (
            max(0, (profile.access_expires_at.date() - timezone.now().date()).days)
            if profile.access_expires_at
            else None
        )
        context["active_attempt_remaining_minutes"] = (
            (get_remaining_seconds(active_attempt) + 59) // 60
            if active_attempt is not None and get_remaining_seconds(active_attempt) is not None
            else None
        )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "activate":
            return redirect("core_web:activate-course")

        if not user_has_active_exam_access(request.user):
            messages.error(
                request,
                "Necesitas activar tu curso con un codigo antes de iniciar examenes.",
            )
            return redirect("core_web:dashboard")

        template_id = request.POST.get("template_id")
        if not template_id:
            messages.error(request, "Debes seleccionar una plantilla valida.")
            return redirect("core_web:dashboard")

        template = get_object_or_404(ExamTemplate, pk=template_id)

        topic = None
        topic_id = request.POST.get("topic_id")
        if topic_id:
            topic = get_object_or_404(Topic, pk=topic_id)

        try:
            attempt = generate_exam_attempt(request.user, template, topic=topic)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("core_web:dashboard")

        messages.success(request, "Examen iniciado correctamente.")
        return redirect("core_web:attempt-detail", pk=attempt.pk)


class ExamAttemptHistoryView(PrivateAreaMixin, ListView):
    template_name = "core/exam_attempt_history.html"
    context_object_name = "history_attempts"
    paginate_by = 25

    def get_queryset(self):
        attempts = list(
            ExamAttempt.objects.filter(student=self.request.user)
            .select_related("template")
            .prefetch_related("exam_questions")
            .order_by("-started_at", "-id")
        )
        for attempt in attempts:
            check_and_expire_attempt(attempt)
        return add_history_summary_to_attempts(attempts)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        attempts = context["history_attempts"]
        delivered_attempts = [
            attempt
            for attempt in self.object_list
            if attempt.status == ExamAttemptStatus.ENTREGADO and attempt.score is not None
        ]
        context["approved_attempts"] = sum(1 for attempt in delivered_attempts if attempt.score >= 85)
        context["failed_attempts"] = sum(1 for attempt in delivered_attempts if attempt.score < 85)
        context["average_score"] = (
            sum(attempt.score for attempt in delivered_attempts) / len(delivered_attempts)
            if delivered_attempts
            else None
        )
        context["shown_attempts"] = len(attempts)
        context["total_attempts"] = len(self.object_list)
        return context


class ExamAttemptDetailView(PrivateAreaMixin, DetailView):
    template_name = "core/exam_attempt_detail.html"
    model = ExamAttempt
    context_object_name = "attempt"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(student=self.request.user)
            .select_related("template")
            .prefetch_related("exam_questions__answer")
        )

    def post(self, request, *args, **kwargs):
        if not user_has_active_exam_access(request.user):
            messages.error(
                request,
                "Tu acceso al curso no esta activo. Ingresa tu codigo para continuar.",
            )
            return redirect("core_web:dashboard")
        self.object = self.get_object()
        if check_and_expire_attempt(self.object):
            messages.error(request, "El tiempo del examen ha expirado.")
            return redirect("core_web:attempt-detail", pk=self.object.pk)
        action = request.POST.get("action")

        if action not in {"save", "finish"}:
            messages.error(request, "Accion no reconocida.")
            return redirect("core_web:attempt-detail", pk=self.object.pk)

        if self.object.status == ExamAttemptStatus.ENTREGADO:
            messages.info(
                request,
                "El examen ya fue entregado. No es posible modificar respuestas.",
            )
            return redirect("core_web:attempt-detail", pk=self.object.pk)

        questions = list(self.object.exam_questions.all())
        question_positions = {eq.pk: idx + 1 for idx, eq in enumerate(questions)}

        encountered_error = False
        saved_answers = 0

        for eq in questions:
            field_name = f"answers-{eq.pk}"
            selected_indexes = request.POST.getlist(field_name)
            if not selected_indexes:
                continue
            try:
                grade_single_answer(
                    eq,
                    selected_indexes,
                    include_feedback=False,
                )
                saved_answers += 1
            except ValueError as exc:
                encountered_error = True
                number = question_positions.get(eq.pk, eq.pk)
                messages.error(
                    request,
                    f"Pregunta {number}: {exc}",
                )

        if action == "finish":
            unanswered = []
            for eq in questions:
                ans = getattr(eq, "answer", None)
                if not ans or (not ans.selected_indexes and ans.selected_index is None):
                    unanswered.append(eq)
            if unanswered:
                messages.error(
                    request,
                    f"Quedan {len(unanswered)} preguntas sin responder.",
                )
                return redirect("core_web:attempt-detail", pk=self.object.pk)

            score = grade_attempt(self.object)
            messages.success(
                request,
                f"Examen finalizado. Puntaje obtenido: {score}.",
            )
        else:
            if encountered_error:
                # Errors already communicated per question.
                pass
            elif saved_answers:
                messages.success(request, "Respuestas guardadas.")
            else:
                messages.info(
                    request,
                    "No se recibieron cambios para guardar.",
                )

        return redirect("core_web:attempt-detail", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        check_and_expire_attempt(self.object)
        questions = list(self.object.exam_questions.all())
        entries = []
        for idx, question in enumerate(questions, start=1):
            answer = getattr(question, "answer", None)
            selected = []
            if answer:
                selected = list(answer.selected_indexes or [])
                if not selected and answer.selected_index is not None:
                    selected = [answer.selected_index]
            correct = [
                i for i, option in enumerate(question.options or []) if option.get("is_correct")
            ]
            option_texts = [option.get("text", "") for option in question.options or []]
            selected_texts = [
                option_texts[i] for i in selected if 0 <= i < len(option_texts)
            ]
            correct_texts = [
                option_texts[i] for i in correct if 0 <= i < len(option_texts)
            ]
            entries.append(
                {
                    "number": idx,
                    "question": question,
                    "answer": answer,
                    "selected_indexes": selected,
                    "correct_indexes": correct,
                    "selected_texts": selected_texts,
                    "correct_texts": correct_texts,
                }
            )
        answered_count = sum(1 for entry in entries if entry["selected_indexes"])
        context["question_entries"] = entries
        context["is_expired"] = self.object.status == ExamAttemptStatus.EXPIRADO
        context["can_answer"] = self.object.status not in (
            ExamAttemptStatus.ENTREGADO,
            ExamAttemptStatus.EXPIRADO,
        )
        context["can_repeat"] = (
            self.object.status in (ExamAttemptStatus.ENTREGADO, ExamAttemptStatus.EXPIRADO)
            and user_has_active_exam_access(self.request.user)
            and bool(entries)
        )
        context["show_feedback"] = (
            self.object.status == ExamAttemptStatus.ENTREGADO
            and self.object.template.show_feedback
        )
        context["answered_count"] = answered_count
        context["total_questions"] = len(entries)
        context["all_answered"] = answered_count == len(entries) and len(entries) > 0
        context["unanswered_count"] = max(0, len(entries) - answered_count)
        context["progress_percent"] = (
            int(round((answered_count / len(entries)) * 100))
            if entries
            else 0
        )
        remaining_seconds = get_remaining_seconds(self.object)
        context["remaining_seconds"] = remaining_seconds
        context["remaining_minutes"] = (
            (remaining_seconds + 59) // 60
            if remaining_seconds is not None
            else None
        )
        return context

    def dispatch(self, request, *args, **kwargs):
        if (
            request.user.is_authenticated
            and not request.user.is_staff
            and not user_has_active_exam_access(request.user)
        ):
            messages.error(
                request,
                "Tu acceso al curso no esta activo. Ingresa tu codigo para continuar.",
            )
            return redirect("core_web:dashboard")
        return super().dispatch(request, *args, **kwargs)


class StaffExamAuditDetailView(ExamAttemptDetailView):
    def get_queryset(self):
        return (
            ExamAttempt.objects.all()
            .select_related("student", "template")
            .prefetch_related("exam_questions__answer")
        )

    def post(self, request, *args, **kwargs):
        messages.error(request, "La vista de auditoria es solo lectura.")
        return redirect("core_web:staff-exam-audit", pk=kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["audit_mode"] = True
        context["audit_student"] = self.object.student
        context["can_answer"] = False
        context["can_repeat"] = False
        context["show_feedback"] = True
        context["remaining_minutes"] = None
        return context


class RepeatExamAttemptView(PrivateAreaMixin, View):
    def post(self, request, *args, **kwargs):
        if not user_has_active_exam_access(request.user):
            messages.error(
                request,
                "Tu acceso al curso no esta activo. Ingresa tu codigo para continuar.",
            )
            return redirect("core_web:dashboard")

        original_attempt = get_object_or_404(
            ExamAttempt.objects.prefetch_related("exam_questions"),
            pk=kwargs["pk"],
            student=request.user,
        )
        check_and_expire_attempt(original_attempt)

        if original_attempt.status == ExamAttemptStatus.EN_CURSO:
            messages.info(request, "Este examen aun esta en curso. Puedes reanudarlo.")
            return redirect("core_web:attempt-detail", pk=original_attempt.pk)

        try:
            new_attempt = repeat_exam_attempt(original_attempt)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("core_web:attempt-detail", pk=original_attempt.pk)

        messages.success(request, "Se creo un nuevo intento con las mismas preguntas.")
        return redirect("core_web:attempt-detail", pk=new_attempt.pk)
