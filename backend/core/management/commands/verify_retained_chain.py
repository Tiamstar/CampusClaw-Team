"""Read-only HTTP cross-module trace of explicitly selected retained fixtures."""
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import httpx
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import (User, Membership, GradeSnapshot, QuizAttempt, ReviewPlan,
                         ForumDraft, ForumReply, ForumTodo)
from core.forum_service import sources_current


class Command(BaseCommand):
    help = 'Check existing quiz/grade/mastery/graph/review and forum provenance; no business writes or model calls.'

    def add_arguments(self, parser):
        parser.add_argument('--teacher', required=True)
        parser.add_argument('--student', required=True)
        parser.add_argument('--course-id', required=True, type=int)
        parser.add_argument('--snapshot-id', required=True, type=int)
        parser.add_argument('--plan-id', required=True, type=int)
        parser.add_argument('--draft-id', required=True, type=int)
        parser.add_argument('--output', default='/tmp/retained-chain-evidence.json')

    def handle(self, *args, **options):
        cid = options['course_id']
        teacher = User.objects.get(email=options['teacher'], is_active=True)
        student = User.objects.get(email=options['student'], is_active=True)
        for user, role in [(teacher,'teacher'),(student,'student')]:
            if not Membership.objects.filter(course_id=cid,user=user,role=role).exists():
                raise CommandError('Current authorized membership required')
        snapshot = GradeSnapshot.objects.get(pk=options['snapshot_id'],course_id=cid)
        plan = ReviewPlan.objects.get(pk=options['plan_id'],course_id=cid,owner=student)
        draft = ForumDraft.objects.select_related('post').get(pk=options['draft_id'],post__course_id=cid)
        report = {'observed_at':timezone.now().isoformat(),'course_id':cid,'snapshot_id':snapshot.pk,
                  'plan_id':plan.pk,'draft_id':draft.pk,'checks':[],
                  'scope':'Read-only current retained single-student chain; not a new two-student concurrent X01/X02 run or independent member acceptance',
                  'business_writes':False,'model_calls':False}
        def save():
            Path(options['output']).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        def check(name, ok, **facts):
            report['checks'].append({'name':name,'passed':bool(ok),**facts});save()
            self.stdout.write(f'{name}: {bool(ok)}')
        save()
        with httpx.Client(base_url='http://127.0.0.1:8000/api/',trust_env=False,timeout=30) as sc, httpx.Client(base_url='http://127.0.0.1:8000/api/',trust_env=False,timeout=30) as tc:
            for client,user in [(sc,student),(tc,teacher)]:
                client.headers['Authorization']='Bearer '+str(RefreshToken.for_user(user).access_token)
            def get(client,path,params=None):
                response=client.get(path,params=params)
                if response.status_code!=200:raise CommandError(f'Read HTTP {response.status_code}; evidence retained')
                return response.json()
            window=plan.basis['learning']['window']
            params={k:window[k] for k in ['start','end']}
            learning=get(sc,f'courses/{cid}/learning/',params)
            graph=get(sc,f'courses/{cid}/graph/',params)
            visible=get(sc,f'courses/{cid}/gradebook/')['snapshot']
            detail=get(sc,f'review-plans/{plan.pk}/')
            check('published_snapshot_current',visible is not None and visible['id']==snapshot.pk and not visible['stale'])
            row=next(r for r in snapshot.rows if r['student_id']==student.pk)
            total=sum((Decimal(e['score'])/Decimal(e['max_score'])*Decimal(i['weight']) for e,i in zip(row['entries'],snapshot.items)),Decimal(0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            check('weighted_total_recomputed',str(total)==row['total'],total=str(total))
            quiz_entries=[e for e in row['entries'] if e['kind']=='quiz']
            points=learning['students'][0]['points']
            used=[e for p in points for e in p['evidence']]
            check('quiz_sources_present',bool(quiz_entries) and bool(used))
            for entry in quiz_entries:
                attempt=QuizAttempt.objects.get(pk=entry['source_record'],student=student,quiz__course_id=cid)
                matching=[e for e in used if e['attempt_id']==attempt.pk]
                score=sum((Decimal(str(v)) for v in attempt.scores.values()),Decimal(0))
                check('quiz_grade_version_matches',attempt.grade_revision==entry['grade_revision'] and all(e['grade_revision']==attempt.grade_revision for e in matching) and bool(matching) and score==Decimal(entry['score']),attempt_id=attempt.pk,grade_revision=attempt.grade_revision,score=str(score))
            check('graph_learning_version_same',graph['learning_version']==learning['data_version'])
            nodes={n['id']:n for n in graph['nodes']}
            for point in points:
                metric=nodes[point['id']]['metric']
                check('point_metric_same',metric==point,point_id=point['id'],mastery=point['mastery'],samples=point['sample_size'])
            check('review_basis_current',not detail['stale'] and learning['data_version']==plan.basis['learning']['data_version'])
            by_point={p['id']:p for p in points}
            check('review_evidence_matches',bool(detail['steps']) and all(s['evidence']==by_point[s['point_id']]['evidence'] and s['mastery']==by_point[s['point_id']]['mastery'] for s in detail['steps']))
            order=[s['point_id'] for s in detail['steps']]
            check('prerequisite_order',bool(order) and all(order.index(p)<order.index(s['point_id']) for s in detail['steps'] for p in s['prerequisite_ids']))
            reminders=detail['reminders'];keys=[(r['schedule_revision'],r['point_id'],r['offset_days']) for r in reminders]
            check('confirmed_reminders_unique',detail['status']=='active' and bool(detail['confirmed_at']) and bool(reminders) and len(keys)==len(set(keys)),reminder_count=len(reminders))
            check('teacher_cannot_read_private_plan',tc.get(f'review-plans/{plan.pk}/').status_code==403)
            replies=get(sc,f'forum/posts/{draft.post_id}/replies/')['items']
            linked=[r for r in replies if r['draft_id']==draft.pk]
            record=ForumReply.objects.filter(draft=draft).first()
            check('teacher_confirmed_forum_reply',draft.status=='published' and draft.confirmed_by_id==teacher.pk and record is not None and record.teacher_answer and len(linked)==1)
            check('forum_citations_current',bool(draft.citations) and sources_current(draft),citation_count=len(draft.citations))
            todos=ForumTodo.objects.filter(post_id=draft.post_id)
            check('answered_todos_closed',todos.exists() and not todos.filter(closed_at__isnull=True).exists(),todo_count=todos.count())
            similar=get(sc,f'courses/{cid}/forum/similar/',{'q':draft.post.title})
            check('similarity_self_control',any(r['id']==draft.post_id for r in similar.get('items',[])),status=similar.get('status'))
        report['passed']=all(r['passed'] for r in report['checks']);save()
        if not report['passed']:raise CommandError('Retained chain checks failed; original records unchanged')
