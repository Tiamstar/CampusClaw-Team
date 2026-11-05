"""Regression cases for the first team delivery, including revoked access."""
from asgiref.sync import async_to_sync
from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .agent_runtime import ToolContext, builtin_tool_registry
from .models import AgentThread, AuditEvent, Course, Membership, User


class RequestBoundaryTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('baseline@example.test', 'test-password')
        self.course = Course.objects.create(name='Baseline', created_by=self.teacher)
        Membership.objects.create(course=self.course, user=self.teacher, role='teacher')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.teacher).access_token}')

    def test_invalid_json_is_400_without_creating_thread(self):
        for body in ['[1]', 'null', '{broken']:
            with self.subTest(body=body):
                response = self.client.post('/api/agent/threads/', body, content_type='application/json')
                self.assertEqual(response.status_code, 400)
        self.assertFalse(AgentThread.objects.exists())

    def test_reindex_get_cannot_start_external_work(self):
        with patch('core.agent_views.index_material') as index:
            response = self.client.get(f'/api/courses/{self.course.id}/knowledge/reindex/')
        self.assertEqual(response.status_code, 405)
        index.assert_not_called()

    def test_readiness_detects_database_outage(self):
        with patch('django.db.connection.cursor', side_effect=OperationalError('private db details')):
            response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'private db details', response.content)

    def test_sql_injection_in_search_does_not_expand_scope(self):
        response = self.client.get(f'/api/courses/{self.course.id}/knowledge/search/',
                                   {'q': "' OR 1=1 --", 'mode': 'keyword'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['hits'], [])

    def test_admin_login_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post('/admin/login/', {'username': 'admin', 'password': 'invalid'})
        self.assertEqual(response.status_code, 403)

    def test_denial_audit_has_actor_request_id_and_no_body(self):
        Membership.objects.filter(user=self.teacher, course=self.course).update(role='student')
        response = self.client.post(f'/api/courses/{self.course.id}/assignments/',
                                   {'title': 'private-body-sentinel'}, format='json')
        self.assertEqual(response.status_code, 403)
        event = AuditEvent.objects.get(request_id=response['X-Request-ID'])
        self.assertEqual(event.actor_id, self.teacher.id)
        self.assertEqual(event.status, '403')
        self.assertNotIn('private-body-sentinel', str(event.__dict__))

    def test_anonymous_request_is_denied_and_audited(self):
        response = APIClient().get('/api/me/')
        self.assertEqual(response.status_code, 401)
        event = AuditEvent.objects.get(request_id=response['X-Request-ID'])
        self.assertIsNone(event.actor_id)


class ToolReauthorizationTests(TransactionTestCase):
    def test_revocation_between_prompt_and_tool_execution(self):
        user = User.objects.create_user('revoked@example.test', 'test-password')
        course = Course.objects.create(name='Revocation', created_by=user)
        membership = Membership.objects.create(user=user, course=course, role='student')
        thread = AgentThread.objects.create(owner=user, course=course)
        context = ToolContext(user, thread, frozenset({'course.read'}))
        membership.delete()
        with self.assertRaises(PermissionError):
            async_to_sync(builtin_tool_registry().execute)('list_course_materials', {}, context)
