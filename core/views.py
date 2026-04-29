from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    ExamAttempt,
    ExamAttemptStatus,
    ExamQuestion,
    ExamTemplate,
    Question,
)
from .serializers import (
    AnswerExamSerializer,
    ExamAttemptSerializer,
    QuestionSerializer,
    StartExamSerializer,
)
from .services import (
    check_and_expire_attempt,
    generate_exam_attempt,
    get_remaining_seconds,
    grade_attempt,
    grade_single_answer,
    user_has_active_exam_access,
)


class QuestionViewSet(viewsets.ModelViewSet):
    queryset = Question.objects.all().select_related("topic").prefetch_related("options")
    serializer_class = QuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]


class ExamAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ExamAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            ExamAttempt.objects.filter(student=self.request.user)
            .select_related("template")
            .prefetch_related("exam_questions")
            .order_by("-started_at")
        )

    def list(self, request, *args, **kwargs):
        queryset = list(self.filter_queryset(self.get_queryset()))
        for attempt in queryset:
            check_and_expire_attempt(attempt)
        serializer = self.get_serializer(
            queryset,
            many=True,
            context={**self.get_serializer_context(), "include_feedback": False},
        )
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        check_and_expire_attempt(instance)
        include_feedback = (
            instance.template.show_feedback
            and instance.status == ExamAttemptStatus.ENTREGADO
        )
        serializer = self.get_serializer(
            instance,
            context={
                **self.get_serializer_context(),
                "include_feedback": include_feedback,
                "remaining_seconds": get_remaining_seconds(instance),
            },
        )
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["post"],
        url_path="start",
        serializer_class=StartExamSerializer,
    )
    def start(self, request):
        if not user_has_active_exam_access(request.user):
            return Response(
                {"detail": "Tu acceso a examenes no esta activo. Ingresa tu codigo de activacion."},
                status=status.HTTP_403_FORBIDDEN,
            )
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        template = input_serializer.validated_data["template"]

        try:
            attempt = generate_exam_attempt(request.user, template)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ExamAttemptSerializer(
            attempt,
            context={**self.get_serializer_context(), "include_feedback": False},
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["post"],
        url_path="answer",
        serializer_class=AnswerExamSerializer,
    )
    def answer(self, request, pk=None):
        if not user_has_active_exam_access(request.user):
            return Response(
                {"detail": "Tu acceso a examenes no esta activo. Ingresa tu codigo de activacion."},
                status=status.HTTP_403_FORBIDDEN,
            )
        attempt = self.get_object()
        if check_and_expire_attempt(attempt):
            return Response(
                {"detail": "El examen ha expirado por tiempo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if attempt.status == ExamAttemptStatus.ENTREGADO:
            return Response(
                {"detail": "El examen ya fue finalizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(
            data=request.data,
            context={**self.get_serializer_context(), "attempt": attempt},
        )
        serializer.is_valid(raise_exception=True)
        eq = serializer.validated_data["exam_question"]
        selected_indexes = serializer.validated_data["selected_indexes"]

        try:
            feedback = grade_single_answer(
                eq,
                selected_indexes,
                include_feedback=attempt.template.show_feedback,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(feedback, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="finish")
    def finish(self, request, pk=None):
        if not user_has_active_exam_access(request.user):
            return Response(
                {"detail": "Tu acceso a examenes no esta activo. Ingresa tu codigo de activacion."},
                status=status.HTTP_403_FORBIDDEN,
            )
        attempt = self.get_object()
        if check_and_expire_attempt(attempt):
            return Response(
                {"detail": "El examen ha expirado por tiempo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if attempt.status == ExamAttemptStatus.ENTREGADO:
            return Response(
                {"detail": "El examen ya fue finalizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        unanswered = [
            eq
            for eq in attempt.exam_questions.all()
            if not getattr(eq, "answer", None)
            or (
                not eq.answer.selected_indexes
                and eq.answer.selected_index is None
            )
        ]
        if unanswered:
            return Response(
                {"detail": f"Quedan {len(unanswered)} preguntas sin responder."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        score = grade_attempt(attempt)
        serializer = self.get_serializer(
            attempt,
            context={
                **self.get_serializer_context(),
                "include_feedback": attempt.template.show_feedback,
            },
        )
        return Response(
            {"score": score, "exam_attempt": serializer.data},
            status=status.HTTP_200_OK,
        )
