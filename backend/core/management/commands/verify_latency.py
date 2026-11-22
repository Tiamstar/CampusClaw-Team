"""Retained real-provider observations, without changing any formal grade or configuration."""
import json
import os
import time
import uuid
from decimal import Decimal
from pathlib import Path
import httpx
from django.core.management.base import BaseCommand, CommandError
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import User, Membership, SubmissionVersion, CourseworkTask, AgentThread, RequestMetric


class Command(BaseCommand):
    help='Observe three teaching skills and an actual full chat stream using explicitly authorized existing fixtures.'

    def add_arguments(self, parser):
        parser.add_argument('--real', action='store_true')
        parser.add_argument('--teacher', required=True)
        parser.add_argument('--student', required=True)
        parser.add_argument('--course-id', type=int, required=True)
        parser.add_argument('--version-id', type=int, required=True)
        parser.add_argument('--output', default='/tmp/latency-evidence.json')

    def handle(self, *args, **options):
        if not options['real'] or os.getenv('MODEL_PROVIDER','mock')=='mock':raise CommandError('Requires --real and a real provider')
        teacher=User.objects.get(email=options['teacher'],is_active=True)
        student=User.objects.get(email=options['student'],is_active=True)
        cid=options['course_id'];version=SubmissionVersion.objects.select_related('submission__assignment').get(pk=options['version_id'])
        if teacher==student or version.submission.student_id!=student.pk or version.submission.assignment.course_id!=cid:
            raise CommandError('Fixture does not belong to the specified student and course')
        for user,role in [(teacher,'teacher'),(student,'student')]:
            if not Membership.objects.filter(course_id=cid,user=user,role=role).exists():raise CommandError('Current course membership required')
        revision=version.grade_revisions.get(revision=version.grading_revision)
        item=next((r for r in revision.reviewed_items if Decimal(r['score'])<Decimal(r['maximum'])),None)
        old=CourseworkTask.objects.filter(version=version,kind='grading').order_by('pk').first()
        if not item or not old or not version.published_at:raise CommandError('Select an existing synthetic published wrong-answer fixture with a rubric')
        def grade():
            row=SubmissionVersion.objects.get(pk=version.pk)
            return {'score':str(row.score),'grading_revision':row.grading_revision,'published_at':row.published_at.isoformat() if row.published_at else None}
        report={'synthetic_fixture':True,'fixtures_retained':True,'course_id':cid,'version_id':version.pk,'grade_before':grade(),'provider':os.getenv('MODEL_PROVIDER'),'requests':[]}
        def save():Path(options['output']).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        save()
        with httpx.Client(base_url='http://127.0.0.1:8000/api/',timeout=110,trust_env=False) as tc,httpx.Client(base_url='http://127.0.0.1:8000/api/',timeout=110,trust_env=False) as sc:
            for client,user in [(tc,teacher),(sc,student)]:client.headers['Authorization']='Bearer '+str(RefreshToken.for_user(user).access_token)
            def post(client,path,body,status=202):
                response=client.post(path,json=body)
                report['requests'].append({'path_template':path.replace(str(cid),'[course]').replace(str(version.pk),'[version]'),'status':response.status_code,'request_id':response.headers.get('x-request-id')});save()
                if response.status_code!=status:raise CommandError(f'{path}: HTTP {response.status_code}')
                return response.json()
            jobs=[(tc,post(tc,f'submission-versions/{version.pk}/ai-tasks/',{'kind':'grading','request_key':uuid.uuid4().hex,'rubric':old.basis['rubric']})['id']),
                  (sc,post(sc,f'submission-versions/{version.pk}/ai-tasks/',{'kind':'explanation','request_key':uuid.uuid4().hex,'item_id':item['id']})['id']),
                  (sc,post(sc,f'courses/{cid}/guidance-tasks/',{'question':'耗时监控验收：请用简短提示解释定积分 ∫₀¹ 2x dx 的第一步，不直接给最终结果。','request_key':uuid.uuid4().hex})['id'])]
            report['task_ids']=[pk for _,pk in jobs];save()
            deadline=time.monotonic()+180
            pending=dict((pk,client) for client,pk in jobs)
            while pending and time.monotonic()<deadline:
                for pk,client in list(pending.items()):
                    response=client.get(f'coursework-tasks/{pk}/')
                    if response.status_code!=200:raise CommandError('Task status unavailable')
                    if response.json()['status'] not in ['queued','running']:pending.pop(pk)
                if pending:time.sleep(1)
            report['tasks']=list(CourseworkTask.objects.filter(pk__in=report['task_ids']).values('id','kind','status','started_at','created_at','finished_at','error'))
            thread=post(sc,'agent/threads/',{'course_id':cid,'title':'完整流式耗时验收（保留记录）'},201)
            report['thread_id']=thread['id'];save()
            started=time.monotonic()
            response=sc.post(f"agent/threads/{thread['id']}/messages/stream/",json={'content':'耗时监控验收。不要调用任何工具，仅用一句话说明链式法则的用途。','use_materials':False})
            report['stream']={'status':response.status_code,'message_end':'event: message_end' in response.text,'error_event':'event: error' in response.text,
                'client_elapsed_ms':round((time.monotonic()-started)*1000),'request_id':response.headers.get('x-request-id')}
            # The HTTP server's final response-close callback may follow the client receive.
            for _ in range(10):
                metric=RequestMetric.objects.filter(request_id=report['stream']['request_id']).first()
                if metric:break
                time.sleep(.1)
            report['stream']['metric']=list(RequestMetric.objects.filter(request_id=report['stream']['request_id']).values('duration_ms','outcome','streaming','route','course_id'))
            report['grade_after']=grade()
            report['teacher_dashboard']=tc.get(f'courses/{cid}/skill-monitor/?hours=6').json()
            report['student_monitor_status']=sc.get(f'courses/{cid}/skill-monitor/').status_code
            report['checks']={'all_tasks_completed':not pending and all(r['status'] in ['draft','succeeded'] for r in report['tasks']),
                'all_task_starts_recorded':all(r['started_at'] for r in report['tasks']),
                'formal_grade_unchanged':report['grade_before']==report['grade_after'],
                'stream_consumed_to_end':report['stream']['message_end'] and not report['stream']['error_event'],
                'full_stream_metric':bool(metric and metric.streaming and metric.outcome=='completed' and metric.course_id==cid and abs(metric.duration_ms-report['stream']['client_elapsed_ms'])<1000),
                'student_monitor_denied':report['student_monitor_status']==403}
            save()
            self.stdout.write(json.dumps({'course_id':cid,'task_ids':report['task_ids'],'thread_id':report['thread_id'],'checks':report['checks']},ensure_ascii=False))
            if not all(report['checks'].values()):raise CommandError('Some actual observations failed; all evidence and fixtures retained')
