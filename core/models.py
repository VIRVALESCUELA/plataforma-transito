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
    sent_to_email = models.EmailField(blank=True)
    used_by = models.ForeignKey(
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
    direccion = models.CharField(max_length=180, blank=True)
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


class FichaAlumno(models.Model):
    class FormaPago(models.TextChoices):
        EFECTIVO = "EFECTIVO", "Efectivo"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
        TARJETA = "TARJETA", "Tarjeta"
        MIXTO = "MIXTO", "Mixto"
        OTRO = "OTRO", "Otro"

    numero_ficha = models.PositiveIntegerField(unique=True, blank=True, null=True)
    inscripcion = models.OneToOneField(
        Inscripcion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ficha_alumno",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ficha_alumno",
    )
    fecha_inscripcion = models.DateField(default=timezone.localdate)
    nombre = models.CharField(max_length=150)
    correo = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    direccion = models.CharField(max_length=180, blank=True)
    curso = models.CharField(max_length=120, blank=True)
    clases_contratadas = models.PositiveSmallIntegerField(
        default=0,
        blank=True,
        help_text="Cantidad de clases practicas incluidas en el curso vendido.",
    )
    rut = models.CharField(max_length=20, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    edad = models.PositiveSmallIntegerField(null=True, blank=True)
    valor_pagado = models.PositiveIntegerField(default=0)
    forma_pago = models.CharField(
        max_length=20,
        choices=FormaPago.choices,
        blank=True,
    )
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha_inscripcion", "-numero_ficha"]
        verbose_name = "Ficha de alumno"
        verbose_name_plural = "Fichas de alumnos"

    def __str__(self):
        return f"{self.numero_ficha or 'sin ficha'} - {self.nombre}"

    @classmethod
    def next_numero_ficha(cls):
        last_number = (
            cls.objects.filter(numero_ficha__isnull=False)
            .order_by("-numero_ficha")
            .values_list("numero_ficha", flat=True)
            .first()
        )
        return (last_number or 5000) + 1

    def calcular_edad(self):
        if not self.fecha_nacimiento:
            return None
        today = timezone.localdate()
        edad = today.year - self.fecha_nacimiento.year
        birthday_passed = (today.month, today.day) >= (
            self.fecha_nacimiento.month,
            self.fecha_nacimiento.day,
        )
        return edad if birthday_passed else edad - 1

    def save(self, *args, **kwargs):
        if self.numero_ficha is None:
            self.numero_ficha = self.next_numero_ficha()
        self.edad = self.calcular_edad()
        super().save(*args, **kwargs)

    @property
    def total_pagado(self):
        movimientos_total = self.movimientos.aggregate(total=models.Sum("monto"))["total"]
        if movimientos_total is not None:
            return movimientos_total
        return self.valor_pagado

    @property
    def clases_extra_vendidas(self):
        return self.movimientos.filter(tipo=FichaMovimiento.Tipo.CLASE_EXTRA).count()

    @property
    def cupo_clases_practicas(self):
        return (self.clases_contratadas or 0) + self.clases_extra_vendidas


class FichaMovimiento(models.Model):
    class Tipo(models.TextChoices):
        CURSO = "CURSO", "Curso"
        CLASE_EXTRA = "CLASE_EXTRA", "Clase extra"
        ENSAYO_SICOTECNICO = "ENSAYO_SICOTECNICO", "Ensayo sicotecnico"
        SIMULADOR = "SIMULADOR", "Simulador"
        LIBRO = "LIBRO", "Libro"
        ABONO = "ABONO", "Abono"
        OTRO = "OTRO", "Otro"

    ficha = models.ForeignKey(
        FichaAlumno,
        on_delete=models.CASCADE,
        related_name="movimientos",
    )
    fecha = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=24, choices=Tipo.choices, default=Tipo.CURSO)
    concepto = models.CharField(max_length=120)
    monto = models.PositiveIntegerField(default=0)
    es_inicial = models.BooleanField(default=False)
    forma_pago = models.CharField(
        max_length=20,
        choices=FichaAlumno.FormaPago.choices,
        blank=True,
    )
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Movimiento de ficha"
        verbose_name_plural = "Movimientos de fichas"

    def __str__(self):
        return f"{self.ficha.numero_ficha} - {self.concepto} - {self.monto}"

    @classmethod
    def tipo_desde_concepto(cls, concepto):
        normalized = (concepto or "").casefold()
        if "extra" in normalized:
            return cls.Tipo.CLASE_EXTRA
        if "sico" in normalized or "psico" in normalized or "ensayo" in normalized:
            return cls.Tipo.ENSAYO_SICOTECNICO
        if "simulador" in normalized:
            return cls.Tipo.SIMULADOR
        if "libro" in normalized:
            return cls.Tipo.LIBRO
        if "abono" in normalized:
            return cls.Tipo.ABONO
        if normalized:
            return cls.Tipo.CURSO
        return cls.Tipo.OTRO

    @classmethod
    def sync_pago_inicial(cls, ficha):
        concepto = ficha.curso or "Pago inicial"
        defaults = {
            "fecha": ficha.fecha_inscripcion,
            "tipo": cls.tipo_desde_concepto(concepto),
            "concepto": concepto,
            "monto": ficha.valor_pagado,
            "es_inicial": True,
            "forma_pago": ficha.forma_pago,
            "observaciones": "Movimiento inicial generado desde la ficha.",
        }
        cls.objects.update_or_create(
            ficha=ficha,
            es_inicial=True,
            defaults=defaults,
        )


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
