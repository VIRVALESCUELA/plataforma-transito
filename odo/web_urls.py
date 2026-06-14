from django.urls import path

from .web_views import (
    OdoAccessView,
    OdoAlertsView,
    OdoDashboardView,
    OdoMaintenanceView,
    OdoVehiclesView,
)

app_name = "odo_web"

urlpatterns = [
    path("", OdoDashboardView.as_view(), name="dashboard"),
    path("vehiculos/", OdoVehiclesView.as_view(), name="vehicles"),
    path("accesos/", OdoAccessView.as_view(), name="access"),
    path("alertas/", OdoAlertsView.as_view(), name="alerts"),
    path("mantenciones/", OdoMaintenanceView.as_view(), name="maintenance"),
]
