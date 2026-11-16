import asyncio
import json
import os
from contextlib import aclosing
from datetime import timedelta
from unittest.mock import patch
from asgiref.sync import async_to_sync, sync_to_async
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from . import test_homework, coursework_service as service
from .model_telemetry import Usage, model_context, measured_stream, observe_usage, usage_sink
from .models import (ModelCall, AuditEvent, CourseworkTask, CourseworkSettings, Membership,
                     SkillMetricSample, SkillAlertEvent, SkillMonitorHeartbeat)
from .skill_monitor import evaluate, dashboard


class UsageTests(SimpleTestCase):
    def test_openai_cumulative_snapshots_and_cache(self):
        u=Usage(); frame={'usage':{'prompt_tokens':20,'completion_tokens':4,'total_tokens':24,'prompt_tokens_details':{'cached_tokens':10}}}
        u.observe(frame,'openai');u.observe(frame,'openai')
        self.assertEqual(u.result('openai',True)['total_tokens'],24)
        self.assertEqual(u.result('openai',True)['usage_state'],'complete')
        self.assertEqual(u.result('openai',False)['usage_state'],'partial')

    def test_anthropic_start_delta_and_cache(self):
        u=Usage();u.observe({'type':'message_start','message':{'usage':{'input_tokens':3,'output_tokens':0,'cache_read_input_tokens':10,'cache_creation_input_tokens':4}}},'anthropic')
        u.observe({'type':'message_delta','usage':{'output_tokens':6}},'anthropic')
        result=u.result('anthropic',True)
        self.assertEqual((result['input_tokens'],result['output_tokens'],result['total_tokens']),(17,6,23))

    def test_missing_mock_and_invalid_are_not_zero(self):
        self.assertEqual(Usage().result('openai',True)['usage_state'],'missing')
        self.assertIsNone(Usage().result('openai',True)['total_tokens'])
        self.assertEqual(Usage().result('mock',True)['usage_state'],'mock')
        for value in [-1,True,'3',1.5,10**13]:
            u=Usage();u.count('input_tokens',value);self.assertEqual(u.result('openai',True)['usage_state'],'invalid')
        for counts in [(4,3,8),(4,3,7)]:
            u=Usage();u.observe({'usage':dict(zip(['prompt_tokens','completion_tokens','total_tokens'],counts))},'openai')
            if counts[-1]==8:self.assertIsNone(u.result('openai',True)['total_tokens'])
            else:
                u.count('input_tokens',2);self.assertEqual(u.result('openai',True)['usage_state'],'invalid')


