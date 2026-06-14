from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def normalize_plate(value):
    return "".join((value or "").strip().upper().replace("-", "").split())


def validate_plate(value):
    plate = normalize_plate(value)
    if len(plate) != 6 or not plate.isalnum():
        raise ValidationError("La patente debe tener 6 caracteres, sin espacios ni guiones.")
    if not (
        (plate[:4].isalpha() and plate[4:].isdigit())
        or (plate[:2].isalpha() and plate[2:].isdigit())
    ):
        raise ValidationError("Usa formato chileno: ABCD12 o AB1234.")


class Vehicle(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="odo_vehicles",
    )
    plate = models.CharField(max_length=10, validators=[validate_plate])
    alias = models.CharField(max_length=40, blank=True)
    brand = models.CharField(max_length=40, blank=True)
    model = models.CharField(max_length=40, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    current_odometer = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["plate"]
        constraints = [
            models.UniqueConstraint(
                fields=["plate"],
                name="unique_odo_vehicle_plate",
            )
        ]

    def save(self, *args, **kwargs):
        self.plate = normalize_plate(self.plate)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.plate


class VehicleAccess(models.Model):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="staff_access",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="odo_vehicle_access",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["vehicle__plate", "user__email", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle", "user"],
                name="unique_odo_vehicle_access_per_user",
            )
        ]
        verbose_name = "Acceso ODO por patente"
        verbose_name_plural = "Accesos ODO por patente"

    def __str__(self):
        return f"{self.user} -> {self.vehicle.plate}"


class OdometerReadingSource(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    FUEL = "FUEL", "Carga de combustible"
    MAINTENANCE = "MAINTENANCE", "Mantenimiento"


class OdometerReading(models.Model):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="odometer_readings",
    )
    date = models.DateField(default=timezone.localdate)
    odometer = models.PositiveIntegerField()
    source = models.CharField(
        max_length=16,
        choices=OdometerReadingSource.choices,
        default=OdometerReadingSource.MANUAL,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="odo_readings_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.vehicle.plate}: {self.odometer} km"


class FuelEntry(models.Model):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="fuel_entries",
    )
    date = models.DateField(default=timezone.localdate)
    odometer = models.PositiveIntegerField()
    liters = models.DecimalField(max_digits=8, decimal_places=2)
    price_per_liter = models.DecimalField(max_digits=10, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="odo_fuel_entries_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "Carga de combustible"
        verbose_name_plural = "Cargas de combustible"

    def __str__(self):
        return f"{self.vehicle.plate}: {self.liters} L"


class MaintenanceScheduleStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    DONE = "DONE", "Realizado"
    OVERDUE = "OVERDUE", "Vencido"
    CANCELED = "CANCELED", "Cancelado"


class MaintenanceSchedule(models.Model):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="maintenance_schedules",
    )
    name = models.CharField(max_length=120)
    due_odometer = models.PositiveIntegerField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        choices=MaintenanceScheduleStatus.choices,
        default=MaintenanceScheduleStatus.PENDING,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "due_odometer", "name"]

    def __str__(self):
        return f"{self.vehicle.plate}: {self.name}"


class MaintenanceRecord(models.Model):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="maintenance_records",
    )
    schedule = models.ForeignKey(
        MaintenanceSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="records",
    )
    name = models.CharField(max_length=120)
    date = models.DateField(default=timezone.localdate)
    odometer = models.PositiveIntegerField()
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="odo_maintenance_records_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "Mantenimiento realizado"
        verbose_name_plural = "Mantenimientos realizados"

    def __str__(self):
        return f"{self.vehicle.plate}: {self.name}"


class MaintenanceAlertKind(models.TextChoices):
    DATE = "DATE", "Fecha"
    ODOMETER = "ODOMETER", "Kilometraje"


class MaintenanceAlertSeverity(models.TextChoices):
    WARNING = "WARNING", "Preventiva"
    CRITICAL = "CRITICAL", "Critica"


class MaintenanceAlertStatus(models.TextChoices):
    OPEN = "OPEN", "Abierta"
    SEEN = "SEEN", "Vista"
    DISMISSED = "DISMISSED", "Descartada"


class MaintenanceAlert(models.Model):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="maintenance_alerts",
    )
    schedule = models.ForeignKey(
        MaintenanceSchedule,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    kind = models.CharField(max_length=12, choices=MaintenanceAlertKind.choices)
    severity = models.CharField(
        max_length=12,
        choices=MaintenanceAlertSeverity.choices,
    )
    status = models.CharField(
        max_length=12,
        choices=MaintenanceAlertStatus.choices,
        default=MaintenanceAlertStatus.OPEN,
    )
    threshold_value = models.IntegerField(null=True, blank=True)
    message = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "kind", "threshold_value", "severity"],
                name="unique_odo_alert_per_schedule_threshold",
            )
        ]

    def __str__(self):
        return self.message
