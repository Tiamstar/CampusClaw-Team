import json
import os
from unittest.mock import patch

import httpx
from asgiref.sync import async_to_sync
from django.test import SimpleTestCase

from .agent_runtime import _model_stream_impl, RuntimeErrorWithStatus


class ModelProtocolTests(SimpleTestCase):
    def test_both_protocols_root_and_versioned_bases(self):
        for provider in ('openai', 'anthropic'):
            for suffix in ('', '/v1/'):
                with self.subTest(provider=provider, suffix=suffix):
                    captured = []

                    def respond(request):
                        captured.append(request)
                        wire = ('data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
                                if provider == 'openai' else
                                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\n'
                                'data: {"type":"message_stop"}\n\n')
                        return httpx.Response(200, text=wire)

                    async def collect():
                        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                        with patch('core.agent_runtime.httpx.AsyncClient', return_value=client):
                            return [x async for x in _model_stream_impl([
                                {'role': 'system', 'content': 'Extract only.'},
                                {'role': 'user', 'content': [{'type': 'text', 'text': 'question'},
                                 {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YQ=='}}]},
                            ], tools=[{'type': 'function', 'function': {'name': 'lookup',
                                      'description': 'Lookup', 'parameters': {'type': 'object'}}}])]

                    with patch.dict(os.environ, {'MODEL_PROVIDER': provider, 'MODEL_NAME': 'fixture',
                            'MODEL_API_BASE': 'https://gateway.example' + suffix,
                            'MODEL_API_KEY': 'common-fixture', 'ANTHROPIC_API_KEY': 'anthropic-fixture'}):
                        self.assertIn(('ok', 'fixture'), async_to_sync(collect)())
                    request = captured[0]
                    body = json.loads(request.content)
                    self.assertTrue(body['stream'])
                    if provider == 'openai':
                        self.assertEqual(request.url.path, '/v1/chat/completions')
                        self.assertEqual(request.headers['authorization'], 'Bearer common-fixture')
                        self.assertEqual(body['messages'][1]['content'][1]['type'], 'image_url')
                        self.assertEqual(body['tools'][0]['function']['name'], 'lookup')
                    else:
                        self.assertEqual(request.url.path, '/v1/messages')
                        self.assertEqual(request.headers['x-api-key'], 'anthropic-fixture')
                        self.assertEqual(body['system'], 'Extract only.')
                        self.assertEqual(body['messages'][0]['content'][1]['type'], 'image')
                        self.assertEqual(body['tools'][0]['name'], 'lookup')

    def test_invalid_real_configuration_never_silently_uses_mock(self):
        async def collect():
            return [x async for x in _model_stream_impl([{'role': 'user', 'content': 'test'}])]
        for provider, model in [('typo', 'fixture'), ('openai', ''), ('anthropic', '')]:
            with self.subTest(provider=provider), patch.dict(os.environ,
                    {'MODEL_PROVIDER': provider, 'MODEL_NAME': model}):
                with self.assertRaises(RuntimeErrorWithStatus):
                    async_to_sync(collect)()
