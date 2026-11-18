from decimal import Decimal

from django.db.models import Exists, F, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import GradeNotification, Membership, SubmissionVersion
from .views import fail


def visible_notifications(user):
    membership = Membership.objects.filter(user=user, course_id=OuterRef('course_id'))
    return GradeNotification.objects.filter(recipient=user).annotate(authorized=Exists(membership)).filter(
        authorized=True).filter(
            Q(assignment_version__submission__student_id=F('recipient_id'),
              assignment_version__submission__assignment__course_id=F('course_id')) |
            Q(quiz_attempt__student_id=F('recipient_id'), quiz_attempt__quiz__course_id=F('course_id')))


def notification_data(row):
    result = {'id': row.pk, 'course_id': row.course_id, 'course_name': row.course.name,
              'created_at': row.created_at, 'read_at': row.read_at, 'score': None, 'maximum': None}
    if row.assignment_version_id:
        version = row.assignment_version
        assignment = version.submission.assignment
        available = (row.latest_version_id == version.pk and version.published_at is not None and
                     version.score is not None and version.grading_revision == row.grade_revision)
        result.update(kind='assignment', title=assignment.title, assignment_id=assignment.pk,
                      availability='available' if available else 'updated', attempt_id=None, number=version.number)
        if available:
            result.update(score=str(version.score), maximum=str(assignment.max_score))
    else:
        attempt = row.quiz_attempt
        available = (attempt.quiz.grades_published and attempt.status == 'submitted' and
                     attempt.grading_status == 'finalized' and attempt.grade_revision == row.grade_revision)
        result.update(kind='quiz', title=attempt.quiz.title, assignment_id=None, attempt_id=attempt.pk,
                      availability='available' if available else 'updated', number=attempt.number)
        if available:
            result.update(score=str(sum((Decimal(str(v)) for v in attempt.scores.values()), Decimal(0))),
                          maximum=str(sum((Decimal(str(q['score'])) for q in attempt.snapshot), Decimal(0))))
    return result


@api_view(['GET'])
def inbox(request):
    try:
        page = int(request.query_params.get('page', '1'))
        if not 1 <= page <= 10000:
            raise ValueError()
    except (ValueError, TypeError):
        return fail('页码无效')
    rows = visible_notifications(request.user)
    unread = rows.filter(read_at__isnull=True).count()
    latest = SubmissionVersion.objects.filter(submission_id=OuterRef('assignment_version__submission_id')).order_by('-number').values('pk')[:1]
    rows = rows.annotate(latest_version_id=Subquery(latest)).select_related(
        'course', 'assignment_version__submission__assignment', 'quiz_attempt__quiz').order_by('-created_at', '-pk')
    batch = list(rows[(page-1)*20:page*20+1])
    return Response({'items': [notification_data(row) for row in batch[:20]],
                     'unread_count': unread, 'next_page': page+1 if len(batch) > 20 else None})


@api_view(['GET'])
def unread_count(request):
    return Response({'unread_count': visible_notifications(request.user).filter(read_at__isnull=True).count()})


@api_view(['POST'])
def mark_read(request, notification_id):
    row = get_object_or_404(visible_notifications(request.user), pk=notification_id)
    GradeNotification.objects.filter(pk=row.pk, read_at__isnull=True).update(read_at=timezone.now())
    return Response({'id': row.pk, 'read': True})


@api_view(['POST'])
def mark_all_read(request):
    count = visible_notifications(request.user).filter(read_at__isnull=True).update(read_at=timezone.now())
    return Response({'marked_count': count})
