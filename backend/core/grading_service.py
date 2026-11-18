"""Read-only pending grading scopes, shared by the queue and course overview."""
from django.db.models import OuterRef, Subquery

from .models import QuizAttempt, SubmissionVersion


def pending_assignment_versions(course_ids):
    latest = SubmissionVersion.objects.filter(submission_id=OuterRef('submission_id')).order_by('-number').values('pk')[:1]
    return SubmissionVersion.objects.filter(
        submission__assignment__course_id__in=course_ids, score__isnull=True, pk=Subquery(latest))


def pending_quiz_attempts(course_ids):
    return QuizAttempt.objects.filter(quiz__course_id__in=course_ids, status='submitted').exclude(grading_status='finalized')
