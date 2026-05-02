import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    ExamAttempt,
    ExamAttemptStatus,
    ExamQuestion,
    Profile,
    Question,
    StudentAnswer,
)


def user_has_active_exam_access(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    profile = getattr(user, "profile", None)
    if profile is None:
        profile, _ = Profile.objects.get_or_create(user=user)
    return profile.has_active_exam_access()

@transaction.atomic
def generate_exam_attempt(student, template):
    if student is None:
        raise ValueError("Se requiere un usuario autenticado para iniciar el examen.")

    existing_attempt = get_active_attempt_for_template(student, template)
    if existing_attempt is not None:
        raise ValueError(
            "Ya tienes un examen en curso para esta plantilla. Reanudalo desde tu panel."
        )

    pool = list(Question.objects.filter(is_active=True))
    if len(pool) < template.total_questions:
        raise ValueError(
            "No hay suficientes preguntas disponibles para generar el examen."
        )

    attempt = ExamAttempt.objects.create(student=student, template=template)
    selected = random.sample(pool, k=template.total_questions)
    for q in selected:
        opts = list(q.options.all())
        random.shuffle(opts)
        options_payload = [{"text": o.text, "is_correct": o.is_correct} for o in opts]
        ExamQuestion.objects.create(
            attempt=attempt,
            question_text=q.text,
            explanation=q.explanation,
            topic=q.topic.name if q.topic else '',
            difficulty=q.difficulty,
            reference_law=q.reference_law,
            reference_book=q.reference_book,
            image=q.image.name if q.image else None,
            options=options_payload,
        )
    return attempt


@transaction.atomic
def repeat_exam_attempt(original_attempt):
    if original_attempt is None:
        raise ValueError("Se requiere un examen anterior para repetir.")

    existing_attempt = get_active_attempt_for_template(
        original_attempt.student,
        original_attempt.template,
    )
    if existing_attempt is not None:
        raise ValueError(
            "Ya tienes un examen en curso para esta plantilla. Reanudalo desde tu panel."
        )

    original_questions = list(original_attempt.exam_questions.all())
    if not original_questions:
        raise ValueError("El examen anterior no tiene preguntas para repetir.")

    new_attempt = ExamAttempt.objects.create(
        student=original_attempt.student,
        template=original_attempt.template,
    )
    for question in original_questions:
        ExamQuestion.objects.create(
            attempt=new_attempt,
            reference_book=question.reference_book,
            image=question.image.name if question.image else None,
            question_text=question.question_text,
            explanation=question.explanation,
            topic=question.topic,
            difficulty=question.difficulty,
            reference_law=question.reference_law,
            options=question.options,
        )
    return new_attempt


def get_attempt_deadline(attempt):
    duration = getattr(attempt.template, "duration_minutes", 0) or 0
    if duration <= 0 or not attempt.started_at:
        return None
    return attempt.started_at + timedelta(minutes=duration)


def get_remaining_seconds(attempt):
    deadline = get_attempt_deadline(attempt)
    if deadline is None:
        return None
    remaining = int((deadline - timezone.now()).total_seconds())
    return max(0, remaining)


def get_active_attempt_for_template(student, template):
    if student is None or template is None:
        return None

    attempts = (
        ExamAttempt.objects.filter(
            student=student,
            template=template,
            status=ExamAttemptStatus.EN_CURSO,
        )
        .select_related("template")
        .order_by("-started_at")
    )

    for attempt in attempts:
        if not check_and_expire_attempt(attempt):
            return attempt
    return None


def check_and_expire_attempt(attempt) -> bool:
    """
    Devuelve True si el intento se marca como expirado por superar duration_minutes.
    """
    deadline = get_attempt_deadline(attempt)
    if deadline is None:
        return False

    if timezone.now() >= deadline and attempt.status != ExamAttemptStatus.ENTREGADO:
        attempt.status = ExamAttemptStatus.EXPIRADO
        attempt.finished_at = attempt.finished_at or timezone.now()
        attempt.save(update_fields=["status", "finished_at"])
        return True
    return False


def grade_single_answer(eq, selected_indexes, *, include_feedback=False):
    if not eq.options:
        raise ValueError("La pregunta no tiene opciones disponibles.")
    if selected_indexes is None:
        raise ValueError("Debes seleccionar al menos una opcion.")

    if not isinstance(selected_indexes, (list, tuple)):
        selected_indexes = [selected_indexes]

    try:
        normalized = [int(idx) for idx in selected_indexes]
    except (TypeError, ValueError):
        raise ValueError("Cada opcion seleccionada debe ser un numero entero.")

    if not normalized:
        raise ValueError("Debes seleccionar al menos una opcion.")

    # Remove duplicates while preserving order
    seen = set()
    filtered = []
    for idx in normalized:
        if idx not in seen:
            filtered.append(idx)
            seen.add(idx)
    normalized = filtered

    for idx in normalized:
        if idx < 0 or idx >= len(eq.options):
            raise ValueError("Indice seleccionado fuera de rango.")

    correct_indexes = [
        i for i, option in enumerate(eq.options) if option.get("is_correct")
    ]
    normalized_sorted = sorted(normalized)
    correct_sorted = sorted(correct_indexes)

    ans, _ = StudentAnswer.objects.get_or_create(exam_question=eq)
    ans.selected_index = normalized[0] if normalized else None
    ans.selected_indexes = normalized
    ans.is_correct = bool(correct_indexes) and normalized_sorted == correct_sorted
    ans.save(update_fields=["selected_index", "selected_indexes", "is_correct", "answered_at"])

    payload = {
        "exam_question_id": eq.id,
        "selected_indexes": normalized,
    }

    if include_feedback:
        payload.update(
            {
                "is_correct": ans.is_correct,
                "correct_indexes": correct_indexes,
                "explanation": eq.explanation,
                "reference_law": eq.reference_law,
                "reference_book": eq.reference_book,
            }
        )
    else:
        payload["detail"] = "Respuesta registrada."

    return payload

def grade_attempt(attempt):
    correct = 0
    total = attempt.exam_questions.count()
    for eq in attempt.exam_questions.all():
        ans = getattr(eq, 'answer', None)
        if ans and ans.is_correct:
            correct += 1
    score = int(round((correct / max(1, total)) * 100))
    attempt.score = score
    attempt.status = ExamAttemptStatus.ENTREGADO
    attempt.finished_at = timezone.now()
    attempt.save(update_fields=['score', 'status', 'finished_at'])
    return score
