from decimal import Decimal

from rest_framework import serializers

from .models import (
    FuelEntry,
    MaintenanceAlert,
    MaintenanceRecord,
    MaintenanceSchedule,
    OdometerReading,
    Vehicle,
    normalize_plate,
    validate_plate,
)


class VehicleSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = Vehicle
        fields = [
            "id",
            "owner_email",
            "plate",
            "alias",
            "brand",
            "model",
            "year",
            "current_odometer",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["current_odometer", "created_at", "updated_at"]

    def validate_plate(self, value):
        plate = normalize_plate(value)
        validate_plate(plate)
        return plate


class OdometerReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = OdometerReading
        fields = ["id", "date", "odometer", "source", "notes", "created_at"]
        read_only_fields = ["source", "created_at"]

    def validate_odometer(self, value):
        vehicle = self.context.get("vehicle")
        if vehicle is not None and value < vehicle.current_odometer:
            raise serializers.ValidationError(
                f"El kilometraje no puede ser menor al actual ({vehicle.current_odometer} km)."
            )
        return value


class FuelEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = FuelEntry
        fields = [
            "id",
            "date",
            "odometer",
            "liters",
            "price_per_liter",
            "total_cost",
            "notes",
            "created_at",
        ]
        read_only_fields = ["price_per_liter", "created_at"]

    def validate(self, attrs):
        vehicle = self.context.get("vehicle")
        odometer = attrs.get("odometer")
        liters = attrs.get("liters")
        total_cost = attrs.get("total_cost")
        if (
            vehicle is not None
            and odometer is not None
            and odometer < vehicle.current_odometer
        ):
            raise serializers.ValidationError(
                {
                    "odometer": f"El kilometraje no puede ser menor al actual ({vehicle.current_odometer} km)."
                }
            )
        if liters is not None and liters <= 0:
            raise serializers.ValidationError(
                {"liters": "Los litros deben ser mayores a cero."}
            )
        if total_cost is not None and total_cost < 0:
            raise serializers.ValidationError(
                {"total_cost": "El monto cargado no puede ser negativo."}
            )
        return attrs

    def create(self, validated_data):
        validated_data["price_per_liter"] = (
            validated_data["total_cost"] / validated_data["liters"]
        ).quantize(Decimal("0.01"))
        return super().create(validated_data)


class MaintenanceScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceSchedule
        fields = [
            "id",
            "name",
            "due_odometer",
            "due_date",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "created_at", "updated_at"]

    def validate(self, attrs):
        due_odometer = attrs.get("due_odometer")
        due_date = attrs.get("due_date")
        if self.instance is not None:
            due_odometer = due_odometer if due_odometer is not None else self.instance.due_odometer
            due_date = due_date if due_date is not None else self.instance.due_date
        if due_odometer is None and due_date is None:
            raise serializers.ValidationError(
                "Debes indicar kilometraje, fecha o ambos para programar el mantenimiento."
            )
        return attrs


class MaintenanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceRecord
        fields = [
            "id",
            "schedule",
            "name",
            "date",
            "odometer",
            "cost",
            "notes",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_odometer(self, value):
        vehicle = self.context.get("vehicle")
        if vehicle is not None and value < vehicle.current_odometer:
            raise serializers.ValidationError(
                f"El kilometraje no puede ser menor al actual ({vehicle.current_odometer} km)."
            )
        return value


class MaintenanceAlertSerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(source="schedule.name", read_only=True)

    class Meta:
        model = MaintenanceAlert
        fields = [
            "id",
            "schedule",
            "schedule_name",
            "kind",
            "severity",
            "status",
            "threshold_value",
            "message",
            "created_at",
        ]
        read_only_fields = [
            "schedule",
            "schedule_name",
            "kind",
            "severity",
            "threshold_value",
            "message",
            "created_at",
        ]


class VehicleSummarySerializer(serializers.Serializer):
    vehicle = VehicleSerializer()
    latest_fuel_entry = FuelEntrySerializer(allow_null=True)
    open_alerts = MaintenanceAlertSerializer(many=True)
    pending_schedules = MaintenanceScheduleSerializer(many=True)
