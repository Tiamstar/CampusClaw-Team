"""Exercise HTTP, mock SSE and confirmed real MCP with retained synthetic data."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import subprocess
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parents[1]


def validate_options(base, project, retain):
    origin = urlparse(base)
    if (not retain or origin.scheme != 'http' or origin.hostname not in {'localhost', '127.0.0.1'}
            or (origin.port is not None and not 1 <= origin.port <= 65535)
            or origin.username or origin.password or origin.path not in {'', '/'} or origin.query or origin.fragment):
        raise ValueError('Requires --retain-fixtures and a plain loopback HTTP origin')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project):
        raise ValueError('Use a plain Compose project name')


def backend_container(project):
    output = subprocess.check_output(['docker', 'ps', '-q', '--filter',
        'label=com.docker.compose.project='+project, '--filter', 'label=com.docker.compose.service=backend',
        '--filter', 'label=com.docker.compose.oneoff=False'], cwd=ROOT, text=True).strip()
    if not output or '\n' in output:
        raise RuntimeError('Exactly one running backend service required for selected project')
    return output


def backend(container, code):
    # Generated credentials and code go through stdin, never process arguments.
    result = subprocess.run(['docker', 'exec', '-i', container, 'python', 'manage.py', 'shell', '--no-imports'],
        cwd=ROOT, input=code, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Backend initializer failed; private output not printed, fixtures retained')
    return json.loads(result.stdout.strip().splitlines()[-1])


def confirmed_tool(call, thread_id, tool, arguments, owner, outsider):
    base = f'/api/agent/threads/{thread_id}/'
    pending = call(base+'tool-test/', 'POST', {'name': tool, 'arguments': arguments}, owner)
    if pending.get('status') != 'pending' or not pending.get('result', {}).get('confirmation_required'):
        raise AssertionError('MCP must remain pending until explicit confirmation')
    cid = pending['result']['confirmation_id']
    action = base+f'confirmations/{cid}/'
    call(action, 'POST', {'action': 'confirm'}, outsider, 404)
    call(action, 'POST', {'action': 'confirm', 'arguments': {}}, owner, 400)
    result = call(action, 'POST', {'action': 'confirm'}, owner)
    if result.get('status') != 'succeeded' or result.get('error') or not result.get('result'):
        raise AssertionError('Confirmed MCP tool failed')
    call(action, 'POST', {'action': 'confirm'}, owner, 409)
    return result['result']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:5174')
    parser.add_argument('--sandbox', action='store_true')
    parser.add_argument('--project', default='campusclaw-team')
    parser.add_argument('--retain-fixtures', action='store_true')
    parser.add_argument('--output', type=Path, required=True, help='New evidence JSON, never overwritten')
    args = parser.parse_args()
    validate_options(args.base, args.project, args.retain_fixtures)
    with args.output.open('x', encoding='utf-8'):
        pass
    suffix = uuid.uuid4().hex
    password = secrets.token_urlsafe(32)
    emails = [f'baseline-{suffix}-{role}@example.invalid' for role in ['teacher', 'student', 'outsider']]
    results = []
    tokens = {}
    report = {'passed': False, 'fixtures_retained': True, 'project': args.project,
              'model_mode': 'mock', 'real_mcp': False, 'sandbox_checked': False,
              'scope': 'Local engineering smoke; not real-model, public HTTPS or human independent acceptance',
              'requests': results}

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

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
            request_id = response.headers.get('X-Request-ID')
        results.append({'method': method, 'path': path, 'status': status, 'expected': expected, 'request_id': request_id})
        save()
        if status != expected:
            raise AssertionError(f'{method} {path}: expected {expected}, received {status}')
        return body.decode() if raw else json.loads(body)

    save()
    try:
        container = backend_container(args.project)
        provider = backend(container, 'import json,os; print(json.dumps(os.getenv("MODEL_PROVIDER","mock")))')
        if provider != 'mock':raise RuntimeError('Requires mock provider; no accounts created')
        report['synthetic_user_ids'] = backend(container, 'from core.models import User; import json; '
                f'emails={emails!r}; password={password!r}; '
                'users=[User.objects.create_user(email,password,display_name="Smoke synthetic fixture",'
                'can_create_course=(i==0)) for i,email in enumerate(emails)]; print(json.dumps([u.pk for u in users]))')
        save()
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
        course = call('/api/courses/', 'POST', {'name': 'CampusClaw CI 冒烟（合成保留记录）'}, teacher, 201)
        course_id = course['id']
        report['course_id'] = course_id;save()
        call('/api/courses/join/', 'POST', {'code': course['join_code']}, student, 201)
        due_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        call(f'/api/courses/{course_id}/assignments/', 'POST',
             {'title': 'Fixture assignment', 'due_at': due_at}, teacher, 201)
        call(f'/api/courses/{course_id}/assignments/', 'POST',
             {'title': 'Denied fixture'}, student, 403)
        call(f'/api/courses/{course_id}/knowledge/search/?q=test&mode=keyword', token=outsider, expected=404)
        thread = call('/api/agent/threads/', 'POST', {'course_id': course_id}, teacher, 201)
        thread_id = thread['id']
        report['thread_id'] = thread_id;save()
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
        config_path = f'/api/courses/{course_id}/assistant/'
        config = call(config_path, token=teacher)
        call(config_path, 'PUT', {'mcp_refs': refs, 'revision': config['revision']}, teacher)
        tool_name = f"mcp_{server['id']}_formula_hint"
        confirmed_tool(call, thread_id, tool_name, {'topic': 'derivative'}, teacher, outsider)
        report['real_mcp'] = True;save()
        if args.sandbox:
            result = confirmed_tool(call, thread_id, f"mcp_{server['id']}_python_execute",
                                    {'code': 'print(sum(range(1, 101)))'}, teacher, outsider)
            if '5050' not in json.dumps(result):
                raise AssertionError('Isolated Python execution failed')
            report['sandbox_checked'] = True
        report['passed'] = True
        report['passed_requests'] = len(results)
    except Exception:
        report['failure'] = 'Smoke did not complete; inspect retained request statuses and service logs privately. No cleanup or automatic replay.'
        raise
    finally:
        save()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
