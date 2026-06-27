from django.urls import path

from .views import BalanceDashboardView


app_name = "balance"

urlpatterns = [
    path("", BalanceDashboardView.as_view(), name="dashboard"),
]
