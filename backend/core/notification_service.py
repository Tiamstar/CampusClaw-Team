"""Publish in the caller's transaction; never store a duplicate score/feedback payload."""
from .models import GradeNotification, Membership


def notify_assignment_grade(version):
    submission = version.submission
    course_id = submission.assignment.course_id
    if version.published_at is None or version.score is None:
        return
    if not Membership.objects.filter(course_id=course_id, user_id=submission.student_id, role='student').exists():
        return
    GradeNotification.objects.get_or_create(
        recipient_id=submission.student_id, event_key=f'assignment:{version.pk}:{version.grading_revision}',
        defaults={'course_id': course_id, 'assignment_version': version, 'grade_revision': version.grading_revision})


def notify_quiz_grades(quiz):
    students = Membership.objects.filter(course_id=quiz.course_id, role='student').values('user_id')
    batch = []
    attempts = quiz.attempts.filter(status='submitted', grading_status='finalized', student_id__in=students)
    for attempt in attempts.only('id', 'student_id', 'grade_revision').iterator(chunk_size=200):
        batch.append(GradeNotification(recipient_id=attempt.student_id, course_id=quiz.course_id,
            quiz_attempt_id=attempt.pk, grade_revision=attempt.grade_revision,
            event_key=f'quiz:{quiz.pk}:{quiz.revision}:{attempt.pk}'))
        if len(batch) == 200:
            GradeNotification.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        GradeNotification.objects.bulk_create(batch, ignore_conflicts=True)
