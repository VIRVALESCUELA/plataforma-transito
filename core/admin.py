from django.contrib import admin
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
    list_display = ("id", "student", "template", "status", "score", "started_at", "finished_at")
    list_filter = ("status", "template")
    search_fields = ("student__username",)


@admin.register(ExamQuestion)
class ExamQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "attempt", "topic", "difficulty", "reference_law")
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


@admin.register(StudentAnswer)
class StudentAnswerAdmin(admin.ModelAdmin):
    list_display = ("id", "exam_question", "selected_index", "is_correct", "answered_at")
    list_filter = ("is_correct",)
    search_fields = ("exam_question__question_text",)


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
