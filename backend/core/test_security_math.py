import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from asgiref.sync import async_to_sync
from django.test import TestCase, SimpleTestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from .models import User, Course, Membership, AssistantConfig, AuthRateLimit
from .mcp_client import read_response, rpc


class AuthAndPrivacyTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('teacher@test.example', 'test-pass')
        self.student = User.objects.create_user('student@test.example', 'test-pass')
        self.course = Course.objects.create(name='Test', created_by=self.teacher)
        Membership.objects.create(user=self.teacher, course=self.course, role='teacher')
        Membership.objects.create(user=self.student, course=self.course, role='student')
        self.client = APIClient()

    def test_login_email_limit_spans_clients_and_ip_limit_spans_emails(self):
        for i in range(10):
            self.assertEqual(APIClient().post('/api/auth/login/', {'email': ' TARGET@example.com ', 'password': 'bad'}, REMOTE_ADDR=f'192.0.2.{i}').status_code, 400)
        self.assertEqual(self.client.post('/api/auth/login/', {'email': 'target@example.com', 'password': 'bad'}, REMOTE_ADDR='192.0.2.200').status_code, 429)
        AuthRateLimit.objects.all().delete()
        for i in range(20):
            self.assertEqual(self.client.post('/api/auth/login/', {'email': f'{i}@example.com', 'password': 'bad'}).status_code, 400)
        response = self.client.post('/api/auth/login/', {'email': 'new@example.com', 'password': 'bad'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)

    def test_code_limit_also_applies_to_authenticated_user(self):
        self.client.force_authenticate(self.student)
        for i in range(10):
            self.assertEqual(self.client.post('/api/auth/code/', {'email': 'invalid', 'purpose': 'register'}).status_code, 400)
        self.assertEqual(self.client.post('/api/auth/code/', {'email': 'invalid', 'purpose': 'register'}).status_code, 429)

    def test_counters_expire_and_do_not_store_identity(self):
        from django.utils import timezone
        from datetime import timedelta
        self.client.post('/api/auth/login/', {'email': 'private@example.com', 'password': 'bad'})
        self.assertTrue(all(len(k) == 64 and '@' not in k for k in AuthRateLimit.objects.values_list('key', flat=True)))
        AuthRateLimit.objects.update(count=999, expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.post('/api/auth/login/', {'email': 'private@example.com', 'password': 'bad'}).status_code, 400)

    def test_get_config_does_not_create_and_put_persists(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.student).access_token}')
        url = f'/api/courses/{self.course.id}/assistant/'
        for _ in range(2):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertFalse(AssistantConfig.objects.exists())
        self.assertEqual(self.client.put(url, {'template': 'saved'}, format='json').status_code, 200)
        self.assertEqual(AssistantConfig.objects.get().template, 'saved')

    def test_members_only_teacher_receives_email(self):
        url = f'/api/courses/{self.course.id}/members/'
        self.client.force_authenticate(self.student)
        self.assertTrue(all('email' not in row for row in self.client.get(url).data))
        self.client.force_authenticate(self.teacher)
        self.assertTrue(all('email' in row for row in self.client.get(url).data))


class ConcurrentThrottleTests(TransactionTestCase):
    @override_settings(AUTH_TRUST_PROXY_IP=False, AUTH_RATE_LIMITS={'login': {'ip': (100, 60), 'email': (3, 900)}})
    def test_parallel_workers_share_one_email_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections
        from .auth_throttle import AuthThrottle

        def attempt(number):
            close_old_connections()
            try:
                request = SimpleNamespace(data={'email': 'same@example.com'}, META={'REMOTE_ADDR': f'192.0.2.{number}'})
                return AuthThrottle().allow_request(request, None)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(attempt, range(12))), 3)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks, self.delay = chunks, delay

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk


class MCPBoundsTests(SimpleTestCase):
    def read(self, chunks, sse=True):
        response = httpx.Response(200, headers={'content-type': 'text/event-stream' if sse else 'application/json'}, stream=Chunks(chunks))
        return async_to_sync(read_response)(response)

    def test_split_utf8_and_crlf_and_json(self):
        raw = 'data: {"id":1,"result":"数学"}\r\n\r\n'.encode()
        self.assertEqual(self.read([bytes([b]) for b in raw])['result'], '数学')
        self.assertEqual(self.read([b'{"id":1,"result":{}}'], False)['result'], {})

    def test_single_line_and_cumulative_events_are_bounded(self):
        with patch('core.mcp_client.MAX_RESPONSE_BYTES', 64):
            for chunks in [[b'data:' + b'x' * 65], [b': keepalive\n\n'] * 10, [b'x' * 65]]:
                with self.assertRaisesRegex(ValueError, '3 MB'):
                    self.read(chunks)

    def test_rpc_total_timeout_including_drip_feed(self):
        real_client = httpx.AsyncClient
        async def handle(request):
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks([b': ping\n\n'] * 20, .01))
        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)
        server = SimpleNamespace(url='http://localhost/mcp', token_env='', session_id='')
        with patch.dict('os.environ', {'MCP_ALLOWED_HOSTS': 'localhost'}), patch('core.mcp_client.httpx.AsyncClient', side_effect=client), patch('core.mcp_client.RPC_TIMEOUT', .03):
            with self.assertRaisesRegex(ValueError, '总时限'):
                async_to_sync(rpc)(server, 'tools/list')
