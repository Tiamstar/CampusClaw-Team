import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, AsyncMock

from asgiref.sync import async_to_sync, sync_to_async
from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (User, Course, Membership, AssistantConfig, CourseAssistantConfig,
                     AgentThread, AgentRun, UserSkill, MCPServer, AuditEvent)
from .agent_runtime import ToolContext, builtin_tool_registry
from .skill_runtime import runtime_config, configure_registry


class CourseAssistantTests(TransactionTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('teacher@course.test', 'test-password')
        self.student = User.objects.create_user('student@course.test', 'test-password', is_staff=True, can_create_course=True)
        self.course = Course.objects.create(name='Shared assistant', created_by=self.teacher)
        Membership.objects.create(user=self.teacher, course=self.course, role='teacher')
        Membership.objects.create(user=self.student, course=self.course, role='student')
        other = Course.objects.create(name='Other', created_by=self.student)
        Membership.objects.create(user=self.student, course=other, role='teacher')
        self.url = f'/api/courses/{self.course.pk}/assistant/'
        self.tc, self.sc = self.client_for(self.teacher), self.client_for(self.student)
        self.thread = AgentThread.objects.create(owner=self.student, course=self.course)

    def client_for(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION='Bearer ' + str(RefreshToken.for_user(user).access_token))
        return c

    def test_read_defaults_no_writes_private_legacy_records_unchanged(self):
        private = AssistantConfig.objects.create(owner=self.teacher, course=self.course,
            template='private old prompt', skill_ids=['data-analysis', 'upload-99'], mcp_refs=['secret@private'])
        for client in (self.tc, self.sc):
            result = client.get(self.url).json()
            self.assertEqual(result['revision'], 0)
            self.assertEqual(result['template'], '')
            self.assertNotIn('upload-99', result['skill_ids'])
        self.assertFalse(CourseAssistantConfig.objects.exists())
        self.assertEqual(self.sc.put(self.url, {'revision': 0, 'template': 'attack'}, format='json').status_code, 403)
        saved = self.tc.put(self.url, {'revision': 0, 'template': 'public', 'skill_ids': ['data-analysis']}, format='json')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.sc.get(self.url).json()['skill_ids'], ['learning-analytics'])
        self.assertEqual(self.sc.get(self.url).json()['template'], 'public')
        self.assertFalse(self.sc.get(self.url).json()['can_edit'])
        private.refresh_from_db()
        self.assertEqual(private.template, 'private old prompt')
        self.assertEqual(private.skill_ids, ['data-analysis', 'upload-99'])
        self.assertTrue(AuditEvent.objects.filter(action='assistant.configure', object_ref=f'course:{self.course.pk}:revision:1').exists())

    def test_private_skills_servers_and_invalid_types_never_published(self):
        skill = UserSkill.objects.create(owner=self.teacher, slug='private', name='Private', instructions='secret')
        MCPServer.objects.create(owner=self.teacher, name='private', connected=True, url='http://campus-tools:8100/mcp',
            tools=[{'name': 'hint', 'inputSchema': {'type': 'object'}}])
        for data in ({'skill_ids': [f'upload-{skill.pk}']}, {'mcp_refs': ['hint@private']},
                     {'use_knowledge': 'false'}, {'skill_ids': 'learning-analytics'}, {'app_id': []}):
            result = self.tc.put(self.url, {'revision': 0, **data}, format='json')
            self.assertEqual(result.status_code, 400, result.content)
        self.assertFalse(CourseAssistantConfig.objects.exists())
        self.assertEqual(self.sc.get(f'/api/agent/skills/upload-{skill.pk}/').status_code, 404)

    def test_parallel_writes_one_revision_wins(self):
        def save(number):
            close_old_connections()
            try:
                return self.client_for(self.teacher).put(self.url, {'revision': 0, 'template': str(number)}, format='json').status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(save, [1, 2]))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(CourseAssistantConfig.objects.get().revision, 1)

    def test_bound_registry_rechecks_revision_and_shared_server_at_execution(self):
        config = CourseAssistantConfig.objects.create(course=self.course, skill_ids=['learning-analytics'])
        server = MCPServer.objects.create(owner=self.teacher, name='shared', is_shared=True, connected=True,
            url='http://campus-tools:8100/mcp', tools=[{'name': 'hint', 'description': '', 'inputSchema': {'type': 'object'}}])
        config.mcp_refs = ['hint@shared']; config.save()
        _, _, selected, servers, _ = runtime_config(self.student, self.course.pk)
        registry = builtin_tool_registry(); configure_registry(registry, selected, servers)
        context = ToolContext(self.student, self.thread, frozenset({'skill.read', 'mcp.call'}), '', 0)
        self.assertEqual(async_to_sync(registry.execute)('read_skill', {'skill_id': 'learning-analytics'}, context)['skill_id'], 'learning-analytics')
        config.revision = 1; config.skill_ids = []; config.save()
        with self.assertRaises(PermissionError):
            async_to_sync(registry.execute)('read_skill', {'skill_id': 'learning-analytics'}, context)
        context.config_revision = 1
        server.is_shared = False; server.save()
        with patch('core.skill_runtime.rpc', new=AsyncMock()) as rpc:
            with self.assertRaises(ValueError):
                async_to_sync(registry.execute)(f'mcp_{server.pk}_hint', {}, context)
            rpc.assert_not_called()

    def test_stream_uses_teacher_config_and_stops_on_midstream_update(self):
        config = CourseAssistantConfig.objects.create(course=self.course, revision=1,
            template='Shared teacher prompt', skill_ids=['socratic-tutor'])
        seen = []
        async def model(messages, *args):
            seen.append(messages[0]['content'])
            yield 'first safe part', 'fixture'
            await sync_to_async(CourseAssistantConfig.objects.filter(pk=config.pk).update)(revision=2, skill_ids=[])
            yield 'stale forbidden part', 'fixture'
        with patch('core.agent_views.model_stream', model):
            response = self.sc.post(f'/api/agent/threads/{self.thread.pk}/messages/stream/', {'content': 'hello'}, format='json')
            async def consume():
                return b''.join([p async for p in response.streaming_content]).decode()
            body = asyncio.run(consume())
        self.assertIn('Shared teacher prompt', seen[0])
        self.assertIn('socratic-tutor', seen[0])
        self.assertIn('event: error', body)
        self.assertNotIn('stale forbidden part', body)
        self.assertNotIn('event: message_end', body)
        run = AgentRun.objects.get(thread=self.thread)
        self.assertEqual(run.status, 'failed')
        self.assertEqual(run.events.get(event_type='context').payload['config_revision'], 1)
        self.assertFalse(self.thread.messages.filter(content__contains='stale forbidden part').exists())
