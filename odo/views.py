from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    FuelEntry,
    MaintenanceAlert,
    MaintenanceAlertStatus,
    MaintenanceRecord,
    MaintenanceSchedule,
    MaintenanceScheduleStatus,
    OdometerReadingSource,
    Vehicle,
    VehicleAccess,
)
from .permissions import accessible_vehicles_for
from .serializers import (
    FuelEntrySerializer,
    MaintenanceAlertSerializer,
    MaintenanceRecordSerializer,
    MaintenanceScheduleSerializer,
    OdometerReadingSerializer,
    VehicleSerializer,
    VehicleSummarySerializer,
)
from .services import evaluate_vehicle_alerts, record_odometer


class IsOdoStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


@api_view(["GET"])
@permission_classes([IsOdoStaff])
def health(request):
    return Response(
        {
            "module": "odo",
            "status": "ok",
            "user": {
                "id": request.user.id,
                "email": request.user.email,
            },
        }
    )


class VehicleViewSet(viewsets.ModelViewSet):
    serializer_class = VehicleSerializer
    permission_classes = [IsOdoStaff]

    def get_queryset(self):
        return accessible_vehicles_for(self.request.user)

    def perform_create(self, serializer):
        if not self.request.user.is_superuser:
            raise PermissionDenied("Solo el superusuario puede registrar vehiculos.")
        vehicle = serializer.save(owner=self.request.user)
        VehicleAccess.objects.get_or_create(vehicle=vehicle, user=self.request.user)

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        vehicle = self.get_object()
        evaluate_vehicle_alerts(vehicle)
        data = {
            "vehicle": vehicle,
            "latest_fuel_entry": vehicle.fuel_entries.first(),
            "open_alerts": vehicle.maintenance_alerts.filter(
                status=MaintenanceAlertStatus.OPEN
            ).select_related("schedule"),
            "pending_schedules": vehicle.maintenance_schedules.filter(
                status=MaintenanceScheduleStatus.PENDING
            ),
        }
        serializer = VehicleSummarySerializer(data)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"], url_path="odometer")
    def odometer(self, request, pk=None):
        vehicle = self.get_object()
        if request.method == "GET":
            readings = vehicle.odometer_readings.all()
            serializer = OdometerReadingSerializer(readings, many=True)
            return Response(serializer.data)

        serializer = OdometerReadingSerializer(
            data=request.data,
            context={"vehicle": vehicle},
        )
        serializer.is_valid(raise_exception=True)
        reading = record_odometer(
            vehicle,
            odometer=serializer.validated_data["odometer"],
            source=OdometerReadingSource.MANUAL,
            date=serializer.validated_data.get("date"),
            notes=serializer.validated_data.get("notes", ""),
            created_by=request.user,
        )
        output = OdometerReadingSerializer(reading)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="fuel-entries")
    def fuel_entries(self, request, pk=None):
        vehicle = self.get_object()
        if request.method == "GET":
            entries = vehicle.fuel_entries.all()
            serializer = FuelEntrySerializer(entries, many=True)
            return Response(serializer.data)

        serializer = FuelEntrySerializer(
            data=request.data,
            context={"vehicle": vehicle},
        )
        serializer.is_valid(raise_exception=True)
        entry = serializer.save(vehicle=vehicle)
        entry.created_by = request.user
        entry.save(update_fields=["created_by"])
        record_odometer(
            vehicle,
            odometer=entry.odometer,
            source=OdometerReadingSource.FUEL,
            date=entry.date,
            notes=f"Carga de combustible #{entry.id}",
            created_by=request.user,
        )
        output = FuelEntrySerializer(entry)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="maintenance-schedules")
    def maintenance_schedules(self, request, pk=None):
        vehicle = self.get_object()
        if request.method == "GET":
            schedules = vehicle.maintenance_schedules.all()
            serializer = MaintenanceScheduleSerializer(schedules, many=True)
            return Response(serializer.data)

        serializer = MaintenanceScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = serializer.save(vehicle=vehicle)
        evaluate_vehicle_alerts(vehicle)
        output = MaintenanceScheduleSerializer(schedule)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="maintenance-records")
    def maintenance_records(self, request, pk=None):
        vehicle = self.get_object()
        if request.method == "GET":
            records = vehicle.maintenance_records.all()
            serializer = MaintenanceRecordSerializer(records, many=True)
            return Response(serializer.data)

        serializer = MaintenanceRecordSerializer(
            data=request.data,
            context={"vehicle": vehicle},
        )
        serializer.is_valid(raise_exception=True)
        schedule = serializer.validated_data.get("schedule")
        if schedule is not None and schedule.vehicle_id != vehicle.id:
            return Response(
                {"detail": "La programacion no pertenece a este vehiculo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record = serializer.save(vehicle=vehicle)
        record.created_by = request.user
        record.save(update_fields=["created_by"])
        if record.schedule_id:
            record.schedule.status = MaintenanceScheduleStatus.DONE
            record.schedule.save(update_fields=["status", "updated_at"])
        record_odometer(
            vehicle,
            odometer=record.odometer,
            source=OdometerReadingSource.MAINTENANCE,
            date=record.date,
            notes=f"Mantenimiento: {record.name}",
            created_by=request.user,
        )
        output = MaintenanceRecordSerializer(record)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="alerts")
    def alerts(self, request, pk=None):
        vehicle = self.get_object()
        evaluate_vehicle_alerts(vehicle)
        alerts = vehicle.maintenance_alerts.select_related("schedule")
        serializer = MaintenanceAlertSerializer(alerts, many=True)
        return Response(serializer.data)
