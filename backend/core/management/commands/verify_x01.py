"""Retained two-student HTTP teaching loop, with explicitly synthetic peer/source."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlparse
import uuid

import httpx
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from core.models import (User, StoredFile, Material, KnowledgeEntry, KnowledgeChunk,
                         KnowledgePoint, GraphCandidate, QuizGradeRevision, ReviewPlan)
from core.graph_service import source_rows


class Command(BaseCommand):
    help = 'Retain a new course: concurrent quiz submit, 87/57 grades, mastery, graph and real worker review plans.'

    def add_arguments(self, parser):
        parser.add_argument('--retain-fixtures', action='store_true')
        parser.add_argument('--real', action='store_true')
        parser.add_argument('--teacher', required=True)
        parser.add_argument('--student', required=True)
        parser.add_argument('--base-url', default='http://127.0.0.1:8000')
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        parsed = urlparse(options['base_url'])
        if (not options['retain_fixtures'] or not options['real'] or parsed.scheme != 'http'
                or parsed.hostname not in {'localhost', '127.0.0.1'} or parsed.username or parsed.password
                or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
            raise CommandError('Requires --retain-fixtures --real and a plain loopback HTTP origin')
        if os.getenv('MODEL_PROVIDER', 'mock') == 'mock':
            raise CommandError('Real provider and running review worker required; no mock success claims')
        output = Path(options['output'])
        if output.exists():
            raise CommandError('Evidence already exists; select a new output path')
        teacher = User.objects.get(email=options['teacher'], is_active=True)
        student = User.objects.get(email=options['student'], is_active=True)
        if teacher == student or not teacher.can_create_course:
            raise CommandError('Distinct authorized existing teacher and student required')
        run_id = uuid.uuid4().hex
        report = {'run_id':run_id, 'started_at':timezone.now().isoformat(), 'checks':[],
                  'passed':False, 'fixtures_retained':True, 'transport':'actual_loopback_http',
                  'auth':'server-minted access JWT; not a password-login test',
                  'fixture_boundary':'one existing teacher/student; synthetic peer with unusable password; synthetic preindexed material and manually authored candidate; graph approval is HTTP, not model extraction',
                  'scope':'Codex local X01 engineering self-test; not two human users, browser demonstration, independent acceptance or capacity test'}

        def save():
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

        def check(name, ok, **facts):
            report['checks'].append({'name':name,'passed':bool(ok),**facts}); save()
            self.stdout.write(f'{name}: {bool(ok)}')
            if not ok:
                raise CommandError('X01 assertion failed; all records and evidence retained')

        save()
        peer = User.objects.create_user(f'x01-{run_id}@example.invalid', password=None,
                                       display_name='联调合成学生B（非真人）')
        report['synthetic_peer_id'] = peer.pk; save()
        users = [teacher, student, peer]
        with ExitStack() as stack:
            clients = [stack.enter_context(httpx.Client(base_url=options['base_url'].rstrip('/')+'/api/',
                trust_env=False, timeout=40, headers={'Authorization':'Bearer '+str(AccessToken.for_user(u))})) for u in users]
            tc, sc, pc = clients

            def call(client, method, path, body=None, expected=200, params=None):
                response = client.request(method,path,json=body,params=params)
                if response.status_code != expected:
                    report['failed_http'] = {'method':method,'path':path,'expected':expected,
                        'status':response.status_code,'request_id':response.headers.get('x-request-id')};save()
                    raise CommandError('Unexpected HTTP status; private business response not printed')
                return response.json()

            def post(client, path, body, expected=200):
                return call(client,'POST',path,body,expected)

            course = post(tc,'courses/',{'name':'CampusClaw 双学生并发联调 X01（保留记录）'},201)
            cid = course['id']; report.update(course_id=cid,join_code=course['join_code']);save()
            for client in [sc,pc]:post(client,'courses/join/',{'code':course['join_code']},201)
            # Explicit fixtures only: do not pretend that indexing or extraction ran.
            text = '自制X01联调讲义：基础概念是解题论证的先修知识；拓展应用为独立知识点。'
            file = StoredFile(course_id=cid,uploaded_by=teacher,original_name='X01自制联调讲义.txt',
                              size=len(text.encode()),kind='material')
            file.file.save('x01-guide.txt',ContentFile(text.encode()),save=True)
            material = Material.objects.create(course_id=cid,title='自制联调讲义（预索引夹具）',attachment=file)
            entry = KnowledgeEntry.objects.create(material=material,status='ready',body_text=text,
                                                   content_hash=hashlib.sha256(text.encode()).hexdigest())
            chunk = KnowledgeChunk.objects.create(entry=entry,chunk_index=0,status='ready',chunk_text=text)
            names = ['基础概念','解题论证','拓展应用']
            proposal = {'nodes':[{'key':str(i),'name':name,'source_ids':[chunk.pk]} for i,name in enumerate(names)],
                        'edges':[{'from':'0','to':'1','source_ids':[chunk.pk]}]}
            candidate = GraphCandidate.objects.create(course_id=cid,creator=teacher,status='awaiting_review',
                sources=source_rows(cid,[material.pk]),proposal=proposal,model='manual-fixture-not-model',settings_revision=0)
            approved = post(tc,f'graph/candidates/{candidate.pk}/review/',{'action':'approve','proposal':proposal,
                'reason':'回查自制讲义后批准；候选为人工夹具，不是模型抽取','expected_revision':0})
            check('graph_teacher_approval',approved['status']=='approved',candidate_id=candidate.pk,material_id=material.pk)
            points = {p.name:p.pk for p in KnowledgePoint.objects.filter(course_id=cid)}
            questions = []
            for kind,options_,values in [('single',['A','B'],['0']),('multiple',['A','B','C'],['0','2']),
                                          ('boolean',[],['true']),('blank',[],['答案','answer']),('short',[],['评分参考'])]:
                question = post(tc,f'courses/{cid}/questions/',{'kind':kind,'body':f'X01 {kind} 自制题，$x^2$ 为公式展示对照',
                    'options':options_,'answer':{'values':values},'score':'20','explanation':'仅用于合成联调，不是教学测评结论',
                    'point_ids':[points['解题论证'] if kind=='short' else points['基础概念']]},201)
                questions.append(question)
            now = timezone.now()
            quiz = post(tc,f'courses/{cid}/quizzes/',{'title':'X01 五题并发交卷与版本回查（保留）',
                'opens_at':(now-timedelta(minutes=1)).isoformat(),'closes_at':(now+timedelta(days=7)).isoformat(),
                'answers_at':(now+timedelta(days=7)).isoformat(),'time_limit_minutes':60,'max_attempts':2,
                'rules':[{'kind':q['kind'],'count':1} for q in questions]},201)
            qid = quiz['id'];report['quiz_id']=qid;save()
            post(tc,f'quizzes/{qid}/publish/',{'action':'publish'})
            attempts = [post(client,f'quizzes/{qid}/attempts/',{},201) for client in [sc,pc]]
            report['attempt_ids']=[a['id'] for a in attempts];save()
            check('paper_answers_hidden',all('answer' not in q and 'explanation' not in q for a in attempts for q in a['paper']))
            saved_answers=[]
            for index,(client,attempt) in enumerate(zip([sc,pc],attempts)):
                answers = {str(q['id']):({'text':'自制论证过程','image_ids':[]} if q['kind']=='short' else
                    q['answer']['values'] if q['kind']=='multiple' else '答案' if q['kind']=='blank' else q['answer']['values'][0]) for q in questions}
                if index:
                    for q in questions:
                        if q['kind']=='multiple':answers[str(q['id'])]=['1']
                        if q['kind']=='blank':answers[str(q['id'])]='错误对照'
                saved_answers.append(answers)
                payload = {'answers':answers,'expected_revision':0,'key':'x01-save'}
                call(client,'PUT',f"quiz-attempts/{attempt['id']}/answers/",payload)
                replay = call(client,'PUT',f"quiz-attempts/{attempt['id']}/answers/",payload)
                restored = call(client,'GET',f"quiz-attempts/{attempt['id']}/")
                check('saved_answers_restore',replay['replayed'] and restored['answers']==answers and restored['answer_revision']==1,attempt_id=attempt['id'])
                call(client,'PUT',f"quiz-attempts/{attempt['id']}/answers/",{**payload,'key':'stale-save'},409)
            # Four separate connections start together: both students and a
            # duplicate per student, exercising actual server transactions.
            barrier = threading.Barrier(4)
            def concurrent_submit(index):
                user = [student,peer][index//2];attempt = attempts[index//2]
                with httpx.Client(base_url=options['base_url'].rstrip('/')+'/api/',trust_env=False,timeout=40,
                    headers={'Authorization':'Bearer '+str(AccessToken.for_user(user))}) as client:
                    barrier.wait(timeout=10);start=time.monotonic()
                    response=client.post(f"quiz-attempts/{attempt['id']}/submit/",json={})
                    return {'attempt_id':attempt['id'],'status':response.status_code,
                            'duration_ms':round((time.monotonic()-start)*1000,3),'request_id':response.headers.get('x-request-id')}
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes=list(pool.map(concurrent_submit,range(4)))
            report['concurrent_submit']=outcomes;save()
            check('concurrent_duplicate_submits',all(r['status']==200 for r in outcomes))
            for attempt in attempts:
                count=QuizGradeRevision.objects.filter(attempt_id=attempt['id']).count()
                check('single_automatic_grade_revision',count==1,attempt_id=attempt['id'],revision_count=count)
            post(tc,f'quizzes/{qid}/publish/',{'action':'grades_publish'},409)
            for index,(client,attempt) in enumerate(zip([sc,pc],attempts)):
                aid=attempt['id'];before=call(tc,'GET',f'quiz-attempts/{aid}/')
                check('submitted_last_saved_answers',before['answers']==saved_answers[index] and before['status']=='submitted',attempt_id=aid)
                call(client,'PUT',f'quiz-attempts/{aid}/answers/',{'answers':{},'expected_revision':1,'key':'after-submit'},409)
                auto=sum(Decimal(v) for v in before['scores'].values() if v is not None)
                check('automatic_objective_score',auto==[Decimal(80),Decimal(40)][index],attempt_id=aid,score=str(auto))
                check('unpublished_score_hidden','scores' not in call(client,'GET',f'quiz-attempts/{aid}/'))
                scores={k:('10' if index==0 else '20') if v is None else v for k,v in before['scores'].items()}
                payload={'scores':scores,'feedback':{},'reason':'X01逐题人工复核合成答案，保留版本','expected_revision':1}
                reviewed=post(tc,f'quiz-attempts/{aid}/review/',payload)
                check('formal_quiz_score',Decimal(reviewed['total'])==[Decimal(90),Decimal(60)][index] and reviewed['grade_revision']==2,
                      attempt_id=aid,total=reviewed['total'],grade_revision=reviewed['grade_revision'])
                post(tc,f'quiz-attempts/{aid}/review/',payload,409)
            post(tc,f'quizzes/{qid}/publish/',{'action':'grades_publish'})
            statistics=call(tc,'GET',f'quizzes/{qid}/statistics/')
            check('two_student_statistics_limited',len(statistics['groups'])==1 and statistics['groups'][0]['sample_size']==2
                  and all(q['discrimination'] is None for q in statistics['groups'][0]['questions']))
            assignment=post(tc,f'courses/{cid}/assignments/',{'title':'X01 加权成绩基准作业（保留）','max_score':'100',
                'due_at':(now+timedelta(days=7)).isoformat()},201)
            report['assignment_id']=assignment['id'];save()
            for index,client in enumerate([sc,pc]):
                version=post(client,f"assignments/{assignment['id']}/submit/",{'text_content':'合成联调答案，保留验收过程','submission_key':'x01-submit'},201)
                post(tc,f"submission-versions/{version['id']}/grade/",{'score':['80','50'][index],'feedback':'合成基准评分',
                    'expected_revision':0,'published':True,'reason':'X01基准评分'})
            call(tc,'PUT',f'courses/{cid}/grade-policy/',{'expected_revision':0,'items':[
                {'kind':'assignment','source_id':assignment['id'],'weight':'30'}, {'kind':'quiz','source_id':qid,'weight':'70'}]})
            snapshot=post(tc,f'courses/{cid}/gradebook/',{},201)
            report['snapshot_id']=snapshot['id'];save()
            post(tc,f"grade-snapshots/{snapshot['id']}/publication/",{'published':True})
            window={'start':(now-timedelta(days=1)).isoformat(),'end':timezone.now().isoformat()}
            report['window']=window;report['student_chains']=[];save()
            for index,(client,user,attempt) in enumerate(zip([sc,pc],[student,peer],attempts)):
                visible=call(client,'GET',f'courses/{cid}/gradebook/')['snapshot']
                rows=visible['rows'];row=rows[0]
                recomputed=sum((Decimal(e['score'])/Decimal(e['max_score'])*Decimal(i['weight']) for e,i in zip(row['entries'],visible['items'])),Decimal(0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                check('private_weighted_total',len(rows)==1 and row['student_id']==user.pk and row['total']==str(recomputed)==['87.00','57.00'][index],
                      student_id=user.pk,total=row['total'],snapshot_id=visible['id'])
                entry=next(e for e in row['entries'] if e['kind']=='quiz')
                check('gradebook_same_quiz_revision',entry['source_record']==attempt['id'] and entry['grade_revision']==2,attempt_id=attempt['id'])
                learning=call(client,'GET',f'courses/{cid}/learning/',params=window)
                graph=call(client,'GET',f'courses/{cid}/graph/',params=window)
                metrics={p['id']:p for p in learning['students'][0]['points']}
                evidence=[e for p in metrics.values() for e in p['evidence']]
                check('learning_same_quiz_revision',len(evidence)==5 and all(e['attempt_id']==attempt['id'] and e['grade_revision']==2 for e in evidence))
                check('known_mastery_recomputed',Decimal(metrics[points['基础概念']]['mastery'])==[Decimal(1),Decimal('.5')][index]
                      and Decimal(metrics[points['解题论证']]['mastery'])==[Decimal('.5'),Decimal(1)][index])
                check('graph_learning_same_version',graph['learning_version']==learning['data_version'] and all(n['metric']==metrics[n['id']] for n in graph['nodes']))
                check('unanswered_point_unknown',metrics[points['拓展应用']]['mastery'] is None and metrics[points['拓展应用']]['sample_size']==0)
                report['student_chains'].append({'student_id':user.pk,'attempt_id':attempt['id'],'grade_revision':2,
                    'snapshot_id':visible['id'],'total':row['total'],'learning_version':learning['data_version'],
                    'graph_revision':graph['revision'],'points':[{'id':p['id'],'mastery':p['mastery'],'sample_size':p['sample_size']} for p in metrics.values()]});save()
            plans=[post(client,f'courses/{cid}/review-plans/',window,201) for client in [sc,pc]]
            report['plan_ids']=[p['id'] for p in plans];save()
            deadline=time.monotonic()+180
            while True:
                plans=[call(client,'GET',f"review-plans/{p['id']}/") for client,p in zip([sc,pc],plans)]
                if all(p['status'] not in {'queued','running'} for p in plans):break
                if time.monotonic()>deadline:raise CommandError('Worker wait timed out; queued/running tasks retained, do not restart blindly')
                time.sleep(2)
            report['review_task_states']=[{'id':p['id'],'status':p['status'],'model':p['model']} for p in plans];save()
            for client,user,attempt,plan in zip([sc,pc],[student,peer],attempts,plans):
                check('real_worker_plan_ready',plan['status']=='awaiting_confirmation' and bool(plan['model']) and 'mock' not in plan['model'].lower(),plan_id=plan['id'])
                basis=ReviewPlan.objects.get(pk=plan['id']).basis
                learning=call(client,'GET',f'courses/{cid}/learning/',params=window)
                check('review_same_learning_version',not plan['stale'] and basis['learning']['data_version']==learning['data_version'])
                order=[s['point_id'] for s in plan['steps']]
                refs=[e for s in plan['steps'] for e in s['evidence']]
                check('review_same_quiz_evidence',bool(refs) and all(e['attempt_id']==attempt['id'] and e['grade_revision']==2 for e in refs))
                check('review_prerequisite_order',all(order.index(p)<order.index(s['point_id']) for s in plan['steps'] for p in s['prerequisite_ids']))
                check('no_reminders_before_confirmation',plan['reminders']==[])
                payload={'action':'confirm','expected_revision':plan['revision'],'point_ids':order,'schedule':{
                    'timezone':'Asia/Shanghai','start_date':(timezone.now()+timedelta(days=2)).date().isoformat(),
                    'local_time':'18:00','offset_days':[0,1,3]}}
                confirmed=post(client,f"review-plans/{plan['id']}/action/",payload)
                post(client,f"review-plans/{plan['id']}/action/",payload,409)
                current=call(client,'GET',f"review-plans/{plan['id']}/")
                keys=[(r['schedule_revision'],r['point_id'],r['offset_days']) for r in current['reminders']]
                check('confirmed_reminders_unique',confirmed['status']=='active' and len(keys)==len(set(keys))==len(order)*3,
                      plan_id=plan['id'],reminders=len(keys),student_id=user.pk)
                chain=next(c for c in report['student_chains'] if c['student_id']==user.pk)
                chain.update(plan_id=plan['id'],plan_basis_version=plan['basis_version'],plan_learning_version=basis['learning']['data_version'],
                             plan_order=order,reminders=len(keys));save()
                call(tc,'GET',f"review-plans/{plan['id']}/",expected=403)
            for own,other in [(sc,1),(pc,0)]:
                call(own,'GET',f"quiz-attempts/{attempts[other]['id']}/",expected=403)
                call(own,'GET',f"review-plans/{plans[other]['id']}/",expected=403)
                call(own,'GET',f'courses/{cid}/learning/',expected=403,params={**window,'student_id':[student.pk,peer.pk][other]})
            check('peer_answer_learning_plan_privacy',True)
        report['passed']=True;report['finished_at']=timezone.now().isoformat();save()
