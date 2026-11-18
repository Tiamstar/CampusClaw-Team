from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Assignment, Course, GradeNotification, Membership, Quiz, QuizAttempt,
                     Submission, SubmissionVersion, User)
from .notification_service import notify_assignment_grade, notify_quiz_grades


class GradeNotificationTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('notice-teacher@example.test', 'test-only')
        self.student = User.objects.create_user('notice-student@example.test', 'test-only')
        self.peer = User.objects.create_user('notice-peer@example.test', 'test-only')
        self.course = Course.objects.create(name='Course', created_by=self.teacher)
        for user, role in [(self.teacher, 'teacher'), (self.student, 'student'), (self.peer, 'student')]:
            Membership.objects.create(course=self.course, user=user, role=role)
        self.tc, self.sc, self.pc = [self.client_for(user) for user in [self.teacher, self.student, self.peer]]
        now = timezone.now()
        self.assignment = Assignment.objects.create(course=self.course, title='Assignment', due_at=now+timedelta(days=1))
        self.submission = Submission.objects.create(assignment=self.assignment, student=self.student)
        self.version = SubmissionVersion.objects.create(submission=self.submission, number=1, text_content='PRIVATE_ANSWER')
        self.quiz = Quiz.objects.create(course=self.course, title='Quiz', status='published', opens_at=now-timedelta(hours=1),
            closes_at=now+timedelta(hours=1), answers_at=now+timedelta(hours=1))

    def client_for(self, user):
        client = APIClient(); client.force_authenticate(user); return client

    def grade(self, published=False, revision=0, score='80'):
        return self.tc.post(f'/api/submission-versions/{self.version.pk}/grade/', {
            'score': score, 'feedback': 'PRIVATE_FEEDBACK', 'expected_revision': revision,
            'reason': 'review', 'published': published}, format='json')

    def publication(self, published, revision):
        return self.tc.post(f'/api/submission-versions/{self.version.pk}/publication/',
                            {'published': published, 'expected_revision': revision}, format='json')

    def attempt(self, number=1, **kwargs):
        return QuizAttempt.objects.create(quiz=self.quiz, student=self.student, number=number,
            deadline=timezone.now()+timedelta(hours=1), status='submitted', grading_status='finalized',
            grade_revision=1, snapshot=[{'id': 42, 'score': '100'}], scores={'42': '90'}, **kwargs)

    def quiz_publication(self, action='grades_publish'):
        return self.tc.post(f'/api/quizzes/{self.quiz.pk}/publish/', {'action': action}, format='json')

    def inbox(self):
        response = self.sc.get('/api/notifications/'); self.assertEqual(response.status_code, 200); return response.data

    def test_assignment_only_on_publication_and_repeated_publication_is_noop(self):
        self.assertEqual(self.grade().status_code, 200)
        self.assertEqual(GradeNotification.objects.count(), 0)
        self.assertEqual(self.publication(True, 1).status_code, 200)
        self.assertEqual(self.publication(True, 2).status_code, 200)
        self.version.refresh_from_db(); self.assertEqual(self.version.grading_revision, 2)
        self.assertEqual(GradeNotification.objects.count(), 1)
        data = self.inbox(); self.assertEqual(data['unread_count'], 1)
        item = data['items'][0]; self.assertEqual(item['score'], '80.00')
        self.assertEqual(item['assignment_id'], self.assignment.pk)
        self.assertNotIn('PRIVATE', str(data)); self.assertNotIn('email', str(data))
        self.assertEqual(self.pc.get('/api/notifications/').data['items'], [])

    def test_assignment_withdrawal_regrade_and_new_submission_hide_old_scores(self):
        self.assertEqual(self.grade(True).status_code, 200)
        self.assertEqual(self.publication(False, 1).status_code, 200)
        self.assertIsNone(self.inbox()['items'][0]['score'])
        self.assertEqual(self.grade(True, 2, '85').status_code, 200)
        items = self.inbox()['items']; self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['score'], '85.00'); self.assertIsNone(items[1]['score'])
        SubmissionVersion.objects.create(submission=self.submission, number=2)
        self.assertTrue(all(item['score'] is None for item in self.inbox()['items']))

    def test_quiz_all_finalized_attempts_notify_once_per_publication_and_hide_on_regrade(self):
        first = self.attempt(); self.attempt(2)
        self.assertEqual(self.quiz_publication().status_code, 200)
        self.assertEqual(self.quiz_publication().status_code, 200)
        self.assertEqual(GradeNotification.objects.count(), 2)
        self.assertEqual(self.inbox()['items'][0]['score'], '90')
        self.assertEqual(self.quiz_publication('grades_withdraw').status_code, 200)
        self.assertTrue(all(item['score'] is None for item in self.inbox()['items']))
        response = self.tc.post(f'/api/quiz-attempts/{first.pk}/review/', {
            'scores': {'42': '50'}, 'feedback': {}, 'reason': 'recheck', 'expected_revision': 1}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.quiz_publication().status_code, 200)
        items = self.inbox()['items']; self.assertEqual(len(items), 4)
        old = next(item for item in items if item['id'] == GradeNotification.objects.order_by('pk').first().pk)
        self.assertIsNone(old['score']); self.assertEqual(old['availability'], 'updated')
        self.assertTrue(any(item['score'] == '50.00' and item['attempt_id'] == first.pk for item in items))

    def test_incomplete_quiz_publish_cannot_create_notification(self):
        attempt = self.attempt(); attempt.grading_status = 'awaiting_review'; attempt.save()
        self.assertEqual(self.quiz_publication().status_code, 409)
        self.assertEqual(GradeNotification.objects.count(), 0)

    def test_get_is_read_only_and_explicit_read_is_private_and_idempotent(self):
        self.grade(True)
        row = GradeNotification.objects.get()
        for _ in range(2):
            self.inbox(); self.sc.get('/api/notifications/unread-count/')
        row.refresh_from_db(); self.assertIsNone(row.read_at)
        url = f'/api/notifications/{row.pk}/read/'
        self.assertEqual(self.pc.post(url, {}, format='json').status_code, 404)
        self.assertEqual(self.sc.post(url, {}, format='json').status_code, 200)
        row.refresh_from_db(); stamp = row.read_at
        self.sc.post(url, {}, format='json'); row.refresh_from_db(); self.assertEqual(row.read_at, stamp)
        self.assertEqual(self.inbox()['unread_count'], 0)

    def test_removed_membership_hides_content_count_and_blocks_mark_read(self):
        self.grade(True); row = GradeNotification.objects.get()
        Membership.objects.filter(course=self.course, user=self.student).delete()
        self.assertEqual(self.inbox()['items'], [])
        self.assertEqual(self.sc.get('/api/notifications/unread-count/').data['unread_count'], 0)
        self.assertEqual(self.sc.post(f'/api/notifications/{row.pk}/read/', {}, format='json').status_code, 404)
        self.assertEqual(self.sc.post('/api/notifications/read-all/', {}, format='json').data['marked_count'], 0)
        row.refresh_from_db(); self.assertIsNone(row.read_at)

    def test_notification_failure_rolls_back_grade_and_helpers_deduplicate(self):
        with patch('core.notification_service.notify_assignment_grade', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError): self.grade(True)
        self.version.refresh_from_db(); self.assertIsNone(self.version.score); self.assertEqual(self.version.grading_revision, 0)
        self.grade(True); self.version.refresh_from_db()
        with transaction.atomic():
            notify_assignment_grade(self.version); notify_assignment_grade(self.version)
        self.assertEqual(GradeNotification.objects.count(), 1)

    def test_pagination_query_budget_and_read_all_persist(self):
        for number in range(1, 24): self.attempt(number)
        self.quiz_publication()
        with CaptureQueriesContext(connection) as captured: data = self.inbox()
        self.assertEqual(len(data['items']), 20); self.assertEqual(data['next_page'], 2)
        self.assertEqual(data['unread_count'], 23)
        self.assertLessEqual(sum(q['sql'].lstrip().upper().startswith('SELECT') for q in captured), 4)
        self.assertEqual(self.sc.post('/api/notifications/read-all/', {}, format='json').data['marked_count'], 23)
        self.assertEqual(self.sc.get('/api/notifications/?page=2').data['unread_count'], 0)
        self.assertEqual(self.sc.get('/api/notifications/?page=0').status_code, 400)
        self.assertEqual(APIClient().get('/api/notifications/').status_code, 401)
