from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class ConceptoGasto(models.Model):
    class Origen(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        AUTOMATICO = "AUTOMATICO", "Automatico"

    nombre = models.CharField(max_length=80, unique=True)
    origen = models.CharField(
        max_length=12,
        choices=Origen.choices,
        default=Origen.MANUAL,
    )
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre"]
        verbose_name = "Concepto de gasto"
        verbose_name_plural = "Conceptos de gasto"

    def __str__(self):
        return self.nombre


class GastoMensual(models.Model):
    concepto = models.ForeignKey(
        ConceptoGasto,
        on_delete=models.PROTECT,
        related_name="gastos_mensuales",
    )
    anio = models.PositiveSmallIntegerField(default=timezone.localdate().year)
    mes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    monto = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    observacion = models.CharField(max_length=240, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="balance_gastos_actualizados",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-anio", "mes", "concepto__orden", "concepto__nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["concepto", "anio", "mes"],
                name="unique_gasto_mensual_por_concepto",
            ),
            models.CheckConstraint(
                condition=models.Q(mes__gte=1, mes__lte=12),
                name="gasto_mensual_mes_valido",
            ),
        ]
        verbose_name = "Gasto mensual"
        verbose_name_plural = "Gastos mensuales"

    def __str__(self):
        return f"{self.concepto} {self.mes}/{self.anio}: {self.monto}"
