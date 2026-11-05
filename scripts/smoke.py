"""Exercise the running HTTP entry point with temporary synthetic accounts."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import subprocess
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def backend(code):
    output = subprocess.check_output(
        ['docker', 'compose', 'exec', '-T', 'backend', 'python', 'manage.py', 'shell', '-c', code],
        cwd=ROOT, text=True, encoding='utf-8',
    )
    return json.loads(output.strip().splitlines()[-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:5174')
    parser.add_argument('--sandbox', action='store_true')
    args = parser.parse_args()
    suffix = uuid.uuid4().hex
    password = secrets.token_urlsafe(32)
    emails = [f'baseline-{suffix}-{role}@example.test' for role in ['teacher', 'student', 'outsider']]
    results = []
    tokens = {}

    def call(path, method='GET', data=None, token=None, expected=200, raw=False):
        headers = {}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(args.base + path, method=method, headers=headers,
                                         data=json.dumps(data).encode() if data is not None else None)
        try:
            response = urllib.request.urlopen(request, timeout=65)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status, body = response.status, response.read()
        if status != expected:
            raise AssertionError(f'{method} {path}: expected {expected}, received {status}')
        results.append({'method': method, 'path': path, 'status': status})
        return body.decode() if raw else json.loads(body)

    try:
        backend('from core.models import User; import json; '
                f'emails={emails!r}; password={password!r}; '
                '[User.objects.create_user(email,password,display_name="Baseline fixture",'
                'can_create_course=(i==0)) for i,email in enumerate(emails)]; print(json.dumps(True))')
        call('/health/')
        call('/health/live/')
        call('/', raw=True)
        call('/api/me/', expected=401)
        for email in emails:
            pair = call('/api/auth/login/', 'POST', {'email': email, 'password': password})
            tokens[email] = pair['access']
        teacher, student, outsider = [tokens[email] for email in emails]
        catalog = call('/api/agent/catalog/', token=teacher)
        if catalog['provider'] != 'mock':
            raise AssertionError('Run the repeatable smoke check in MODEL_PROVIDER=mock mode')
        course = call('/api/courses/', 'POST', {'name': 'Temporary baseline smoke'}, teacher, 201)
        course_id = course['id']
        call('/api/courses/join/', 'POST', {'code': course['join_code']}, student, 201)
        due_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        call(f'/api/courses/{course_id}/assignments/', 'POST',
             {'title': 'Fixture assignment', 'due_at': due_at}, teacher, 201)
        call(f'/api/courses/{course_id}/assignments/', 'POST',
             {'title': 'Denied fixture'}, student, 403)
        call(f'/api/courses/{course_id}/knowledge/search/?q=test&mode=keyword', token=outsider, expected=404)
        thread = call('/api/agent/threads/', 'POST', {'course_id': course_id}, teacher, 201)
        thread_id = thread['id']
        call(f'/api/agent/threads/{thread_id}/messages/', token=outsider, expected=404)
        stream = call(f'/api/agent/threads/{thread_id}/messages/stream/', 'POST',
                      {'content': 'Explain the baseline fixture', 'use_course_materials': False}, teacher, raw=True)
        if 'event: message_end' not in stream or 'event: error' in stream:
            raise AssertionError('Mock SSE stream did not complete')
        servers = call('/api/agent/platform-tools/', token=teacher)
        server = next(item for item in servers if item['name'] == 'platform-tools' and item['connected'])
        refs = ['formula_hint@platform-tools']
        if args.sandbox:
            refs.append('python_execute@platform-tools')
        call(f'/api/courses/{course_id}/assistant/', 'PUT', {'mcp_refs': refs}, teacher)
        tool_name = f"mcp_{server['id']}_formula_hint"
        result = call(f'/api/agent/threads/{thread_id}/tool-test/', 'POST',
                      {'name': tool_name, 'arguments': {'topic': 'derivative'}}, teacher)
        if result['status'] != 'ok':
            raise AssertionError('Real MCP formula tool failed')
        if args.sandbox:
            result = call(f'/api/agent/threads/{thread_id}/tool-test/', 'POST',
                          {'name': f"mcp_{server['id']}_python_execute",
                           'arguments': {'code': 'print(sum(range(1, 101)))'}}, teacher)
            if result['status'] != 'ok' or '5050' not in json.dumps(result['result']):
                raise AssertionError('Isolated Python execution failed')
        print(json.dumps({'passed_requests': len(results), 'model_mode': 'mock',
                          'real_mcp': True, 'sandbox_checked': args.sandbox, 'requests': results}, indent=2))
    finally:
        # Delete only resources belonging to this invocation's exact generated fixture emails.
        backend('from core.models import User,Course; import json; '
                f'emails={emails!r}; '
                'Course.objects.filter(created_by__email__in=emails).delete(); '
                'User.objects.filter(email__in=emails).delete(); print(json.dumps(True))')


if __name__ == '__main__':
    main()
