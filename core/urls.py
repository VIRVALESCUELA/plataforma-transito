# core/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ExamAttemptViewSet, QuestionViewSet

router = DefaultRouter()
router.register(r'questions', QuestionViewSet, basename='questions')
router.register(r'exams', ExamAttemptViewSet, basename='exams')

urlpatterns = [
    path('', include(router.urls)),
]
