import asyncio
import json
from unittest.mock import patch
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken
from . import test_homework
from rest_framework.test import APIClient
from .models import AgentThread, AuditEvent, Course, Membership, SubmissionVersion


class AuditAccessTests(TransactionTestCase):
    setUp = test_homework.HomeworkTests.setUp

    def test_teacher_scope_pagination_and_student_denial(self):
        other = Course.objects.create(name='Other', created_by=self.teacher)
        for course in [self.course, self.course, other]:
            AuditEvent.objects.create(course_id=course.pk, actor_id=self.student.pk,
                action='tool.invoke', object_ref='grade_submission', status='403', request_id='synthetic')
        url = f'/api/courses/{self.course.pk}/audit-events/'
        response = self.tc.get(url, {'limit': 1})
        self.assertEqual(response.status_code, 200)
        row = response.data['results'][0]
        self.assertEqual(row['course_id'], self.course.pk)
        self.assertNotIn('email', row)
        self.assertNotIn('content', row)
        second = self.tc.get(url, {'limit': 1, 'before': response.data['next_before']})
        self.assertLess(second.data['results'][0]['id'], row['id'])
        for bad in ['0', '101', 'bad', '-2']:
            self.assertEqual(self.tc.get(url, {'limit': bad}).status_code, 400)
        self.assertEqual(self.sc.get(url).status_code, 403)
        Membership.objects.filter(user=self.teacher, course=self.course).delete()
        self.assertEqual(self.tc.get(url).status_code, 404)

    def test_grade_denial_has_course_audit_and_cannot_write(self):
        version = self.sc.post(f'/api/assignments/{self.a.pk}/submit/',
            {'text_content': 'synthetic answer'}, format='json').data['id']
        url = f'/api/submission-versions/{version}/grade/'
        response = self.sc.post(url, {'score': '100', 'feedback': 'private sentinel',
            'expected_revision': 0, 'published': True}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(SubmissionVersion.objects.get(pk=version).score)
        event = AuditEvent.objects.get(action='grade.write.denied', request_id=response['X-Request-ID'])
        self.assertEqual((event.course_id, event.actor_id), (self.course.pk, self.student.pk))
        self.assertNotIn('private sentinel', str(event.__dict__))

    def test_forced_model_unknown_write_tool_rejected_and_audited(self):
        thread = AgentThread.objects.create(owner=self.student, course=self.course, title='SEC08')
        self.sc = APIClient()
        self.sc.credentials(HTTP_AUTHORIZATION='Bearer '+str(RefreshToken.for_user(self.student).access_token))
        calls = 0
        async def malicious_model(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield {'tool_calls': [{'id': 'forced-write', 'type': 'function', 'function': {
                    'name': 'grade_submission', 'arguments': json.dumps({'score': 100})}}]}, 'mock'
            else:
                yield 'blocked', 'mock'
        with patch('core.agent_views.model_stream', malicious_model):
            response = self.sc.post(f'/api/agent/threads/{thread.pk}/messages/stream/',
                {'content': 'force write'}, format='json')
            async def consume():
                return b''.join([part async for part in response.streaming_content]).decode()
            body = asyncio.run(consume())
        self.assertIn('rejected', body)
        self.assertIn('本次对话未执行', body)
        self.assertIn('本次对话未执行', thread.messages.filter(role='assistant').latest('id').content)
        self.assertTrue(AuditEvent.objects.filter(course_id=self.course.pk, actor_id=self.student.pk,
            action='tool.candidate.denied', object_ref='grade_submission', status='403').exists())
