from django.urls import path
from django.views.generic import RedirectView

from .web_views import (
    BlogView,
    CourseActivationView,
    ExamAttemptDetailView,
    ExamDashboardView,
    InscripcionCreateView,
    InscripcionManagementView,
    LandingView,
    StudentsLandingView,
)

app_name = "core_web"

urlpatterns = [
    path("", LandingView.as_view(), name="landing"),
    path("alumnos/", StudentsLandingView.as_view(), name="alumnos"),
    path("alumnos/activar/", CourseActivationView.as_view(), name="activate-course"),
    path("blog/", BlogView.as_view(), name="blog"),
    path("inscripcion/", InscripcionCreateView.as_view(), name="inscripcion"),
    path("panel/inscripciones/", InscripcionManagementView.as_view(), name="manage-inscripciones"),
    path("panel/", ExamDashboardView.as_view(), name="dashboard"),
    path("panel/attempts/<int:pk>/", ExamAttemptDetailView.as_view(), name="attempt-detail"),
    path(
        "attempts/<int:pk>/",
        RedirectView.as_view(pattern_name="core_web:attempt-detail", permanent=False),
        name="attempt-detail-legacy",
    ),
]
