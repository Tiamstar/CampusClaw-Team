import asyncio
from datetime import timedelta
from unittest.mock import patch
from asgiref.sync import async_to_sync
from django.db import OperationalError
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, TransactionTestCase
from django.urls import resolve
from django.utils import timezone
from .audit import RequestAuditMiddleware
from .models import RequestMetric, ModelCall, Course, User, Membership, CourseworkTask
from .skill_monitor import dashboard
from .coursework_service import SKILLS
from . import test_homework, coursework_service


class HttpTimingTests(TransactionTestCase):
    def setUp(self):
        self.user=User.objects.create_user('latency@example.test','test-password')
        self.course=Course.objects.create(name='Timing fixture',created_by=self.user)

    def wrap(self,response,path=None):
        request=RequestFactory().get(path or f'/api/courses/{self.course.pk}/materials/?private=not-a-label')
        request.resolver_match=resolve(request.path)
        return RequestAuditMiddleware(lambda _:response)(request)

    def test_normal_records_only_template_and_never_sensitive_query(self):
        response=self.wrap(HttpResponse('private answer'))
        row=RequestMetric.objects.get()
        self.assertEqual(row.course_id,self.course.pk)
        self.assertEqual(row.route,'api/courses/<int:course_id>/materials/')
        self.assertEqual(row.outcome,'completed');self.assertFalse(row.streaming)
        self.assertNotIn('private',str(list(RequestMetric.objects.values())))
        response.close();self.assertEqual(RequestMetric.objects.count(),1)

    def test_sync_stream_measures_until_end_and_close_not_headers(self):
        tick=[1.0]
        def source():
            tick[0]=4.0;yield b'first'
            tick[0]=6.0;yield b'last'
        with patch('core.audit.time.monotonic',side_effect=lambda:tick[0]):
            response=self.wrap(StreamingHttpResponse(source()))
            self.assertEqual(RequestMetric.objects.count(),0)
            self.assertEqual(b''.join(response.streaming_content),b'firstlast')
        row=RequestMetric.objects.get();self.assertEqual(row.duration_ms,5000);self.assertEqual(row.outcome,'completed')
        response.close();self.assertEqual(RequestMetric.objects.count(),1)
        never=self.wrap(StreamingHttpResponse(iter([b'not consumed'])))
        never.close();self.assertEqual(RequestMetric.objects.order_by('-pk').first().outcome,'closed')

    def test_sync_stream_error_not_reported_as_completed(self):
        def source():
            yield b'part'
            raise ValueError('private failure')
        response=self.wrap(StreamingHttpResponse(source()))
        with self.assertRaises(ValueError):list(response.streaming_content)
        response.close()
        self.assertEqual(RequestMetric.objects.get().outcome,'error')

    def test_async_stream_completed_cancelled_and_failed_close_once(self):
        closed=[]
        async def source(mode):
            try:
                yield b'part'
                if mode=='error':raise ValueError('private failure')
                if mode=='cancel':raise asyncio.CancelledError()
                yield b'end'
            finally:closed.append(mode)
        async def consume(response):
            return b''.join([part async for part in response.streaming_content])
        for mode in ['complete','error','cancel','early']:
            response=self.wrap(StreamingHttpResponse(source(mode)))
            if mode=='early':
                async def early():
                    stream=response._iterator
                    self.assertEqual(await anext(stream),b'part')
                    await stream.aclose()
                async_to_sync(early)()
            elif mode=='complete':self.assertEqual(async_to_sync(consume)(response),b'partend')
            else:
                with self.assertRaises(ValueError if mode=='error' else asyncio.CancelledError):async_to_sync(consume)(response)
            response.close()
        self.assertEqual(sorted(closed),['cancel','complete','early','error'])
        self.assertEqual(list(RequestMetric.objects.order_by('id').values_list('outcome',flat=True)),['completed','error','closed','closed'])

    def test_instrumentation_storage_failure_does_not_fail_response(self):
        with patch('core.request_metrics.RequestMetric.objects.create',side_effect=OperationalError('private database error')):
            response=self.wrap(HttpResponse('ok'))
        self.assertEqual(response.status_code,200)


class LatencyDashboardTests(TransactionTestCase):
    setUp=test_homework.HomeworkTests.setUp

    def test_course_scope_raw_percentiles_incomplete_and_bounded_window(self):
        now=timezone.now();skill=SKILLS['guidance']
        other=Course.objects.create(name='Other',created_by=self.teacher)
        def metric(n,course=None,**kwargs):
            return RequestMetric.objects.create(request_id=str(n),course=course or self.course,route='api/courses/<int:course_id>/materials/',
                method='GET',status_code=kwargs.get('status',200),streaming=kwargs.get('streaming',False),outcome=kwargs.get('outcome','completed'),
                duration_ms=n,started_at=now-timedelta(seconds=1),finished_at=now-timedelta(minutes=kwargs.get('minutes',0)))
        for n in [100,200,300,400,500]:metric(n)
        metric(9000,outcome='closed');metric(8000,outcome='error',status=500)
        metric(7000,minutes=90);metric(6000,course=other)
        for n in [10,20]:
            ModelCall.objects.create(course=self.course,skill_id=skill,provider='openai',model='fixture',status='succeeded',duration_ms=n,finished_at=now)
        ModelCall.objects.create(course=self.course,skill_id=skill,provider='mock',model='mock',duration_ms=99999,finished_at=now)
        result=dashboard(self.course.pk,1)
        route=result['http_latency']['routes'][0]
        self.assertEqual((route['requests'],route['completed'],route['closed'],route['transport_errors']),(7,5,1,1))
        self.assertAlmostEqual(route['p95_ms'],480);self.assertAlmostEqual(route['avg_ms'],300)
        self.assertEqual(result['http_latency']['curve'][0]['samples'],5)
        self.assertEqual(result['duration_curves']['model'][0]['samples'],2)
        self.assertAlmostEqual(result['duration_curves']['model'][0]['p95_ms'],19.5)
        self.assertEqual(dashboard(self.course.pk,24)['http_latency']['interval'],'hour')

    def test_task_total_queue_processing_and_unknown_legacy_start(self):
        now=timezone.now()
        for n in range(2):
            row=coursework_service.enqueue_guidance(self.course.pk,self.student,'private question',str(n))
            CourseworkTask.objects.filter(pk=row.pk).update(status='succeeded',created_at=now-timedelta(seconds=10),
                started_at=now-timedelta(seconds=6) if n==0 else None,finished_at=now)
        result=dashboard(self.course.pk,1)['duration_curves']['task'][0]
        self.assertEqual(result['samples'],2);self.assertAlmostEqual(result['avg_ms'],10000)
        self.assertEqual(result['processing_samples'],1)
        self.assertAlmostEqual(result['processing_p95_ms'],6000);self.assertAlmostEqual(result['queue_avg_ms'],4000)
        self.assertNotIn('private question',str(result))

    def test_teacher_permissions_and_ordinary_requests_gain_server_resource_scope(self):
        self.sc.get(f'/api/assignments/{self.a.pk}/')
        self.assertTrue(RequestMetric.objects.filter(course=self.course,route='api/assignments/<int:assignment_id>/').exists())
        url=f'/api/courses/{self.course.pk}/skill-monitor/'
        self.assertEqual(self.sc.get(url).status_code,403)
        self.assertEqual(self.tc.get(url+'?hours=168').status_code,200)
        Membership.objects.filter(user=self.teacher,course=self.course).delete()
        self.assertEqual(self.tc.get(url).status_code,404)
