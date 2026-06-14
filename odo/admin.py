from django.contrib import admin

from .models import (
    FuelEntry,
    MaintenanceAlert,
    MaintenanceRecord,
    MaintenanceSchedule,
    OdometerReading,
    Vehicle,
    VehicleAccess,
)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate", "owner", "alias", "current_odometer", "updated_at")
    list_filter = ("brand", "year")
    search_fields = ("plate", "alias", "owner__email", "owner__username")


@admin.register(VehicleAccess)
class VehicleAccessAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("vehicle__plate", "user__email", "user__username")


@admin.register(OdometerReading)
class OdometerReadingAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "date", "odometer", "source", "created_by", "created_at")
    list_filter = ("source", "date")
    search_fields = ("vehicle__plate",)


@admin.register(FuelEntry)
class FuelEntryAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "date", "odometer", "liters", "total_cost", "created_by")
    list_filter = ("date",)
    search_fields = ("vehicle__plate",)


@admin.register(MaintenanceSchedule)
class MaintenanceScheduleAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "name", "due_odometer", "due_date", "status")
    list_filter = ("status", "due_date")
    search_fields = ("vehicle__plate", "name")


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "name", "date", "odometer", "cost", "created_by")
    list_filter = ("date",)
    search_fields = ("vehicle__plate", "name")


@admin.register(MaintenanceAlert)
class MaintenanceAlertAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "schedule", "kind", "severity", "status", "created_at")
    list_filter = ("kind", "severity", "status", "created_at")
    search_fields = ("vehicle__plate", "schedule__name", "message")
