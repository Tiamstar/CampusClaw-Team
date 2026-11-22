from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Assignment, Course, ForumPost, Membership, Quiz, QuizAttempt,
                     QuizGradeRevision, Submission, SubmissionGradeRevision, SubmissionVersion, User)


class CourseOverviewTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('overview-teacher@example.test', 'test-only')
        self.student = User.objects.create_user('overview-student@example.test', 'test-only')
        self.peer = User.objects.create_user('overview-peer@example.test', 'test-only')
        self.outsider = User.objects.create_user('overview-outsider@example.test', 'test-only')
        self.course = Course.objects.create(name='Overview', created_by=self.teacher)
        self.other = Course.objects.create(name='Other', created_by=self.outsider)
        for user, role in [(self.teacher, 'teacher'), (self.student, 'student'), (self.peer, 'student')]:
            Membership.objects.create(course=self.course, user=user, role=role)
        self.now = timezone.now()
        self.url = f'/api/courses/{self.course.id}/overview/'

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def assignment(self, title, days=1, **kwargs):
        return Assignment.objects.create(course=self.course, title=title, due_at=self.now+timedelta(days=days), **kwargs)

    def version(self, assignment, user=None, number=1, **kwargs):
        submission, _ = Submission.objects.get_or_create(assignment=assignment, student=user or self.student)
        return SubmissionVersion.objects.create(submission=submission, number=number, **kwargs)

    def quiz(self, title='Published', **kwargs):
        return Quiz.objects.create(course=self.course, title=title, opens_at=self.now-timedelta(hours=1),
                                   closes_at=self.now+timedelta(days=1), answers_at=self.now+timedelta(days=2), **kwargs)

    def attempt(self, quiz, user=None, number=1, **kwargs):
        return QuizAttempt.objects.create(quiz=quiz, student=user or self.student, number=number,
                                          deadline=self.now-timedelta(minutes=1), **kwargs)

    def test_membership_and_read_only_method(self):
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(self.client_for(self.outsider).get(self.url).status_code, 403)
        self.assertEqual(self.client_for(self.student).post(self.url, {}, format='json').status_code, 405)
        Membership.objects.filter(course=self.course, user=self.student).delete()
        self.assertEqual(self.client_for(self.student).get(self.url).status_code, 403)

    def test_student_unsubmitted_deadlines_use_only_own_actual_versions(self):
        future = self.assignment('Soon')
        late = self.assignment('Late allowed', -1, allow_late=True)
        self.assignment('Missed closed', -2)
        done = self.assignment('Already submitted')
        self.version(done, score=Decimal('0'), feedback='UNRELEASED_PRIVATE_FEEDBACK')
        peer_only = self.assignment('Peer submitted only', 2)
        self.version(peer_only, self.peer)
        empty = self.assignment('Empty submission container', 3)
        Submission.objects.create(assignment=empty, student=self.student)
        Assignment.objects.create(course=self.other, title='FOREIGN_PRIVATE', due_at=self.now)
        data = self.client_for(self.student).get(self.url).data
        self.assertEqual(data['counts']['assignments_to_submit'], 4)
        self.assertEqual(data['counts']['missed_assignments'], 1)
        self.assertEqual([a['id'] for a in data['assignments']], [future.id, peer_only.id, empty.id, late.id])
        self.assertNotIn('assignment_reviews', data['counts'])
        self.assertNotIn('PRIVATE', str(data))
        self.assertNotIn('score', str(data))

    def test_teacher_counts_match_latest_version_and_submitted_attempt_scope(self):
        task = self.assignment('Graded latest')
        self.version(task)
        self.version(task, number=2, score=Decimal('0'))
        self.version(self.assignment('Needs review'), review_started_at=self.now)
        quiz = self.quiz(status='published')
        self.attempt(quiz, status='submitted', grading_status='pending')
        self.attempt(quiz, number=2, status='submitted', grading_status='finalized')
        self.attempt(quiz, self.peer, status='in_progress')
        data = self.client_for(self.teacher).get(self.url).data
        self.assertEqual(data['counts']['assignment_reviews'], 1)
        self.assertEqual(data['counts']['quiz_reviews'], 1)
        self.assertEqual(data['active_attempts'], [])
        for kind, key in [('assignment', 'assignment_reviews'), ('quiz', 'quiz_reviews')]:
            queue = self.client_for(self.teacher).get(f'/api/grading-queue/?kind={kind}').data
            self.assertEqual(len(queue['items']), data['counts'][key])

    def test_published_schedule_and_private_attempts_never_auto_finalize(self):
        quiz = self.quiz(status='published', rules=[{'secret': 'PRIVATE_RULE'}])
        expired = self.attempt(quiz, answers={'private': 'MY_ANSWER'})
        self.attempt(quiz, self.peer, answers={'private': 'PEER_ANSWER'})
        self.quiz(title='PRIVATE_DRAFT', status='draft')
        self.quiz(title='Closed', status='closed')
        future = self.quiz(title='Future', status='published')
        future.opens_at = self.now+timedelta(hours=1)
        future.save()
        before = (QuizGradeRevision.objects.count(), SubmissionGradeRevision.objects.count())
        with patch('core.quiz_service.finalize', side_effect=AssertionError('GET must not finalize')):
            data = self.client_for(self.student).get(self.url).data
        self.assertEqual(data['counts']['open_quizzes'], 1)
        self.assertEqual(data['counts']['upcoming_quizzes'], 1)
        self.assertEqual({q['id'] for q in data['quizzes']}, {quiz.id, future.id})
        self.assertEqual([a['id'] for a in data['active_attempts']], [expired.id])
        self.assertNotIn('PRIVATE', str(data))
        self.assertNotIn('ANSWER', str(data))
        expired.refresh_from_db()
        self.assertEqual(expired.status, 'in_progress')
        self.assertEqual(expired.grade_revision, 0)
        self.assertEqual(before, (QuizGradeRevision.objects.count(), SubmissionGradeRevision.objects.count()))

    def test_bounded_rows_counts_and_queries_with_anonymous_forum_titles_only(self):
        for index in range(12):
            self.assignment(f'Task {index}', index+1)
            self.quiz(title=f'Quiz {index}', status='published')
            ForumPost.objects.create(course=self.course, author=self.peer, title=f'Post {index}',
                                     body='PRIVATE_BODY', anonymous=True)
        with CaptureQueriesContext(connection) as captured:
            response = self.client_for(self.student).get(self.url)
        data = response.data
        self.assertEqual(data['counts']['assignments_to_submit'], 12)
        self.assertEqual(data['counts']['open_quizzes'], 12)
        self.assertEqual(len(data['assignments']), 5)
        self.assertEqual(len(data['quizzes']), 5)
        self.assertEqual(len(data['recent_posts']), 3)
        self.assertNotIn('author', str(data))
        self.assertNotIn('PRIVATE_BODY', str(data))
        self.assertLessEqual(sum(q['sql'].lstrip().upper().startswith('SELECT') for q in captured), 10)

    def test_empty_course_returns_explicit_empty_lists_and_zero_counts(self):
        data = self.client_for(self.student).get(self.url).data
        self.assertEqual(data['assignments'], [])
        self.assertEqual(data['quizzes'], [])
        self.assertEqual(data['recent_posts'], [])
        self.assertTrue(all(value == 0 for value in data['counts'].values()))
