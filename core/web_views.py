from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import DetailView, FormView, TemplateView, View
from urllib.parse import quote
import secrets

from .forms import ActivationCodeForm, InscripcionForm, StudentSignupForm
from .models import ActivationCode, ExamAttempt, ExamAttemptStatus, ExamTemplate, Inscripcion, Profile
from .services import (
    check_and_expire_attempt,
    generate_exam_attempt,
    get_remaining_seconds,
    grade_attempt,
    grade_single_answer,
    user_has_active_exam_access,
)

User = get_user_model()


class StudentSignupView(FormView):
    template_name = "registration/signup.html"
    form_class = StudentSignupForm
    success_url = reverse_lazy("core_web:dashboard")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(
            self.request,
            "Registro exitoso. Ahora ingresa tu codigo de activacion desde el panel para habilitar los examenes.",
        )
        return super().form_valid(form)

class InscripcionCreateView(FormView):
    template_name = "core/inscripcion_form.html"
    form_class = InscripcionForm
    success_url = reverse_lazy("core_web:inscripcion")

    def get_initial(self):
        initial = super().get_initial()
        curso = self.request.GET.get("curso")
        if curso:
            initial["curso"] = curso
        return initial

    def form_valid(self, form):
        # Aseguramos persistencia antes de redirigir a WhatsApp.
        with transaction.atomic():
            inscripcion = form.save()
        messages.success(self.request, "Hemos recibido tu solicitud. Te contactaremos pronto.")

        # Numero fijo para recibir la inscripcion por WhatsApp
        whatsapp_number = "56992734999"
        curso = inscripcion.curso or "No especificado"
        message = (
            "Nueva inscripcion de curso:\n"
            f"Nombre: {inscripcion.nombre}\n"
            f"Comuna: {inscripcion.comuna}\n"
            f"Correo: {inscripcion.correo}\n"
            f"Telefono: {inscripcion.telefono}\n"
            f"Curso: {curso}"
        )
        whatsapp_url = f"https://wa.me/{whatsapp_number}?text={quote(message)}"
        # Abrimos WhatsApp en nueva pestaña y volvemos al home con el form limpio.
        return render(
            self.request,
            "core/inscripcion_redirect.html",
            {"whatsapp_url": whatsapp_url, "home_url": reverse_lazy("core_web:landing")},
        )

    def form_invalid(self, form):
        messages.error(self.request, "Revisa los datos ingresados e intenta nuevamente.")
        return super().form_invalid(form)

class LandingView(TemplateView):
    template_name = "core/home.html"

class StudentsLandingView(TemplateView):
    template_name = "core/alumnos.html"

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
            Inscripcion.objects.select_related("activation_code")
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
                messages.success(
                    request,
                    f"Codigo {activation.code} generado para {inscripcion.nombre}.",
                )
            else:
                messages.info(
                    request,
                    f"Esta inscripcion ya tiene el codigo {inscripcion.activation_code.code}.",
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


class CourseActivationView(PrivateAreaMixin, TemplateView):
    template_name = "core/activate_course.html"

    def _get_profile(self):
        profile = getattr(self.request.user, "profile", None)
        if profile is None:
            profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile

    def _activate_code(self, code):
        activation = ActivationCode.objects.get(code=code)
        profile = self._get_profile()
        now = timezone.now()
        profile.access_activated_at = now
        profile.access_expires_at = now + timedelta(days=activation.duration_days)
        profile.activated_course_name = activation.course_name
        profile.save(
            update_fields=["access_activated_at", "access_expires_at", "activated_course_name"]
        )
        activation.used_by = self.request.user
        activation.used_at = now
        activation.save(update_fields=["used_by", "used_at"])
        return activation, profile

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self._get_profile()
        context["profile"] = profile
        context["has_exam_access"] = profile.has_active_exam_access()
        context["activation_form"] = kwargs.get("activation_form", ActivationCodeForm())
        context["access_expires_in_days"] = (
            max(0, (profile.access_expires_at.date() - timezone.now().date()).days)
            if profile.access_expires_at
            else None
        )
        return context

    def post(self, request, *args, **kwargs):
        form = ActivationCodeForm(request.POST)
        if form.is_valid():
            activation, _profile = self._activate_code(
                form.cleaned_data["activation_instance"].code
            )
            messages.success(
                request,
                f"Codigo activado correctamente. Tienes {activation.duration_days} dias de acceso a los examenes.",
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
        profile = self._get_profile()
        now = timezone.now()
        profile.access_activated_at = now
        profile.access_expires_at = now + timedelta(days=activation.duration_days)
        profile.activated_course_name = activation.course_name
        profile.save(
            update_fields=["access_activated_at", "access_expires_at", "activated_course_name"]
        )
        activation.used_by = self.request.user
        activation.used_at = now
        activation.save(update_fields=["used_by", "used_at"])
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
        context["attempts"] = attempts
        context["active_attempt"] = active_attempt
        context["history_attempts"] = [
            attempt for attempt in attempts if active_attempt is None or attempt.pk != active_attempt.pk
        ]
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
        context["activation_form"] = kwargs.get("activation_form", ActivationCodeForm())
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

        try:
            attempt = generate_exam_attempt(request.user, template)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("core_web:dashboard")

        messages.success(request, "Examen iniciado correctamente.")
        return redirect("core_web:attempt-detail", pk=attempt.pk)


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
        if request.user.is_authenticated and not user_has_active_exam_access(request.user):
            messages.error(
                request,
                "Tu acceso al curso no esta activo. Ingresa tu codigo para continuar.",
            )
            return redirect("core_web:dashboard")
        return super().dispatch(request, *args, **kwargs)
