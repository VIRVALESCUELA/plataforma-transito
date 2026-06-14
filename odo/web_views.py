from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from .forms import (
    FuelEntryForm,
    MaintenanceRecordForm,
    MaintenanceScheduleForm,
    VehicleAccessForm,
    VehicleForm,
)
from .models import (
    FuelEntry,
    MaintenanceAlertStatus,
    MaintenanceRecord,
    MaintenanceSchedule,
    MaintenanceScheduleStatus,
    OdometerReadingSource,
    Vehicle,
    VehicleAccess,
)
from .permissions import accessible_vehicles_for, user_can_use_odo
from .services import evaluate_vehicle_alerts, record_odometer


WATCHED_SCHEDULE_NAMES = {
    "oil": "Aceite motor",
    "inspection": "Revision tecnica",
    "permit": "Permiso circulacion",
}


def _fuel_entry_card(entry):
    previous_entry = (
        FuelEntry.objects.filter(
            vehicle=entry.vehicle,
            odometer__lt=entry.odometer,
        )
        .order_by("-odometer", "-date", "-created_at")
        .first()
    )
    distance = None
    performance = None
    if previous_entry:
        distance = entry.odometer - previous_entry.odometer
        if distance > 0 and entry.liters:
            performance = (Decimal(distance) / entry.liters).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
    return {
        "entry": entry,
        "previous_entry": previous_entry,
        "distance": distance,
        "performance": performance,
    }


def _next_schedule_for(vehicle, name):
    schedules = [
        schedule
        for schedule in vehicle.maintenance_schedules.all()
        if schedule.name == name
        and schedule.status
        in [MaintenanceScheduleStatus.PENDING, MaintenanceScheduleStatus.OVERDUE]
    ]
    if not schedules:
        return None
    return sorted(
        schedules,
        key=lambda schedule: (
            schedule.status != MaintenanceScheduleStatus.OVERDUE,
            schedule.due_date or date.max,
            schedule.due_odometer or 999999999,
        ),
    )[0]


class OdoStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = "/accounts/login/"

    def test_func(self):
        return user_can_use_odo(self.request.user)


class OdoContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehicles = (
            accessible_vehicles_for(self.request.user)
            .prefetch_related("maintenance_alerts", "maintenance_schedules")
            .order_by("plate")
        )
        context["vehicles"] = vehicles
        context["can_manage_vehicles"] = self.request.user.is_superuser
        context["vehicle_count"] = vehicles.count()
        context["open_alert_count"] = sum(
            vehicle.maintenance_alerts.filter(
                status=MaintenanceAlertStatus.OPEN
            ).count()
            for vehicle in vehicles
        )
        context["service_count"] = FuelEntry.objects.filter(vehicle__in=vehicles).count()
        context["vehicle_form"] = kwargs.get("vehicle_form") or VehicleForm()
        context["access_form"] = kwargs.get("access_form") or VehicleAccessForm()
        context["fuel_form"] = kwargs.get("fuel_form") or FuelEntryForm(
            user=self.request.user
        )
        context["schedule_form"] = kwargs.get(
            "schedule_form"
        ) or MaintenanceScheduleForm(user=self.request.user)
        context["record_form"] = kwargs.get("record_form") or MaintenanceRecordForm(
            user=self.request.user
        )
        context["vehicle_status_cards"] = [
            {
                "vehicle": vehicle,
                "oil_schedule": _next_schedule_for(
                    vehicle,
                    WATCHED_SCHEDULE_NAMES["oil"],
                ),
                "inspection_schedule": _next_schedule_for(
                    vehicle,
                    WATCHED_SCHEDULE_NAMES["inspection"],
                ),
                "permit_schedule": _next_schedule_for(
                    vehicle,
                    WATCHED_SCHEDULE_NAMES["permit"],
                ),
                "open_alert_count": vehicle.maintenance_alerts.filter(
                    status=MaintenanceAlertStatus.OPEN
                ).count(),
            }
            for vehicle in vehicles
        ]
        recent_fuel_entries = FuelEntry.objects.filter(
            vehicle__in=vehicles
        ).select_related("vehicle")[:5]
        context["recent_fuel_cards"] = [
            _fuel_entry_card(entry) for entry in recent_fuel_entries
        ]
        context["recent_maintenance_records"] = MaintenanceRecord.objects.filter(
            vehicle__in=vehicles
        ).select_related("vehicle")[:6]
        context["pending_schedules"] = MaintenanceSchedule.objects.filter(
            vehicle__in=vehicles,
            status__in=[
                MaintenanceScheduleStatus.PENDING,
                MaintenanceScheduleStatus.OVERDUE,
            ],
        ).select_related("vehicle")[:8]
        return context


