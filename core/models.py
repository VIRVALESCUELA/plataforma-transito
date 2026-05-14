from django.conf import settings
from django.db import models
from django.utils import timezone

class UserRole(models.TextChoices):
    ALUMNO = 'ALUMNO', 'Alumno'
    DOCENTE = 'DOCENTE', 'Docente'
    ADMIN = 'ADMIN', 'Admin'

class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=UserRole.choices, default=UserRole.ALUMNO)
    access_activated_at = models.DateTimeField(null=True, blank=True)
    access_expires_at = models.DateTimeField(null=True, blank=True)
    activated_course_name = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "Registro de plataforma"
        verbose_name_plural = "Registros de plataforma"

    def has_active_exam_access(self):
        return bool(
            self.access_expires_at and timezone.now() <= self.access_expires_at
        )


class ActivationCode(models.Model):
    code = models.CharField(max_length=40, unique=True)
    course_name = models.CharField(max_length=120, blank=True)
    duration_days = models.PositiveIntegerField(default=30)
    is_enabled = models.BooleanField(default=True)
    used_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

class Inscripcion(models.Model):
    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        CONTACTADO = "CONTACTADO", "Contactado"
        CLIENTE = "CLIENTE", "Cliente sin plataforma"
        MATRICULADO = "MATRICULADO", "Matriculado"
        CUENTA_CREADA = "CUENTA_CREADA", "Cuenta creada"
        CURSO_ACTIVO = "CURSO_ACTIVO", "Curso activo"
        DESCARTADO = "DESCARTADO", "Descartado"

    nombre = models.CharField(max_length=150)
    comuna = models.CharField(max_length=120)
    correo = models.EmailField()
    telefono = models.CharField(max_length=30)
    curso = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDIENTE,
    )
    activation_code = models.OneToOneField(
        "ActivationCode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inscripcion",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Solicitud de inscripcion"
        verbose_name_plural = "Solicitudes de inscripcion"

    @property
    def requires_online_access(self):
        course_name = (self.curso or "").casefold()
        online_keywords = ("teorico", "teórico", "instagram")
        return any(keyword in course_name for keyword in online_keywords)


class PageVisitCounter(models.Model):
    page = models.CharField(max_length=120, unique=True)
    total = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page"]
        verbose_name = "Contador de visitas"
        verbose_name_plural = "Contadores de visitas"

    def __str__(self):
        return f"{self.page}: {self.total}"


class Topic(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    def __str__(self): return self.name

class Question(models.Model):
    text = models.TextField()
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True)
    difficulty = models.IntegerField(default=1)  # 1 fácil, 2 medio, 3 difícil
    reference_law = models.CharField(max_length=50, blank=True)  # p.ej., "Art. 123"
    reference_book = models.CharField(max_length=100, blank=True)  # p.ej., "Cap. 2, Sección B"
    explanation = models.TextField(blank=True)
    image = models.ImageField(upload_to='questions/', blank=True, null=True)  
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Option(models.Model):
    question = models.ForeignKey(Question, related_name='options', on_delete=models.CASCADE)
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)

class ExamTemplate(models.Model):
    name = models.CharField(max_length=120)
    duration_minutes = models.IntegerField(default=45)
    total_questions = models.IntegerField(default=35)
    rules_json = models.JSONField(default=dict, blank=True)
    show_feedback = models.BooleanField(default=True)
   
class ExamAttemptStatus(models.TextChoices):
    EN_CURSO = 'EN_CURSO', 'En curso'
    ENTREGADO = 'ENTREGADO', 'Entregado'
    EXPIRADO = 'EXPIRADO', 'Expirado'

class ExamAttempt(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    template = models.ForeignKey(ExamTemplate, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=ExamAttemptStatus.choices, default=ExamAttemptStatus.EN_CURSO)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)  # 0..100

class ExamQuestion(models.Model):
    attempt = models.ForeignKey(ExamAttempt, related_name='exam_questions', on_delete=models.CASCADE)
    source_question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exam_snapshots",
    )
    # Snapshot para congelar el contenido aunque cambie el banco
    reference_book = models.CharField(max_length=100, blank=True)  # agregado para mostrar imagen de examen
    image = models.ImageField(upload_to="questions/", blank=True, null=True)
    question_text = models.TextField()
    explanation = models.TextField(blank=True)
    topic = models.CharField(max_length=120, blank=True)
    difficulty = models.IntegerField(default=1)
    reference_law = models.CharField(max_length=50, blank=True)
    # Opciones snapshot
    options = models.JSONField(default=list)  # [{"text": "...", "is_correct": true/false}, ...]

class StudentAnswer(models.Model):
    exam_question = models.OneToOneField(ExamQuestion, related_name='answer', on_delete=models.CASCADE)
    selected_index = models.IntegerField(null=True, blank=True)  # índice en la lista options
    selected_indexes = models.JSONField(blank=True, default=list)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now=True)
