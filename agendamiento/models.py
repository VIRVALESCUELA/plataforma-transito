from django.conf import settings
from django.db import models
from django.utils import timezone


class CourseKind(models.TextChoices):
    DOCE_MODULOS = "12_MODULOS", "12 modulos"
    DIEZ_MODULOS = "10_MODULOS", "10 modulos"
    OCHO_HORAS = "8_HORAS", "8 horas"
    SEIS_HORAS = "6_HORAS", "6 horas"
    OTRO = "OTRO", "Otro"


class LessonStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Agendada"
    COMPLETED = "COMPLETED", "Ejecutada"
    ABSENT = "ABSENT", "Ausente alumno"
    SCHOOL_SUSPENDED = "SCHOOL_SUSPENDED", "Suspendida por escuela"
    STUDENT_RESCHEDULED = "STUDENT_RESCHEDULED", "Reagendada por alumno"


class ScheduleResource(models.Model):
    name = models.CharField(max_length=120, unique=True)
    instructor = models.CharField(max_length=120, blank=True)
    vehicle = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=7, default="#1f4b42")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Recurso de agendamiento"
        verbose_name_plural = "Recursos de agendamiento"

    def __str__(self):
        return self.name


class DrivingLesson(models.Model):
    resource = models.ForeignKey(
        ScheduleResource,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lessons",
    )
    date = models.DateField()
    slot_key = models.CharField(max_length=16)
    start_time = models.TimeField()
    end_time = models.TimeField()
    ficha_alumno = models.ForeignKey(
        "core.FichaAlumno",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clases_practicas",
    )
    ficha = models.PositiveIntegerField()
    lesson_number = models.PositiveSmallIntegerField()
    course_kind = models.CharField(
        max_length=20,
        choices=CourseKind.choices,
        default=CourseKind.DOCE_MODULOS,
    )
    status = models.CharField(
        max_length=24,
        choices=LessonStatus.choices,
        default=LessonStatus.SCHEDULED,
    )
    is_completed = models.BooleanField(default=False)
    notes = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_driving_lessons",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time", "ficha", "lesson_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["date", "slot_key", "resource"],
                name="unique_driving_lesson_by_date_slot_resource",
            )
        ]

    def __str__(self):
        return f"{self.date} {self.slot_key} - {self.ficha}/{self.lesson_number}"


class ScheduleBlock(models.Model):
    class Scope(models.TextChoices):
        DAY = "DAY", "Dia completo"
        SLOT = "SLOT", "Horario"

    resource = models.ForeignKey(
        ScheduleResource,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="blocks",
    )
    date = models.DateField()
    scope = models.CharField(max_length=8, choices=Scope.choices)
    slot_key = models.CharField(max_length=16, blank=True)
    reason = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_schedule_blocks",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["date", "scope", "slot_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["date", "scope", "slot_key", "resource"],
                name="unique_schedule_block_by_date_scope_slot_resource",
            )
        ]

    def __str__(self):
        target = self.slot_key if self.scope == self.Scope.SLOT else "dia"
        return f"{self.date} {target}"


class ScheduleOpening(models.Model):
    class Scope(models.TextChoices):
        DAY = "DAY", "Dia completo"
        SLOT = "SLOT", "Horario"

    resource = models.ForeignKey(
        ScheduleResource,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="openings",
    )
    date = models.DateField()
    scope = models.CharField(max_length=8, choices=Scope.choices)
    slot_key = models.CharField(max_length=16, blank=True)
    reason = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_schedule_openings",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["date", "scope", "slot_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["date", "scope", "slot_key", "resource"],
                name="unique_schedule_opening_by_date_scope_slot_resource",
            )
        ]

    def __str__(self):
        target = self.slot_key if self.scope == self.Scope.SLOT else "dia"
        return f"{self.date} {target} abierto"
