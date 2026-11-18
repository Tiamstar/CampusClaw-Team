"""Explicit, retained HTTP negative cases; never invokes a model or sends email."""
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import Course, ForumPost, SubmissionVersion, User


class Command(BaseCommand):
    help = 'Run SQL/CSRF HTTP cases and retain an XSS forum fixture for browser inspection.'

    def add_arguments(self, parser):
        parser.add_argument('--retain-fixtures', action='store_true')
        parser.add_argument('--teacher', required=True)
        parser.add_argument('--student', required=True)
        parser.add_argument('--cases', required=True)
        parser.add_argument('--base-url', default='http://127.0.0.1:8000')
        parser.add_argument('--output', default='/tmp/security-negative-evidence.json')

    def handle(self, *args, **options):
        base = options['base_url']
        parsed = urlparse(base)
        if not options['retain_fixtures'] or parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.username or parsed.password:
            raise CommandError('Requires --retain-fixtures and a plain loopback HTTP base URL')
        cases = json.loads(Path(options['cases']).read_text(encoding='utf-8'))
        if cases.get('schema_version') != 1:
            raise CommandError('Unsupported cases version')
        teacher = User.objects.get(email=options['teacher'], is_active=True)
        student = User.objects.get(email=options['student'], is_active=True)
        if teacher == student or not teacher.can_create_course:
            raise CommandError('Distinct existing authorized teacher/student accounts required')
        report = {'started_at': timezone.now().isoformat(), 'fixtures_retained': True,
                  'transport': 'actual_loopback_http', 'auth': 'server-minted JWT for existing authorized users; not a password-login test',
                  'checks': [], 'browser_xss': 'pending; API storage alone does not prove safe rendering'}
        def save():
            Path(options['output']).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        def check(name, passed, **metadata):
            report['checks'].append({'id': name, 'passed': bool(passed), **metadata})
            save()
            self.stdout.write(f'{name}: {bool(passed)}')
        def grades():
            return list(SubmissionVersion.objects.order_by('pk').values_list('pk','score','grading_revision','published_at'))
        before = grades()
        with httpx.Client(base_url=base, timeout=15, trust_env=False) as tc, httpx.Client(base_url=base, timeout=15, trust_env=False) as sc, httpx.Client(base_url=base, timeout=15, trust_env=False) as anonymous:
            for client, user in [(tc, teacher), (sc, student)]:
                client.headers['Authorization'] = 'Bearer ' + str(RefreshToken.for_user(user).access_token)
            def post(client, path, body, expected=201):
                response = client.post('/api/'+path, json=body)
                if response.status_code != expected:
                    raise CommandError(f'Fixture HTTP {response.status_code}; partial evidence and fixtures retained')
                return response.json()
            course = post(tc, 'courses/', {'name':'CampusClaw SQL/XSS/CSRF 安全反例（保留记录）'})
            cid = course['id']
            report.update(course_id=cid, join_code=course['join_code'])
            save()
            post(sc, 'courses/join/', {'code':course['join_code']})
            path = f'courses/{cid}/forum/posts/'
            normal = post(sc, path, {'title':'SECURITY-SQL-POSITIVE 普通查询对照', 'body':'合成内容，保留供验收。'})
            response = sc.get('/api/'+path, params={'q':'SECURITY-SQL-POSITIVE'})
            check('SQL-positive-control', response.status_code==200 and [r['id'] for r in response.json().get('items',[])]==[normal['id']], status=response.status_code)
            for case in cases['sql']:
                response = sc.get('/api/'+path, params={'q':case['query']})
                check(case['id']+'-empty', response.status_code==200 and response.json().get('items')==[], status=response.status_code, request_id=response.headers.get('x-request-id'))
                literal = post(sc, path, {'title':'字面值 '+case['query'], 'body':'攻击字符串作为普通文本保存，不执行SQL。'})
                response = sc.get('/api/'+path, params={'q':case['query']})
                check(case['id']+'-literal', response.status_code==200 and [r['id'] for r in response.json().get('items',[])]==[literal['id']], status=response.status_code)
            xss = post(sc, path, {k:cases['xss'][k] for k in ['title','body']})
            report['xss_post_id'] = xss['id']
            check('XSS-stored-control', xss['body']==cases['xss']['body'], post_id=xss['id'])
            # Admin uses cookie/session CSRF; the API intentionally requires an explicit JWT header.
            form = {'username':'security-negative-nonexistent', 'password':'invalid-test-only'}
            response = anonymous.post('/admin/login/', data=form)
            check(cases['csrf'][0], response.status_code==403, status=response.status_code)
            anonymous.get('/admin/login/')
            token = anonymous.cookies.get('csrftoken')
            if not token: raise CommandError('Admin CSRF cookie missing; evidence retained')
            response = anonymous.post('/admin/login/', data={**form, 'csrfmiddlewaretoken':'invalid'})
            check(cases['csrf'][1], response.status_code==403, status=response.status_code)
            response = anonymous.post('/admin/login/', data={**form, 'csrfmiddlewaretoken':token}, headers={'Origin':'https://foreign.example.invalid'})
            check(cases['csrf'][2], response.status_code==403, status=response.status_code)
            response = anonymous.post('/admin/login/', data={**form, 'csrfmiddlewaretoken':token}, headers={'Origin':base})
            check(cases['csrf'][3], response.status_code==200 and 'errornote' in response.text, status=response.status_code)
            count = ForumPost.objects.filter(course_id=cid).count()
            body = {'title':'CSRF请求不应创建', 'body':'合成反例'}
            response = anonymous.post('/api/'+path, json=body, headers={'Origin':'https://foreign.example.invalid'})
            check(cases['csrf'][4], response.status_code==401 and ForumPost.objects.filter(course_id=cid).count()==count, status=response.status_code)
            anonymous.cookies.set('access_token', sc.headers['Authorization'][7:])
            response = anonymous.post('/api/'+path, json=body)
            check(cases['csrf'][5], response.status_code==401 and ForumPost.objects.filter(course_id=cid).count()==count, status=response.status_code)
            response = sc.post('/api/'+path, json={'title':'Bearer正常请求对照', 'body':'明确Authorization头；不是跨站请求伪造。'})
            check(cases['csrf'][6], response.status_code==201 and ForumPost.objects.filter(course_id=cid).count()==count+1, status=response.status_code)
        check('formal-grades-unchanged', before==grades(), versions_checked=len(before))
        report['finished_at'] = timezone.now().isoformat()
        report['http_checks_passed'] = all(row['passed'] for row in report['checks'])
        report['course_exists'] = Course.objects.filter(pk=cid).exists()
        save()
        if not report['http_checks_passed']: raise CommandError('Some HTTP checks failed; evidence retained')