class TeachingTests(TestCase):
    setUp=test_homework.HomeworkTests.setUp

    def guide(self,key='guide',question='integral hint'):
        return self.sc.post(f'/api/courses/{self.course.pk}/guidance-tasks/',{'question':question,'request_key':key},format='json')

    def run_guide(self,pk,text='Try the antiderivative $x^2$.',hits=None,hook=None):
        async def stream(*args,**kwargs):
            if hook:await sync_to_async(hook)()
            yield text,'test-model'
        async def search(*args):return hits or []
        with patch.object(service,'model_stream',stream),patch('core.agent_runtime.search',search):service.process(pk)
        return CourseworkTask.objects.get(pk=pk)

    def test_guide_readonly_enqueue_private_and_cancel_retry(self):
        url=f'/api/courses/{self.course.pk}/guidance-tasks/'
        with patch.object(service,'generate') as external:
            self.assertEqual(self.sc.get(url).data,[])
            self.assertEqual(CourseworkSettings.objects.count(),0)
            first=self.guide();self.assertEqual(first.status_code,202)
            self.assertEqual(self.guide().data['id'],first.data['id'])
            self.assertEqual(self.guide('another').status_code,409)
            self.assertEqual(self.guide(question='different').status_code,409)
            external.assert_not_called()
        pk=first.data['id'];detail=f'/api/coursework-tasks/{pk}/'
        self.assertEqual(self.tc.get(detail).status_code,404)
        self.assertEqual(self.pc.get(detail).status_code,404)
        self.assertEqual(self.tc.get(url).data,[])
        self.assertEqual(self.sc.post(detail,{'action':'cancel','expected_revision':99},format='json').status_code,409)
        cancelled=self.sc.post(detail,{'action':'cancel','expected_revision':0},format='json');self.assertEqual(cancelled.data['status'],'cancelled')
        retried=self.sc.post(detail,{'action':'retry','expected_revision':1,'request_key':'retry'},format='json')
        self.assertEqual(retried.status_code,202);self.assertEqual(retried.data['retry_of_id'],pk)
        self.assertIsNone(CourseworkTask.objects.get(pk=retried.data['id']).version_id)

    def test_guidance_empty_results_and_actual_citations(self):
        pk=self.guide().data['id'];row=self.run_guide(pk)
        self.assertEqual(row.status,'succeeded');self.assertIn('课程资料未命中',row.result['explanation']);self.assertEqual(row.result['citations'],[])
        pk=self.guide('two').data['id'];hits=[{'material_id':1,'chunk_id':2,'title':'Text','excerpt':'antiderivative'}]
        row=self.run_guide(pk,'See [m1:c2], try $x^2$.',hits)
        self.assertEqual(row.status,'succeeded');self.assertEqual(row.result['citations'],hits)
        pk=self.guide('three').data['id'];row=self.run_guide(pk,'Invented [m9:c9]',hits)
        self.assertEqual(row.status,'failed');self.assertEqual(row.result,{})

    def test_guidance_disable_and_membership_revocation(self):
        pk=self.guide().data['id'];CourseworkSettings.objects.create(course=self.course,guidance_enabled=False,revision=1)
        with patch.object(service,'generate') as external:
            service.process(pk);external.assert_not_called()
        self.assertEqual(CourseworkTask.objects.get(pk=pk).status,'failed')
        self.assertEqual(self.guide('two').status_code,409)
        CourseworkSettings.objects.all().delete();pk=self.guide('three').data['id']
        Membership.objects.filter(user=self.student,course=self.course).delete()
        service.process(pk);self.assertEqual(CourseworkTask.objects.get(pk=pk).status,'failed')
        self.assertEqual(self.sc.get(f'/api/coursework-tasks/{pk}/').status_code,404)

    def test_guidance_late_result_cannot_restore_cancelled_task(self):
        pk=self.guide().data['id']
        def cancel():
            row=CourseworkTask.objects.get(pk=pk);service.finish(row,'cancelled')
        row=self.run_guide(pk,hook=cancel)
        self.assertEqual(row.status,'cancelled');self.assertEqual(row.result,{})

    def test_settings_three_switches_legacy_compatibility_and_conflict(self):
        url=f'/api/courses/{self.course.pk}/coursework-settings/'
        self.assertTrue(self.tc.get(url).data['guidance_enabled'])
        data={'grading_enabled':True,'explanation_enabled':True,'guidance_enabled':False,'expected_revision':0}
        self.assertEqual(self.tc.post(url,data,format='json').status_code,200)
        self.assertEqual(self.tc.post(url,data,format='json').status_code,409)
        data.pop('guidance_enabled');data['expected_revision']=1
        self.assertFalse(self.tc.post(url,data,format='json').data['guidance_enabled'])
        self.assertEqual(self.sc.post(url,data,format='json').status_code,403)

    def test_measured_stream_complete_cancel_failure_timeout_and_metadata(self):
        async def impl(*args):
            observe_usage({'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}},'openai')
            yield 'private text','model'
        async def collect():
            async with aclosing(measured_stream(impl,[{'content':'private question'}])) as stream:
                async for _ in stream:pass
            self.assertIsNone(usage_sink.get())
        async def close():
            stream=measured_stream(impl,[]);await anext(stream);await stream.aclose()
        async def fail(*args):
            raise TimeoutError('private URL/key');yield
        async def failure():
            async for _ in measured_stream(fail,[]):pass
        with patch.dict(os.environ,{'MODEL_PROVIDER':'openai','MODEL_NAME':'test'}),model_context(course_id=self.course.pk,actor_id=self.student.pk,skill_id=service.SKILLS['guidance']):
            async_to_sync(collect)();async_to_sync(close)()
            with self.assertRaises(TimeoutError):async_to_sync(failure)()
        rows=list(ModelCall.objects.order_by('started_at'))
        self.assertEqual([r.status for r in rows],['succeeded','cancelled','failed'])
        self.assertEqual([r.usage_state for r in rows],['complete','partial','missing'])
        self.assertEqual(rows[0].total_tokens,12);self.assertEqual(rows[2].error_code,'timeout')
        self.assertNotIn('private',str(list(ModelCall.objects.values())))
        self.assertEqual(AuditEvent.objects.filter(action='model.call').count(),3)

    def test_gateway_trailing_usage_and_generator_connection_closure(self):
        import httpx
        from .agent_runtime import model_stream
        wire='data: '+json.dumps({'choices':[{'delta':{'content':'hint'},'finish_reason':None}]})+'\n\n'
        wire+='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\n\n'
        wire+='data: '+json.dumps({'choices':[],'usage':{'prompt_tokens':9,'completion_tokens':2,'total_tokens':11}})+'\n\n'+'data: [DONE]\n\n'
        requests=[]
        def handle(request):
            requests.append(json.loads(request.content));return httpx.Response(200,text=wire)
        async def collect():
            client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
            with patch('core.agent_runtime.httpx.AsyncClient',return_value=client):
                async with aclosing(model_stream([{'role':'user','content':'private'}])) as stream:
                    result=[item async for item in stream]
                self.assertTrue(client.is_closed)
            return result
        with patch.dict(os.environ,{'MODEL_PROVIDER':'openai','MODEL_NAME':'test','MODEL_API_BASE':'https://example.test/v1','MODEL_API_KEY':'fixture'}):
            self.assertEqual(async_to_sync(collect)(),[('hint','test')])
        self.assertTrue(requests[0]['stream_options']['include_usage'])
        row=ModelCall.objects.get();self.assertEqual(row.usage_state,'complete');self.assertEqual(row.total_tokens,11)

    def test_monitor_permissions_readonly_and_missing_values(self):
        url=f'/api/courses/{self.course.pk}/skill-monitor/'
        self.assertEqual(self.sc.get(url).status_code,403)
        self.assertEqual(self.tc.get(url+'?hours=2').status_code,400)
        result=self.tc.get(url);self.assertEqual(result.status_code,200)
        self.assertTrue(result.data['monitor_stale']);self.assertIsNone(result.data['skills'][0]['total_tokens'])
        self.assertEqual(SkillMonitorHeartbeat.objects.count(),0);self.assertEqual(SkillMetricSample.objects.count(),0)
        self.assertNotIn('question',str(result.data))

    @override_settings(SKILL_ALERT_FOR_SECONDS=0, SKILL_ALERT_RECOVERY_SECONDS=0)
    def test_monitor_aggregation_tokens_p95_business_failure_and_alert_lifecycle(self):
        now=timezone.now();skill=service.SKILLS['guidance']
        pk=self.guide().data['id'];CourseworkTask.objects.filter(pk=pk).update(created_at=now-timedelta(seconds=90))
        for i in range(5):ModelCall.objects.create(course=self.course,skill_id=skill,provider='openai',model='test',status='succeeded',duration_ms=(i+1)*10000,usage_state='complete',input_tokens=10,output_tokens=2,total_tokens=12,finished_at=now)
        ModelCall.objects.create(course=self.course,skill_id=skill,provider='openai',model='test',status='failed',usage_state='partial',total_tokens=100,finished_at=now)
        evaluate(now);evaluate(now)
        self.assertEqual(SkillMetricSample.objects.count(),3)
        self.assertEqual(SkillAlertEvent.objects.filter(firing=True).count(),2)
        result=dashboard(self.course.pk,1);row=next(r for r in result['skills'] if r['kind']=='guidance')
        self.assertEqual(row['total_tokens'],60);self.assertEqual(row['partial_tokens'],100)
        self.assertAlmostEqual(row['p95_ms'],48000);self.assertIsNone(row['failure_rate'])
        self.assertAlmostEqual(row['usage_coverage'],5/6)
        CourseworkTask.objects.filter(pk=pk).update(status='succeeded',finished_at=now)
        ModelCall.objects.update(duration_ms=10)
        evaluate(now);evaluate(now)
        self.assertEqual(SkillAlertEvent.objects.filter(firing=False).count(),2)
        self.assertFalse(dashboard(self.course.pk,1)['monitor_stale'])
        self.assertEqual(len(dashboard(self.course.pk,24)['queue_curve']),3)

    @override_settings(SKILL_ALERT_FOR_SECONDS=0, SKILL_ALERT_RECOVERY_SECONDS=0)
    def test_monitor_failure_minimum_and_interrupted_recovery(self):
        now=timezone.now();skill=service.SKILLS['guidance']
        for i in range(4):
            row=service.enqueue_guidance(self.course.pk,self.student,'hint',str(i));service.finish(row,'failed')
        evaluate(now);self.assertFalse(SkillAlertEvent.objects.exists())
        row=service.enqueue_guidance(self.course.pk,self.student,'hint','last');service.finish(row,'failed')
        stale=ModelCall.objects.create(course=self.course,skill_id=skill,provider='openai',model='test')
        ModelCall.objects.filter(pk=stale.pk).update(started_at=now-timedelta(minutes=11))
        evaluate(now);self.assertEqual(SkillAlertEvent.objects.filter(firing=True).count(),1)
        stale.refresh_from_db();self.assertEqual(stale.status,'interrupted');self.assertIsNone(stale.total_tokens)