class OdoDashboardView(OdoStaffRequiredMixin, OdoContextMixin, TemplateView):
    template_name = "odo/dashboard.html"

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")

        if action == "create_fuel":
            form = FuelEntryForm(request.POST, user=request.user)
            if form.is_valid():
                entry = form.save(created_by=request.user)
                record_odometer(
                    entry.vehicle,
                    odometer=entry.odometer,
                    source=OdometerReadingSource.FUEL,
                    date=entry.date,
                    notes=f"Carga de combustible #{entry.id}",
                    created_by=request.user,
                )
                messages.success(
                    request,
                    f"Carga registrada para {entry.vehicle.plate}.",
                )
                return redirect("odo_web:dashboard")
            messages.error(request, "Revisa los datos de combustible.")
            return self.render_to_response(self.get_context_data(fuel_form=form))

        messages.error(request, "Accion ODO no reconocida.")
        return redirect("odo_web:dashboard")


class OdoVehiclesView(OdoStaffRequiredMixin, OdoContextMixin, TemplateView):
    template_name = "odo/vehicles.html"

    def post(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Solo el superusuario puede registrar vehiculos.")
            return redirect("odo_web:vehicles")
        form = VehicleForm(request.POST, owner=request.user)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.owner = request.user
            vehicle.save()
            VehicleAccess.objects.get_or_create(vehicle=vehicle, user=request.user)
            evaluate_vehicle_alerts(vehicle)
            messages.success(request, f"Vehiculo {vehicle.plate} registrado.")
            return redirect("odo_web:vehicles")
        messages.error(request, "Revisa los datos del vehiculo.")
        return self.render_to_response(self.get_context_data(vehicle_form=form))


class OdoAccessView(OdoStaffRequiredMixin, OdoContextMixin, TemplateView):
    template_name = "odo/access.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Solo el superusuario puede asignar patentes.")
            return redirect("odo_web:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vehicle_accesses"] = (
            VehicleAccess.objects.select_related("vehicle", "user")
            .order_by("vehicle__plate", "user__email", "user__username")
        )
        return context

    def post(self, request, *args, **kwargs):
        form = VehicleAccessForm(request.POST)
        if form.is_valid():
            access, created = VehicleAccess.objects.get_or_create(
                vehicle=form.cleaned_data["vehicle"],
                user=form.cleaned_data["user"],
            )
            if created:
                messages.success(
                    request,
                    f"Patente {access.vehicle.plate} asignada a {access.user.get_full_name() or access.user.email or access.user.username}.",
                )
            else:
                messages.info(request, "Ese staff ya tenia acceso a esa patente.")
            return redirect("odo_web:access")
        messages.error(request, "Revisa la asignacion de patente.")
        return self.render_to_response(self.get_context_data(access_form=form))


class OdoAlertsView(OdoStaffRequiredMixin, OdoContextMixin, TemplateView):
    template_name = "odo/alerts.html"

    def post(self, request, *args, **kwargs):
        form = MaintenanceScheduleForm(request.POST, user=request.user)
        if form.is_valid():
            schedules = form.save_many()
            vehicle = schedules[0].vehicle
            evaluate_vehicle_alerts(vehicle)
            names = ", ".join(schedule.name for schedule in schedules)
            messages.success(
                request,
                f"{len(schedules)} alerta(s) programada(s) para {vehicle.plate}: {names}.",
            )
            return redirect("odo_web:alerts")
        messages.error(request, "Revisa los datos de la mantencion.")
        return self.render_to_response(self.get_context_data(schedule_form=form))


class OdoMaintenanceView(OdoStaffRequiredMixin, OdoContextMixin, TemplateView):
    template_name = "odo/maintenance.html"

    def post(self, request, *args, **kwargs):
        form = MaintenanceRecordForm(request.POST, user=request.user)
        if form.is_valid():
            records = form.save_many(created_by=request.user)
            vehicle = records[0].vehicle
            names = ", ".join(record.name for record in records)
            record_odometer(
                vehicle,
                odometer=records[0].odometer,
                source=OdometerReadingSource.MAINTENANCE,
                date=records[0].date,
                notes=f"Mantencion registrada: {names}",
                created_by=request.user,
            )
            messages.success(
                request,
                f"{len(records)} mantencion(es) registrada(s) para {vehicle.plate}: {names}.",
            )
            return redirect("odo_web:maintenance")
        messages.error(request, "Revisa los datos del registro de mantencion.")
        return self.render_to_response(self.get_context_data(record_form=form))
