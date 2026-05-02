from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    ActivationCode,
    ExamAttempt,
    ExamQuestion,
    ExamTemplate,
    Inscripcion,
    Option,
    Profile,
    Question,
    StudentAnswer,
    Topic,
)


# --- Opciones en linea dentro de la Pregunta ---
class OptionInline(admin.TabularInline):
    model = Option
    extra = 4  # muestra 4 filas por defecto
    min_num = 2
    max_num = 6


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "text_short", "topic", "difficulty", "is_active")
    list_filter = ("topic", "difficulty", "is_active")
    search_fields = ("text", "reference_law", "reference_book")
    readonly_fields = ("preview",)
    inlines = [OptionInline]

    def text_short(self, obj):
        return (obj.text[:80] + "...") if len(obj.text) > 80 else obj.text

    text_short.short_description = "Pregunta"

    def thumb(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height:40px"/>', obj.image.url)
        return "-"

    thumb.short_description = "Imagen"

    def preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:200px"/>', obj.image.url)
        return "Sin imagen"


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(ExamTemplate)
class ExamTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "total_questions", "duration_minutes", "show_feedback")
    list_editable = ("total_questions", "duration_minutes", "show_feedback")

    # Por tu requerimiento: 35 preguntas y 45 min por defecto
    def get_changeform_initial_data(self, request):
        return {"total_questions": 35, "duration_minutes": 45, "show_feedback": True}


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "student_email", "template", "status", "score", "started_at", "finished_at")
    list_filter = ("status", "template")
    search_fields = ("student__username", "student__first_name", "student__last_name", "student__email")
    date_hierarchy = "started_at"
    ordering = ("-started_at",)

    def student_email(self, obj):
        return obj.student.email or "-"

    student_email.short_description = "Correo"


@admin.register(ExamQuestion)
class ExamQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "attempt_link", "student", "question_short", "topic", "difficulty", "answer_status")
    list_filter = ("topic", "difficulty", "attempt__status", "attempt__template")
    search_fields = (
        "question_text",
        "topic",
        "reference_law",
        "reference_book",
        "attempt__student__username",
        "attempt__student__first_name",
        "attempt__student__last_name",
        "attempt__student__email",
    )
    readonly_fields = (
        "attempt",
        "question_text",
        "options",
        "topic",
        "difficulty",
        "reference_law",
        "reference_book",
        "explanation",
    )
    ordering = ("-attempt__started_at", "id")
    list_select_related = ("attempt", "attempt__student")

    def attempt_link(self, obj):
        url = reverse("admin:core_examattempt_change", args=[obj.attempt_id])
        return format_html('<a href="{}">Examen #{}</a>', url, obj.attempt_id)

    attempt_link.short_description = "Examen"

    def student(self, obj):
        return obj.attempt.student

    student.short_description = "Alumno"

    def question_short(self, obj):
        return (obj.question_text[:100] + "...") if len(obj.question_text) > 100 else obj.question_text

    question_short.short_description = "Pregunta"

    def answer_status(self, obj):
        answer = getattr(obj, "answer", None)
        if not answer:
            return "Sin responder"
        return "Correcta" if answer.is_correct else "Incorrecta"

    answer_status.short_description = "Resultado"


@admin.register(StudentAnswer)
class StudentAnswerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "attempt_link",
        "question_short",
        "selected_answer",
        "correct_answer",
        "is_correct",
        "answered_at",
    )
    list_filter = ("is_correct", "exam_question__attempt__template", "exam_question__attempt__status")
    search_fields = (
        "exam_question__question_text",
        "exam_question__topic",
        "exam_question__attempt__student__username",
        "exam_question__attempt__student__first_name",
        "exam_question__attempt__student__last_name",
        "exam_question__attempt__student__email",
    )
    date_hierarchy = "answered_at"
    ordering = ("-answered_at",)
    list_select_related = ("exam_question", "exam_question__attempt", "exam_question__attempt__student")

    def student(self, obj):
        return obj.exam_question.attempt.student

    student.short_description = "Alumno"

    def attempt_link(self, obj):
        attempt = obj.exam_question.attempt
        url = reverse("admin:core_examattempt_change", args=[attempt.id])
        return format_html('<a href="{}">Examen #{}</a>', url, attempt.id)

    attempt_link.short_description = "Examen"

    def question_short(self, obj):
        text = obj.exam_question.question_text
        return (text[:100] + "...") if len(text) > 100 else text

    question_short.short_description = "Pregunta"

    def selected_answer(self, obj):
        options = obj.exam_question.options or []
        if obj.selected_indexes:
            selected = []
            for index in obj.selected_indexes:
                if 0 <= index < len(options):
                    selected.append(options[index].get("text", ""))
            return " | ".join(selected) or "-"
        if obj.selected_index is not None and 0 <= obj.selected_index < len(options):
            return options[obj.selected_index].get("text", "")
        return "-"

    selected_answer.short_description = "Respuesta alumno"

    def correct_answer(self, obj):
        options = obj.exam_question.options or []
        correct = [option.get("text", "") for option in options if option.get("is_correct")]
        return " | ".join(correct) or "-"

    correct_answer.short_description = "Respuesta correcta"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "full_name",
        "email",
        "role",
        "access_status",
        "activated_course_name",
        "access_expires_at",
    )
    list_filter = ("role", "activated_course_name")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")

    def full_name(self, obj):
        full_name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return full_name or "-"

    full_name.short_description = "Nombre"

    def email(self, obj):
        return obj.user.email or "-"

    email.short_description = "Correo"

    def access_status(self, obj):
        return "Activo" if obj.has_active_exam_access() else "Sin activar"

    access_status.short_description = "Acceso"


@admin.register(ActivationCode)
class ActivationCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "course_name", "duration_days", "is_enabled", "used_by", "used_at")
    list_filter = ("is_enabled", "duration_days")
    search_fields = ("code", "course_name", "used_by__username")


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "curso", "status", "correo", "telefono", "activation_code", "created_at")
    search_fields = ("nombre", "correo", "telefono", "curso", "comuna")
    list_filter = ("curso", "comuna", "status")
