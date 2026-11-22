"""Retained synthetic publication experiment using the authorized accounts, no model calls."""
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import GradeNotification, Membership, QuizAttempt, SubmissionVersion, User


class Command(BaseCommand):
    help = 'Create and retain clearly labelled assignment/quiz grade-notification acceptance data.'

    def add_arguments(self, parser):
        parser.add_argument('--retain-data', action='store_true')
        parser.add_argument('--teacher-email', required=True)
        parser.add_argument('--student-email', required=True)
        parser.add_argument('--course-id', required=True, type=int)
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        if not options['retain_data']:
            raise CommandError('Explicit --retain-data is required; this command never cleans up teaching data')
        teacher = User.objects.get(email=options['teacher_email'])
        student = User.objects.get(email=options['student_email'])
        course_id = options['course_id']
        for user, role in [(teacher, 'teacher'), (student, 'student')]:
            if not Membership.objects.filter(course_id=course_id, user=user, role=role).exists():
                raise CommandError('Authorized teacher and student course membership required')
        output = Path(options['output'])
        if output.exists():
            raise CommandError('Use a new output file; existing evidence must not be overwritten')
        evidence = {'passed': False, 'retained': True, 'transport': 'Django APIClient',
                    'model_calls': False, 'course_id': course_id, 'ids': {}}
        with output.open('x', encoding='utf-8') as handle:
            json.dump(evidence, handle)
        tc, sc = APIClient(), APIClient()
        tc.force_authenticate(teacher); sc.force_authenticate(student)
        previous_versions = list(SubmissionVersion.objects.order_by('pk').values_list('pk', 'score', 'grading_revision', 'published_at'))
        previous_attempts = list(QuizAttempt.objects.order_by('pk').values_list('pk', 'scores', 'feedback', 'grade_revision', 'grading_status'))

        def call(client, method, path, data=None, expected=200):
            response = getattr(client, method)('/api/'+path, data or {}, format='json', HTTP_HOST='localhost')
            if response.status_code != expected:
                raise CommandError(f'Acceptance request failed ({method} {path}: {response.status_code})')
            return response.data

        def retain(name, value):
            evidence['ids'][name] = value
            output.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            return value

        try:
            now = timezone.now()
            aid = retain('assignment', call(tc, 'post', f'courses/{course_id}/assignments/', {
                'title': '【通知验收·合成数据】成绩发布、撤回与重新公开',
                'description': '仅用于站内通知工程验证。合成答案和85分不是实际课程评价；保留供检查。',
                'due_at': (now+timedelta(days=7)).isoformat(), 'max_score': '100'}, 201)['id'])
            vid = retain('version', call(sc, 'post', f'assignments/{aid}/submit/', {
                'text_content': '合成验收提交：检查成绩通知、已读状态和详情跳转。'}, 201)['id'])
            call(tc, 'post', f'submission-versions/{vid}/grade/', {
                'score': '85', 'feedback': '合成验收评分，仅验证通知，不代表真实学习评价。',
                'reason': '通知工程验收', 'expected_revision': 0, 'published': False})
            assert not GradeNotification.objects.filter(assignment_version_id=vid).exists()
            call(tc, 'post', f'submission-versions/{vid}/publication/', {'published': True, 'expected_revision': 1})
            call(tc, 'post', f'submission-versions/{vid}/publication/', {'published': True, 'expected_revision': 2})
            assert GradeNotification.objects.filter(assignment_version_id=vid).count() == 1
            call(tc, 'post', f'submission-versions/{vid}/publication/', {'published': False, 'expected_revision': 2})
            rows = call(sc, 'get', 'notifications/')['items']
            assert next(row for row in rows if row['assignment_id'] == aid)['score'] is None
            call(tc, 'post', f'submission-versions/{vid}/publication/', {'published': True, 'expected_revision': 3})
            qid = retain('question', call(tc, 'post', f'courses/{course_id}/questions/', {
                'kind': 'blank', 'body': '【通知验收·合成题】1+1等于多少？',
                'options': [], 'answer': {'values': ['2']}, 'explanation': '合成样本，仅验证客观判分后发布通知。'}, 201)['id'])
            quiz_id = retain('quiz', call(tc, 'post', f'courses/{course_id}/quizzes/', {
                'title': '【通知验收·合成数据】单题测验成绩通知',
                'opens_at': (now-timedelta(minutes=1)).isoformat(), 'closes_at': (now+timedelta(days=3)).isoformat(),
                'answers_at': (now+timedelta(days=3)).isoformat(), 'question_ids': [qid],
                'question_scores': {str(qid): '10'}, 'time_limit_minutes': 30, 'max_attempts': 1}, 201)['id'])
            call(tc, 'post', f'quizzes/{quiz_id}/publish/', {'action': 'publish'})
            attempt_id = retain('attempt', call(sc, 'post', f'quizzes/{quiz_id}/attempts/', {}, 201)['id'])
            call(sc, 'put', f'quiz-attempts/{attempt_id}/answers/', {
                'key': 'notification-acceptance', 'expected_revision': 0, 'answers': {str(qid): '2'}})
            call(sc, 'post', f'quiz-attempts/{attempt_id}/submit/')
            call(tc, 'post', f'quizzes/{quiz_id}/publish/', {'action': 'grades_publish'})
            call(tc, 'post', f'quizzes/{quiz_id}/publish/', {'action': 'grades_publish'})
            assert GradeNotification.objects.filter(quiz_attempt_id=attempt_id).count() == 1
            rows = call(sc, 'get', 'notifications/')['items']
            assert Decimal(next(row for row in rows if row['attempt_id'] == attempt_id)['score']) == Decimal('10')
            assert list(SubmissionVersion.objects.filter(pk__in=[v[0] for v in previous_versions]).order_by('pk').values_list(
                'pk', 'score', 'grading_revision', 'published_at')) == previous_versions
            assert list(QuizAttempt.objects.filter(pk__in=[a[0] for a in previous_attempts]).order_by('pk').values_list(
                'pk', 'scores', 'feedback', 'grade_revision', 'grading_status')) == previous_attempts
            evidence.update(passed=True, existing_grades_unchanged=True,
                notifications=list(GradeNotification.objects.filter(recipient=student, course_id=course_id).filter(
                    assignment_version_id=vid).values_list('pk', flat=True)) + list(
                    GradeNotification.objects.filter(quiz_attempt_id=attempt_id).values_list('pk', flat=True)))
        finally:
            output.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps({'passed': True, 'retained': True, 'course_id': course_id, 'ids': evidence['ids']}))
