from django.contrib import admin

from .models import DrivingLesson, ScheduleBlock, ScheduleOpening, ScheduleResource


@admin.register(ScheduleResource)
class ScheduleResourceAdmin(admin.ModelAdmin):
    list_display = ("name", "instructor", "vehicle", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "instructor", "vehicle")


@admin.register(DrivingLesson)
class DrivingLessonAdmin(admin.ModelAdmin):
    list_display = ("date", "slot_key", "resource", "ficha", "lesson_number", "course_kind", "status")
    list_filter = ("resource", "course_kind", "status", "date")
    search_fields = ("ficha", "notes")
    date_hierarchy = "date"


@admin.register(ScheduleBlock)
class ScheduleBlockAdmin(admin.ModelAdmin):
    list_display = ("date", "scope", "slot_key", "resource", "reason")
    list_filter = ("resource", "scope", "date")
    search_fields = ("reason",)
    date_hierarchy = "date"


@admin.register(ScheduleOpening)
class ScheduleOpeningAdmin(admin.ModelAdmin):
    list_display = ("date", "scope", "slot_key", "resource", "reason")
    list_filter = ("resource", "scope", "date")
    search_fields = ("reason",)
    date_hierarchy = "date"
