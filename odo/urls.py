from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "odo"

router = DefaultRouter()
router.register("vehicles", views.VehicleViewSet, basename="odo-vehicles")

urlpatterns = [
    path("health/", views.health, name="health"),
    path("", include(router.urls)),
]
