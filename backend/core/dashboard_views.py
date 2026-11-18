"""Bounded course overview. Reading never grades, expires attempts or calls a model."""
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .grading_service import pending_assignment_versions, pending_quiz_attempts
from .models import Assignment, ForumPost, Quiz, QuizAttempt, SubmissionVersion
from .views import fail, member


@api_view(['GET'])
def overview(request, course_id):
    membership = member(request.user, course_id)
    if not membership:
        return fail('无权访问课程', 403)
    teacher = membership.role == 'teacher'
    now = timezone.now()
    assignments = Assignment.objects.filter(course_id=course_id)
    counts = {}
    if teacher:
        counts['assignment_reviews'] = pending_assignment_versions([course_id]).count()
        counts['quiz_reviews'] = pending_quiz_attempts([course_id]).count()
        deadlines = assignments.filter(due_at__gte=now).order_by('due_at', 'pk')
    else:
        mine = SubmissionVersion.objects.filter(submission__assignment_id=OuterRef('pk'), submission__student=request.user)
        unfinished = assignments.annotate(has_submission=Exists(mine)).filter(has_submission=False)
        deadlines = unfinished.filter(Q(due_at__gte=now) | Q(allow_late=True)).annotate(
            overdue=Case(When(due_at__lt=now, then=Value(1)), default=Value(0), output_field=IntegerField())
        ).order_by('overdue', 'due_at', 'pk')
        counts['assignments_to_submit'] = deadlines.count()
        counts['missed_assignments'] = unfinished.filter(due_at__lt=now, allow_late=False).count()
    upcoming = Quiz.objects.filter(course_id=course_id, status='published', closes_at__gt=now)
    counts['open_quizzes'] = upcoming.filter(opens_at__lte=now).count()
    counts['upcoming_quizzes'] = upcoming.filter(opens_at__gt=now).count()
    # Whitelisted scalar fields only: never expose rules, answers, draft scores or identities.
    quiz_rows = list(upcoming.order_by('closes_at', 'pk').values('id', 'title', 'opens_at', 'closes_at')[:5])
    active_attempts = []
    if not teacher:
        active_attempts = list(QuizAttempt.objects.filter(
            quiz__course_id=course_id, student=request.user, status='in_progress'
        ).order_by('deadline', 'pk').values('id', 'quiz__title', 'deadline')[:5])
    posts = list(ForumPost.objects.filter(course_id=course_id).order_by('-created_at', '-pk').values(
        'id', 'title', 'created_at', 'resolved_reply_id')[:3])
    return Response({
        'role': membership.role, 'generated_at': now, 'counts': counts,
        'assignments': list(deadlines.values('id', 'title', 'due_at', 'allow_late')[:5]),
        'quizzes': quiz_rows, 'active_attempts': active_attempts, 'recent_posts': posts,
        'limits': {'assignments': 5, 'quizzes': 5, 'active_attempts': 5, 'recent_posts': 3},
    })
