from django.urls import path

from .views import (
    ScheduleGridView,
    ScheduleMinimalGridView,
    ScheduleResourceManageView,
    ScheduleSearchView,
)

app_name = "agendamiento"

urlpatterns = [
    path("", ScheduleGridView.as_view(), name="grid"),
    path("15-dias/", ScheduleMinimalGridView.as_view(), name="minimal"),
    path("buscar/", ScheduleSearchView.as_view(), name="search"),
    path("recursos/", ScheduleResourceManageView.as_view(), name="resources"),
]
