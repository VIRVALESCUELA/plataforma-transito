import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    MaintenanceAlert,
    MaintenanceAlertKind,
    MaintenanceAlertSeverity,
    MaintenanceSchedule,
    MaintenanceScheduleStatus,
    OdometerReading,
)

ODOMETER_THRESHOLDS = [500, 400, 300, 200, 100]
DATE_THRESHOLDS = [5, 4, 3, 2, 1]
EMAIL_ODOMETER_THRESHOLDS = {300, 100}
EMAIL_DATE_THRESHOLDS = {5, 1}
ODO_ALERT_NOTIFICATION_EMAIL = "virvalescuela@gmail.com"
logger = logging.getLogger(__name__)


def record_odometer(vehicle, *, odometer, source, date=None, notes="", created_by=None):
    reading_date = date or timezone.localdate()
    previous_odometer = vehicle.current_odometer
    reading = OdometerReading.objects.create(
        vehicle=vehicle,
        date=reading_date,
        odometer=odometer,
        source=source,
        notes=notes,
        created_by=created_by,
    )
    if odometer > vehicle.current_odometer:
        vehicle.current_odometer = odometer
        vehicle.save(update_fields=["current_odometer", "updated_at"])
    evaluate_vehicle_alerts(
        vehicle,
        previous_odometer=previous_odometer,
        current_date=reading_date,
    )
    return reading


def evaluate_vehicle_alerts(vehicle, *, previous_odometer=None, current_date=None):
    schedules = MaintenanceSchedule.objects.filter(
        vehicle=vehicle,
        status=MaintenanceScheduleStatus.PENDING,
    )
    created_alerts = []

    for schedule in schedules:
        created_alerts.extend(
            evaluate_schedule_alerts(
                schedule,
                current_odometer=vehicle.current_odometer,
                previous_odometer=previous_odometer,
                current_date=current_date,
            )
        )

    return [alert for alert in created_alerts if alert is not None]


def evaluate_schedule_alerts(
    schedule,
    *,
    current_odometer,
    previous_odometer=None,
    current_date=None,
):
    alerts = []
    alerts.extend(
        _evaluate_odometer_alerts(
            schedule,
            current_odometer=current_odometer,
            previous_odometer=previous_odometer,
        )
    )
    alerts.extend(_evaluate_date_alerts(schedule, current_date=current_date))
    return alerts


def _evaluate_odometer_alerts(schedule, *, current_odometer, previous_odometer=None):
    if schedule.due_odometer is None:
        return []

    current_remaining = schedule.due_odometer - current_odometer
    previous_remaining = (
        schedule.due_odometer - previous_odometer
        if previous_odometer is not None
        else None
    )

    if current_remaining <= 0:
        _mark_schedule_overdue(schedule)
        message = (
            f"Aviso de vencimiento: {schedule.name} alcanzo "
            f"{schedule.due_odometer} km."
            if current_remaining == 0
            else f"Aviso de vencimiento: {schedule.name} superado por {abs(current_remaining)} km."
        )
        return [
            _create_alert(
                schedule,
                kind=MaintenanceAlertKind.ODOMETER,
                severity=MaintenanceAlertSeverity.CRITICAL,
                threshold_value=-1,
                message=message,
            )
        ]

    crossed_thresholds = []
    for threshold in ODOMETER_THRESHOLDS:
        if previous_remaining is None:
            if current_remaining == threshold:
                crossed_thresholds.append(threshold)
        elif previous_remaining > threshold >= current_remaining:
            crossed_thresholds.append(threshold)

    alerts = [
        _create_alert(
            schedule,
            kind=MaintenanceAlertKind.ODOMETER,
            severity=MaintenanceAlertSeverity.WARNING,
            threshold_value=threshold,
            message=f"{schedule.name} vence en {threshold} km.",
        )
        for threshold in crossed_thresholds
    ]
    return [alert for alert in alerts if alert is not None]


def _evaluate_date_alerts(schedule, *, current_date=None):
    if schedule.due_date is None:
        return []

    today = current_date or timezone.localdate()
    days_remaining = (schedule.due_date - today).days

    if days_remaining <= 0:
        _mark_schedule_overdue(schedule)
        message = (
            f"Aviso de vencimiento: {schedule.name} vence hoy."
            if days_remaining == 0
            else f"Aviso de vencimiento: {schedule.name} superado hace {abs(days_remaining)} dias."
        )
        return [
            _create_alert(
                schedule,
                kind=MaintenanceAlertKind.DATE,
                severity=MaintenanceAlertSeverity.CRITICAL,
                threshold_value=-1,
                message=message,
            )
        ]

    if days_remaining not in DATE_THRESHOLDS:
        return []

    day_label = "manana" if days_remaining == 1 else f"en {days_remaining} dias"
    return [
        _create_alert(
            schedule,
            kind=MaintenanceAlertKind.DATE,
            severity=MaintenanceAlertSeverity.WARNING,
            threshold_value=days_remaining,
            message=f"{schedule.name} vence {day_label}.",
        )
    ]


def _mark_schedule_overdue(schedule):
    if schedule.status == MaintenanceScheduleStatus.OVERDUE:
        return
    schedule.status = MaintenanceScheduleStatus.OVERDUE
    schedule.save(update_fields=["status", "updated_at"])


def _create_alert(schedule, *, kind, severity, threshold_value, message):
    try:
        with transaction.atomic():
            alert = MaintenanceAlert.objects.create(
                vehicle=schedule.vehicle,
                schedule=schedule,
                kind=kind,
                severity=severity,
                threshold_value=threshold_value,
                message=message,
            )
            transaction.on_commit(lambda: _notify_alert_by_email(alert))
            return alert
    except IntegrityError:
        return None


def _notify_alert_by_email(alert):
    should_notify_warning = (
        alert.severity == MaintenanceAlertSeverity.WARNING
        and (
            (
                alert.kind == MaintenanceAlertKind.ODOMETER
                and alert.threshold_value in EMAIL_ODOMETER_THRESHOLDS
            )
            or (
                alert.kind == MaintenanceAlertKind.DATE
                and alert.threshold_value in EMAIL_DATE_THRESHOLDS
            )
        )
    )
    if alert.severity != MaintenanceAlertSeverity.CRITICAL and not should_notify_warning:
        return

    recipient = getattr(
        settings,
        "ODO_ALERT_NOTIFICATION_EMAIL",
        ODO_ALERT_NOTIFICATION_EMAIL,
    )
    vehicle = alert.vehicle
    schedule = alert.schedule
    subject = f"ODO alerta {vehicle.plate}: {schedule.name}"
    body_lines = [
        alert.message,
        "",
        f"Patente: {vehicle.plate}",
        f"Kilometraje actual: {vehicle.current_odometer} km",
        f"Vence en km: {schedule.due_odometer or 'No definido'}",
        f"Vence en fecha: {schedule.due_date or 'No definida'}",
        f"Estado: {schedule.get_status_display()}",
    ]
    if schedule.notes:
        body_lines.extend(["", "Nota de alerta:", schedule.notes])
    body = "\n".join(body_lines)
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            "No se pudo enviar la alerta ODO %s para %s.",
            alert.pk,
            vehicle.plate,
        )
