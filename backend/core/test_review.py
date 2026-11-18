import json
from datetime import timedelta
from unittest.mock import patch
from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import User,Course,Membership,KnowledgePoint,ReviewPlan,ReviewReminder
from .review_service import basis_for,ordered_steps,process_plan,explain
from .review_views import validate_schedule


class ReviewTests(TestCase):
    def setUp(self):
        self.teacher=User.objects.create_user('review-t@example.test','test-password')
        self.student=User.objects.create_user('review-s@example.test','test-password')
        self.peer=User.objects.create_user('review-p@example.test','test-password')
        self.course=Course.objects.create(name='Review',created_by=self.teacher)
        for u,r in [(self.teacher,'teacher'),(self.student,'student'),(self.peer,'student')]:
            Membership.objects.create(course=self.course,user=u,role=r)
        self.point=KnowledgePoint.objects.create(course=self.course,name='积分')
        self.sc=APIClient();self.sc.force_authenticate(self.student)
        self.base=f'/api/courses/{self.course.id}/review-plans/'

    def create(self):
        r=self.sc.post(self.base,{},format='json');self.assertEqual(r.status_code,201,r.data)
        return ReviewPlan.objects.get(pk=r.data['id'])

    def ready(self):
        plan=self.create()
        async def generated(steps):return [{**s,'explanation':'一般练习建议','cited_refs':s['refs']} for s in steps],'test-model'
        with patch('core.review_service.explain',side_effect=generated):self.assertTrue(process_plan(plan.id))
        plan.refresh_from_db();self.assertEqual(plan.status,'awaiting_confirmation')
        return plan

    def schedule(self):
        return {'timezone':'Asia/Shanghai','start_date':(timezone.now()+timedelta(days=2)).date().isoformat(),'local_time':'18:00','offset_days':[0,1,3]}

    def act(self,p,action='confirm',**extra):
        return self.sc.post(f'/api/review-plans/{p.id}/action/',{'action':action,'expected_revision':p.revision,'point_ids':[self.point.id],'schedule':self.schedule(),**extra},format='json')

    def test_queue_no_model_get_no_writes_and_owner_permission(self):
        with patch('core.review_service.explain') as model:
            p=self.create();model.assert_not_called()
            self.assertEqual(self.sc.get(self.base).status_code,200)
        self.assertEqual(ReviewReminder.objects.count(),0)
        self.assertEqual(self.sc.post(self.base,{},format='json').status_code,409)
        for u in [self.peer,self.teacher]:
            c=APIClient();c.force_authenticate(u)
            self.assertEqual(c.get(f'/api/review-plans/{p.id}/').status_code,403)
        c=APIClient();c.force_authenticate(self.teacher)
        self.assertEqual(c.post(self.base,{},format='json').status_code,403)

    def test_confirm_reschedule_idempotent_complete_and_cancel(self):
        p=self.ready();self.assertEqual(ReviewReminder.objects.count(),0)
        result=self.act(p);self.assertEqual(result.status_code,200,result.data)
        self.assertEqual(ReviewReminder.objects.count(),3)
        self.assertEqual(self.act(p).status_code,409)
        p.refresh_from_db();self.assertEqual(self.act(p,'reschedule').status_code,200)
        self.assertEqual(ReviewReminder.objects.filter(state='cancelled').count(),3)
        item=ReviewReminder.objects.filter(state='scheduled').first()
        for _ in range(2):self.assertEqual(self.sc.post(f'/api/review-reminders/{item.id}/',{'action':'complete'},format='json').status_code,200)
        p.refresh_from_db();self.assertEqual(self.act(p,'cancel').status_code,200)
        self.assertFalse(ReviewReminder.objects.filter(state='scheduled').exists())

    def test_stale_basis_blocks_confirmation_and_completion(self):
        p=self.ready();self.point.name='新名称';self.point.save()
        self.assertEqual(self.act(p).status_code,409)
        data=self.sc.get(f'/api/review-plans/{p.id}/').data
        self.assertTrue(data['stale']);self.assertEqual(data['steps'],[])
        self.assertFalse(ReviewReminder.objects.exists())

    def test_cancel_and_revocation_reject_late_result_and_duplicate_worker(self):
        p=self.create()
        async def late(steps):
            from asgiref.sync import sync_to_async
            await sync_to_async(ReviewPlan.objects.filter(pk=p.id).update)(status='cancelled')
            return steps,'late'
        with patch('core.review_service.explain',side_effect=late):self.assertFalse(process_plan(p.id))
        p.refresh_from_db();self.assertEqual(p.status,'cancelled')
        self.assertFalse(process_plan(p.id));self.assertFalse(ReviewReminder.objects.exists())
        p=self.create();Membership.objects.filter(course=self.course,user=self.student).delete()
        with patch('core.review_service.explain') as model:
            process_plan(p.id);model.assert_not_called()
        p.refresh_from_db();self.assertEqual(p.status,'failed')

    def test_order_unknown_is_not_weak_and_invalid_graph_fails(self):
        now=timezone.now();b=basis_for(self.course.id,self.student.id,now-timedelta(days=90),now)
        original=ordered_steps(b);self.assertEqual(original[0]['purpose'],'general')
        self.assertIn('暂无有效评分证据',original[0]['evidence_note'])
        b['graph']['nodes'].append({'id':999,'name':'先修','active':True,'revision':1})
        b['graph']['edges']=[{'prerequisite_id':999,'target_id':self.point.id,'sources':[]}]
        self.assertEqual([s['point_id'] for s in ordered_steps(b)],[999,self.point.id])
        b['graph']['nodes'][-1]['active']=False
        with self.assertRaises(ValueError):ordered_steps(b)
        b['graph']['nodes'][-1]['active']=True;b['graph']['edges'][0]['sources']=[{'current':False}]
        with self.assertRaises(ValueError):ordered_steps(b)
        b['graph']['edges'][0]['sources']=[]
        b['graph']['resources']=[{'point_id':self.point.id,'material_id':5,'sources':[]}]
        b['materials']=[{'id':5,'index_status':'ready','file_available':False}]
        with self.assertRaises(ValueError):ordered_steps(b)

    def test_model_cannot_add_refs_or_reorder_nodes(self):
        async def stream(messages):yield json.dumps({'steps':[{'point_id':self.point.id,'explanation':'建议','refs':['m999']}]}),'test'
        with patch('core.review_service.model_stream',side_effect=stream):
            with self.assertRaises(ValueError):async_to_sync(explain)([{'point_id':self.point.id,'refs':[]}])

    def test_schedule_validation_prerequisites_offsets_and_timezone(self):
        p=self.ready();p.steps[0]['prerequisite_ids']=[999]
        with self.assertRaises(ValueError):validate_schedule({'point_ids':[self.point.id],'schedule':self.schedule()},p)
        p.steps[0]['prerequisite_ids']=[]
        for change in [{'timezone':[]},{'offset_days':[1,0]},{'offset_days':[0,0]},{'offset_days':[True]},{'local_time':'bad'}]:
            with self.assertRaises(ValueError):validate_schedule({'point_ids':[self.point.id],'schedule':{**self.schedule(),**change}},p)
        self.assertEqual(len(validate_schedule({'point_ids':[self.point.id],'schedule':self.schedule()},p)[2]),3)

    def test_invalid_window_and_empty_graph(self):
        for data in [{'end':'bad'},{'start':'2026-01-01'},{'student_id':self.peer.id}]:
            self.assertEqual(self.sc.post(self.base,data,format='json').status_code,400)
        self.point.delete();self.assertEqual(self.sc.post(self.base,{},format='json').status_code,400)

    def test_weak_target_includes_strong_prerequisite(self):
        now=timezone.now();b=basis_for(self.course.id,self.student.id,now-timedelta(days=90),now)
        b['learning']['students'][0]['points'][0]['mastery']='0.4'
        b['graph']['nodes'].append({'id':999,'name':'先修','active':True,'revision':1})
        b['learning']['students'][0]['points'].append({'id':999,'mastery':'1','sample_size':1,'evidence':[]})
        b['graph']['edges']=[{'prerequisite_id':999,'target_id':self.point.id,'sources':[]}]
        steps=ordered_steps(b)
        self.assertEqual([s['purpose'] for s in steps],['prerequisite','weakness'])

    def test_dst_and_stale_reminder(self):
        from datetime import datetime,timezone as utc
        p=self.ready()
        with patch('core.review_views.timezone.now',return_value=datetime(2026,3,1,tzinfo=utc.utc)):
            for day,clock in [('2026-03-08','02:30'),('2026-11-01','01:30')]:
                schedule={'timezone':'America/New_York','start_date':day,'local_time':clock,'offset_days':[0]}
                with self.assertRaises(ValueError):validate_schedule({'point_ids':[self.point.id],'schedule':schedule},p)
        self.assertEqual(self.act(p).status_code,200)
        item=p.reminders.first();self.point.active=False;self.point.save()
        self.assertEqual(self.sc.post(f'/api/review-reminders/{item.id}/',{'action':'complete'},format='json').status_code,409)
        data=self.sc.get(f'/api/review-plans/{p.id}/').data
        self.assertTrue(all(not r['actionable'] and not r['due'] for r in data['reminders']))
