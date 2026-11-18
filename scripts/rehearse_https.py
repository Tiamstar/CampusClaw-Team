"""Rehearse production HTTPS on a fresh internal network; retain all resources.

Requires built Compose images and Caddy 2.10.2, no published ports or real keys.
The generated private config and logs must be outside the Git repository.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from setup_production import create_config

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import json,os,ssl,time,urllib.request,urllib.error
from pathlib import Path
m=json.loads(Path('/tmp/fixture-manifest.json').read_text())['manifest']
context=ssl.create_default_context(cafile='/tmp/rehearsal-root.crt')
opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),urllib.request.ProxyHandler({}))
base='https://acceptance.localhost'
checks={}
def call(path,method='GET',data=None,token=None,headers=None):
 h=dict(headers or {})
 if token:h['Authorization']='Bearer '+token
 if data is not None:h['Content-Type']='application/json'
 request=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=h,method=method)
 try:r=opener.open(request,timeout=30)
 except urllib.error.HTTPError as e:r=e
 with r:return r.status,r.headers,r.read()
def check(name,value):
 checks[name]=bool(value)
 if not value:raise RuntimeError('HTTPS assertion failed: '+name)
check('verified_ca_readiness',call('/health/')[0]==200)
check('spa_over_verified_tls',call('/')[0]==200)
check('hsts_header',call('/')[1].get('Strict-Transport-Security')=='max-age=86400')
def login(label):
 status,headers,body=call('/api/auth/login/','POST',{'email':m['accounts'][label]['email'],'password':os.environ['ACCEPTANCE_FIXTURE_PASSWORD']})
 check('password_login_'+label,status==200)
 return json.loads(body)['access']
t=login('T_A');s=login('S_A1');b=login('S_B1');cid=m['courses']['A']['id']
status,headers,body=call(f'/api/courses/{cid}/gradebook/',token=t)
rows=json.loads(body)['snapshots'][0]['rows'];totals={r['student_id']:r['total'] for r in rows}
check('teacher_grade_baseline',status==200 and [totals[m['accounts'][f'S_A{i}']['id']] for i in [1,2]]==['87.00','57.00'])
status,headers,body=call(f'/api/courses/{cid}/gradebook/',token=s)
check('student_only_own_grade',status==200 and len(json.loads(body)['snapshot']['rows'])==1)
check('cross_course_denied',call(f'/api/courses/{cid}/gradebook/',token=b)[0]==403)
status,headers,body=call('/api/csrf/')
cookie=headers.get('Set-Cookie','');token=cookie.split('csrftoken=')[1].split(';')[0]
check('csrf_secure_cookie',status==200 and 'Secure' in cookie and 'SameSite=Lax' in cookie)
form=urllib.parse.urlencode({'username':'no-user@example.invalid','password':'not-a-real-password','csrfmiddlewaretoken':token}).encode()
def admin(origin,include_token=True):
 h={'Cookie':'csrftoken='+token,'Origin':origin,'Referer':origin+'/admin/login/','Content-Type':'application/x-www-form-urlencoded'}
 req=urllib.request.Request(base+'/admin/login/',data=form if include_token else b'username=none',headers=h)
 try:r=opener.open(req,timeout=30)
 except urllib.error.HTTPError as e:r=e
 with r:return r.status
check('admin_same_origin_csrf_passes',admin(base)==200)
check('admin_foreign_origin_rejected',admin('https://evil.example.invalid')==403)
check('admin_missing_csrf_rejected',admin(base,False)==403)
check('spoofed_proto_replaced',call('/api/me/',headers={'X-Forwarded-Proto':'http'})[0]==401)
status,headers,body=call('/api/agent/threads/','POST',{'course_id':cid},t)
check('chat_thread_created',status==201);thread=json.loads(body)['id']
status,headers,body=call(f'/api/agent/threads/{thread}/messages/stream/','POST',{'content':'合成HTTPS流式预演，不使用真实资料','use_course_materials':False},t)
check('mock_sse_completed',status==200 and b'event: message_end' in body and b'event: error' not in body)
# A forged public X-Real-IP must not evade a single shared edge-IP limit.
statuses=[]
for i in range(22):
 statuses.append(call('/api/auth/login/','POST',{'email':f'bad-{i}@example.invalid','password':'invalid'},headers={'X-Real-IP':f'192.0.2.{i}'})[0])
check('spoofed_client_ip_cannot_bypass_limit',429 in statuses)
# HTTP is checked without following its redirect and with a different scheme.
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
plain=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
try:r=plain.open('http://acceptance.localhost/health/',timeout=20)
except urllib.error.HTTPError as e:r=e
with r:check('http_redirects_to_https',r.status==308 and r.headers.get('Location')=='https://acceptance.localhost/health/')
print(json.dumps({'checks':checks,'passed':all(checks.values()),'model':'mock; not a real provider test','tls':'local CA explicitly trusted; no insecure verification bypass'}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--project', required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'https-rehearsal-[a-z0-9-]{1,40}', args.project):
        parser.error('Project must start https-rehearsal- and use lowercase letters, numbers and hyphens')
    output = args.output_dir.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error('Output must be a NEW private directory outside the repository')
    output.mkdir(parents=True, exist_ok=False)
    config = output / '.env.production'
    create_config(config, 'acceptance.localhost', 'rehearsal@example.invalid')
    env = os.environ.copy()
    # Do not let caller environment import model/SMTP credentials or Compose
    # overrides into the isolated exercise.
    for key in list(env):
        if key.startswith(('MODEL_', 'EMBEDDING_', 'ANTHROPIC_', 'EMAIL_', 'POSTGRES_', 'COMPOSE_', 'DJANGO_', 'PUBLIC_', 'ACME_', 'SANDBOX_', 'MCP_')):
            env.pop(key)
    env['ACCEPTANCE_FIXTURE_PASSWORD'] = secrets.token_urlsafe(32)+'!aA9'
    compose = ['compose','--env-file',str(config),'-p',args.project,'-f','docker-compose.yml',
               '-f','deploy/compose.production.yml','-f','deploy/compose.rehearsal.yml']
    report = {'project':args.project,'scope':'Local internal-CA engineering rehearsal; not public HTTPS or independent human acceptance',
              'passed':False,'resources_retained':True}
    owns_resources = False
    def run(command, log, input=None):
        result = subprocess.run(['docker',*command],cwd=ROOT,env=env,input=input,capture_output=True,text=True,encoding='utf-8')
        (output/log).write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('Docker step failed; see private log '+log)
        return result.stdout
    try:
        rendered=json.loads(run([*compose,'config','--format','json'],'compose.private.json'))
        if any(s.get('ports') for s in rendered['services'].values()):
            raise RuntimeError('Rehearsal must not publish any ports')
        if not rendered['networks']['default'].get('internal'):
            raise RuntimeError('Rehearsal network must be internal')
        # Reject reuse of an earlier rehearsal even when its containers stopped.
        existing=run(['ps','-aq','--filter','label=com.docker.compose.project='+args.project],'existing.log').strip()
        volumes=run(['volume','ls','-q','--filter','label=com.docker.compose.project='+args.project],'existing-volumes.log').strip()
        if existing or volumes:raise RuntimeError('Choose a fresh rehearsal project; existing resources retained')
        owns_resources = True
        run([*compose,'up','-d','--no-build','--wait','db'],'database.log')
        run([*compose,'run','--rm','--no-deps','backend','python','manage.py','migrate','--noinput'],'migrate.log')
        # Seed before bootstrap_tools creates its platform service identity.
        # Only this offline initializer skips redirect; live backend keeps HTTPS.
        first=json.loads(run([*compose,'run','--rm','--no-deps','-T','-e','DJANGO_HTTPS_ONLY=0','-e','ACCEPTANCE_FIXTURE_PASSWORD','backend','python','manage.py',
                              'seed_acceptance','--allow-synthetic-fixtures'],'seed.private.json'))
        run([*compose,'up','-d','--no-build','--wait','--wait-timeout','180'],'start.log')
        backend=run([*compose,'ps','-q','backend'],'backend-id.log').strip()
        caddy=run([*compose,'ps','-q','caddy'],'caddy-id.log').strip()
        run(['cp',caddy+':/data/caddy/pki/authorities/local/root.crt',str(output/'root.crt')],'export-root.log')
        run(['cp',str(output/'root.crt'),backend+':/tmp/rehearsal-root.crt'],'install-root.log')
        run(['exec','-i',backend,'python','-c',"import sys;open('/tmp/fixture-manifest.json','w').write(sys.stdin.read())"],
            'install-manifest.log',json.dumps(first))
        report.update(json.loads(run([*compose,'exec','-T','-e','ACCEPTANCE_FIXTURE_PASSWORD','backend','python','-'],
                                    'probe.log',PROBE)))
        report['no_published_ports']=True
        report['internal_network']=True
        report['compose_config_validated']=True
    finally:
        if owns_resources:
            run([*compose,'stop'],'stop.log')
        (output/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
