from django.urls import path

from .web_views import (
    OdoAccessView,
    OdoAlertsView,
    OdoDashboardView,
    OdoDocumentDeleteView,
    OdoDocumentEditView,
    OdoDocumentsView,
    OdoMaintenanceView,
    OdoVehiclesView,
)

app_name = "odo_web"

urlpatterns = [
    path("", OdoDashboardView.as_view(), name="dashboard"),
    path("vehiculos/", OdoVehiclesView.as_view(), name="vehicles"),
    path("accesos/", OdoAccessView.as_view(), name="access"),
    path("documentos/", OdoDocumentsView.as_view(), name="documents"),
    path("documentos/<int:pk>/editar/", OdoDocumentEditView.as_view(), name="document-edit"),
    path("documentos/<int:pk>/eliminar/", OdoDocumentDeleteView.as_view(), name="document-delete"),
    path("alertas/", OdoAlertsView.as_view(), name="alerts"),
    path("mantenciones/", OdoMaintenanceView.as_view(), name="maintenance"),
]
