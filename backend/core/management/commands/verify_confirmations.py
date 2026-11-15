"""Prepare retained benign MCP confirmation fixtures; never auto-confirm."""
import json
import os
from pathlib import Path
import httpx
from django.core.management.base import BaseCommand, CommandError
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import User, MCPServer, ToolConfirmation, AgentRun


class Command(BaseCommand):
    help='Create a synthetic course using two authorized existing accounts and pause at MCP confirmation.'

    def add_arguments(self,parser):
        parser.add_argument('--real',action='store_true')
        parser.add_argument('--teacher',required=True)
        parser.add_argument('--student',required=True)
        parser.add_argument('--output',default='/tmp/confirmation-evidence.json')

    def handle(self,*args,**options):
        if not options['real'] or os.getenv('MODEL_PROVIDER','mock')=='mock':
            raise CommandError('Requires --real and a configured real provider')
        teacher=User.objects.get(email=options['teacher'],is_active=True)
        student=User.objects.get(email=options['student'],is_active=True)
        if teacher==student or not teacher.can_create_course:raise CommandError('Select distinct teacher/student')
        server=MCPServer.objects.get(name='platform-tools',is_shared=True,connected=True)
        if not any(t['name']=='formula_hint' for t in server.tools):raise CommandError('formula_hint unavailable')
        report={'synthetic_only':True,'fixtures_retained':True,'auto_confirmation':False,'provider':os.getenv('MODEL_PROVIDER')}
        def save():Path(options['output']).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        with httpx.Client(base_url='http://127.0.0.1:8000/api/',timeout=110,trust_env=False) as tc,httpx.Client(base_url='http://127.0.0.1:8000/api/',timeout=110,trust_env=False) as sc:
            for client,user in [(tc,teacher),(sc,student)]:client.headers['Authorization']='Bearer '+str(RefreshToken.for_user(user).access_token)
            def post(client,path,body,status=201):
                response=client.post(path,json=body)
                if response.status_code!=status:raise CommandError(f'{path}: HTTP {response.status_code}')
                return response.json()
            course=post(tc,'courses/',{'name':'CampusClaw MCP 一次性确认验收（保留记录）'})
            cid=course['id'];report.update(course_id=cid,join_code=course['join_code']);save()
            post(sc,'courses/join/',{'code':course['join_code']})
            response=tc.put(f'courses/{cid}/assistant/',json={'revision':0,'app_id':'general','template':'你是数学学习助教。用户明确指定工具时请调用该工具。工具请求等待确认不代表已经执行，不要声称已完成。','skill_ids':[],'mcp_refs':['formula_hint@platform-tools'],'use_knowledge':False})
            if response.status_code!=200:raise CommandError('Cannot bind synthetic course tool')
            tool=f'mcp_{server.pk}_formula_hint'
            threads={}
            for role,client in [('teacher',tc),('student',sc)]:
                thread=post(client,'agent/threads/',{'course_id':cid,'title':'MCP 确认验收 · '+role})
                threads[role]=thread['id']
            report['threads']=threads;save()
            response=sc.post(f"agent/threads/{threads['student']}/messages/stream/",json={'content':'请调用 formula_hint 工具，参数 topic 为“复合函数求导”，不要自行代替工具回答。','use_materials':False})
            if response.status_code!=200:raise CommandError('Model stream failed')
            report['stream']=response.text
            report['model_pending']=ToolConfirmation.objects.filter(thread_id=threads['student'],status='pending').exists()
            # Separate manual fixture ensures the teacher can inspect and cancel one action.
            report['teacher_manual']=post(tc,f"agent/threads/{threads['teacher']}/tool-test/",{'name':tool,'arguments':{'topic':'平方根求导（取消对照）'}},200)
            report['before_browser']=list(ToolConfirmation.objects.filter(thread__course_id=cid).values('id','thread_id','status','started_at'))
            report['before_browser']=[{k:str(v) if k=='id' else v for k,v in row.items()} for row in report['before_browser']]
            report['run_ids']=list(AgentRun.objects.filter(thread__course_id=cid).values_list('id',flat=True));save()
            self.stdout.write(json.dumps({k:report[k] for k in ['course_id','join_code','threads','model_pending','run_ids']},ensure_ascii=False))
