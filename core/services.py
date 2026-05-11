import random
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    ExamAttempt,
    ExamAttemptStatus,
    ExamQuestion,
    Profile,
    Question,
    StudentAnswer,
)

EARLY_EXAM_LIMIT = 18
EARLY_FAILED_REVIEW_RATIO = 0.2
LATE_FAILED_REVIEW_RATIO = 0.5


def user_has_active_exam_access(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    profile = getattr(user, "profile", None)
    if profile is None:
        profile, _ = Profile.objects.get_or_create(user=user)
    return profile.has_active_exam_access()


def _question_key_from_exam_question(exam_question):
    if exam_question.source_question_id:
        return ("source", exam_question.source_question_id)
    return ("text", exam_question.question_text.strip())


def _normalized_question_text(text):
    return " ".join((text or "").split()).casefold()


def _unique_question_count(pool):
    return len({_normalized_question_text(question.text) for question in pool})


def _topic_name_from_exam_question(exam_question, known_topic_names=None):
    source_question = getattr(exam_question, "source_question", None)
    source_topic = getattr(source_question, "topic", None)
    if source_topic:
        return source_topic.name
    snapshot_topic = exam_question.topic or ""
    if snapshot_topic and (
        known_topic_names is None or snapshot_topic in known_topic_names
    ):
        return snapshot_topic
    return "Sin clasificar"


def _get_student_practice_state(student):
    delivered_attempts = (
        ExamAttempt.objects.filter(
            student=student,
            status=ExamAttemptStatus.ENTREGADO,
        )
        .order_by("started_at", "id")
        .prefetch_related("exam_questions__answer", "exam_questions__source_question")
    )
    seen_source_ids = set()
    latest_by_question = {}

    for attempt in delivered_attempts:
        for exam_question in attempt.exam_questions.all():
            answer = getattr(exam_question, "answer", None)
            if answer is None:
                continue
            if exam_question.source_question_id:
                seen_source_ids.add(exam_question.source_question_id)
            latest_by_question[_question_key_from_exam_question(exam_question)] = answer.is_correct

    failed_source_ids = {
        key[1]
        for key, is_correct in latest_by_question.items()
        if key[0] == "source" and not is_correct
    }
    return {
        "seen_source_ids": seen_source_ids,
        "failed_source_ids": failed_source_ids,
        "delivered_attempt_count": delivered_attempts.count(),
    }


def _sample_without_repeating(pool, count, selected_ids, selected_texts):
    available = [
        question
        for question in pool
        if question.id not in selected_ids
        and _normalized_question_text(question.text) not in selected_texts
    ]
    if count <= 0 or not available:
        return []

    shuffled = random.sample(available, k=len(available))
    sample = []
    sample_texts = set()
    for question in shuffled:
        text_key = _normalized_question_text(question.text)
        if text_key in sample_texts:
            continue
        sample.append(question)
        sample_texts.add(text_key)
        if len(sample) == count:
            break
    return sample


def _select_practice_questions(pool, question_count, student):
    state = _get_student_practice_state(student)
    selected = []
    selected_ids = set()
    selected_texts = set()

    failed_ratio = (
        EARLY_FAILED_REVIEW_RATIO
        if state["delivered_attempt_count"] < EARLY_EXAM_LIMIT
        else LATE_FAILED_REVIEW_RATIO
    )
    target_failed_count = int(round(question_count * failed_ratio))

    failed_pool = [
        question for question in pool if question.id in state["failed_source_ids"]
    ]
    failed_selection = _sample_without_repeating(
        failed_pool,
        target_failed_count,
        selected_ids,
        selected_texts,
    )
    selected.extend(failed_selection)
    selected_ids.update(question.id for question in failed_selection)
    selected_texts.update(
        _normalized_question_text(question.text) for question in failed_selection
    )

    missing_count = question_count - len(selected)
    unseen_pool = [
        question
        for question in pool
        if question.id not in state["seen_source_ids"] and question.id not in selected_ids
        and _normalized_question_text(question.text) not in selected_texts
    ]
    unseen_selection = _sample_without_repeating(
        unseen_pool,
        missing_count,
        selected_ids,
        selected_texts,
    )
    selected.extend(unseen_selection)
    selected_ids.update(question.id for question in unseen_selection)
    selected_texts.update(
        _normalized_question_text(question.text) for question in unseen_selection
    )

    missing_count = question_count - len(selected)
    fill_selection = _sample_without_repeating(
        pool,
        missing_count,
        selected_ids,
        selected_texts,
    )
    selected.extend(fill_selection)

    random.shuffle(selected)
    return selected


@transaction.atomic
def generate_exam_attempt(student, template, topic=None):
    if student is None:
        raise ValueError("Se requiere un usuario autenticado para iniciar el examen.")

    existing_attempt = get_active_attempt_for_template(student, template)
    if existing_attempt is not None:
        raise ValueError(
            "Ya tienes un examen en curso para esta plantilla. Reanudalo desde tu panel."
        )

    questions = (
        Question.objects.filter(is_active=True)
        .select_related("topic")
        .prefetch_related("options")
    )
    if topic is not None:
        questions = questions.filter(topic=topic)
    pool = list(questions)
    if topic is not None:
        if not pool:
            raise ValueError(f"No hay preguntas disponibles en el tema {topic.name}.")
        if _unique_question_count(pool) < template.total_questions:
            selected_ids = {question.id for question in pool}
            complementary_pool = list(
                Question.objects.filter(
                    is_active=True,
                    topic__question__is_active=True,
                )
                .exclude(pk__in=selected_ids)
                .select_related("topic")
                .prefetch_related("options")
                .annotate(
                    active_topic_questions=Count(
                        "topic__question",
                        filter=Q(topic__question__is_active=True),
                    )
                )
                .filter(active_topic_questions__lt=template.total_questions)
                .distinct()
            )
            pool.extend(complementary_pool)
        question_count = min(template.total_questions, _unique_question_count(pool))
    else:
        if _unique_question_count(pool) < template.total_questions:
            raise ValueError(
                "No hay suficientes preguntas unicas disponibles para generar el examen."
            )
        question_count = template.total_questions

    attempt = ExamAttempt.objects.create(student=student, template=template)
    selected = _select_practice_questions(pool, question_count, student)
    for q in selected:
        opts = list(q.options.all())
        random.shuffle(opts)
        options_payload = [{"text": o.text, "is_correct": o.is_correct} for o in opts]
        ExamQuestion.objects.create(
            attempt=attempt,
            source_question=q,
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
            source_question=question.source_question,
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


def get_student_exam_progress(student):
    active_question_count = Question.objects.filter(is_active=True).count()
    active_topic_counts = {
        item["topic__name"] or "Sin tema": item["total"]
        for item in Question.objects.filter(is_active=True)
        .values("topic__name")
        .annotate(total=Count("id"))
    }
    active_topic_names = set(active_topic_counts)
    attempts = (
        ExamAttempt.objects.filter(
            student=student,
            status=ExamAttemptStatus.ENTREGADO,
        )
        .order_by("started_at", "id")
        .prefetch_related("exam_questions__answer", "exam_questions__source_question__topic")
    )

    answered = 0
    correct = 0
    seen_keys = set()
    seen_topic_keys = defaultdict(set)
    topic_stats = defaultdict(lambda: {"topic": "", "answered": 0, "correct": 0})
    latest_by_question = {}

    for attempt in attempts:
        for exam_question in attempt.exam_questions.all():
            answer = getattr(exam_question, "answer", None)
            if answer is None:
                continue

            topic_name = _topic_name_from_exam_question(exam_question, active_topic_names)
            question_key = _question_key_from_exam_question(exam_question)
            answered += 1
            if answer.is_correct:
                correct += 1

            seen_keys.add(question_key)
            seen_topic_keys[topic_name].add(question_key)
            topic_stats[topic_name]["topic"] = topic_name
            topic_stats[topic_name]["answered"] += 1
            topic_stats[topic_name]["correct"] += 1 if answer.is_correct else 0
            latest_by_question[question_key] = {
                "is_correct": answer.is_correct,
                "topic": topic_name,
                "text": exam_question.question_text,
            }

    general_percent = int(round((correct / answered) * 100)) if answered else None
    coverage_percent = (
        int(round((len(seen_keys) / active_question_count) * 100))
        if active_question_count
        else 0
    )
    failed_pending = [
        item for item in latest_by_question.values() if not item["is_correct"]
    ]
    topics = []
    all_topic_names = set(active_topic_counts) | set(topic_stats)
    for topic_name in all_topic_names:
        stats = topic_stats[topic_name]
        topic_answered = stats["answered"]
        topic_correct = stats["correct"]
        topic_total_bank = active_topic_counts.get(topic_name, 0)
        topics.append(
            {
                "topic": topic_name,
                "answered": topic_answered,
                "correct": topic_correct,
                "percent": int(round((topic_correct / topic_answered) * 100))
                if topic_answered
                else 0,
                "coverage_percent": int(
                    round((len(seen_topic_keys[topic_name]) / topic_total_bank) * 100)
                )
                if topic_total_bank
                else 0,
                "bank_total": topic_total_bank,
            }
        )

    topics.sort(key=lambda item: (item["percent"], -item["answered"]))
    recent_scores = [
        attempt.score
        for attempt in attempts.order_by("-finished_at", "-id")[:5]
        if attempt.score is not None
    ]
    recent_average = (
        int(round(sum(recent_scores) / len(recent_scores))) if recent_scores else None
    )
    ready_for_municipal = bool(
        attempts.count() >= 20
        and coverage_percent >= 85
        and general_percent is not None
        and general_percent >= 90
        and len(failed_pending) <= 10
        and recent_scores
        and all(score >= 90 for score in recent_scores)
    )

    return {
        "answered": answered,
        "correct": correct,
        "attempt_count": attempts.count(),
        "bank_total": active_question_count,
        "seen_questions": len(seen_keys),
        "coverage_percent": min(100, coverage_percent),
        "general_percent": general_percent,
        "failed_pending_count": len(failed_pending),
        "recent_average": recent_average,
        "topics": topics,
        "weak_topics": [topic for topic in topics if topic["answered"] and topic["percent"] < 85],
        "ready_for_municipal": ready_for_municipal,
    }
