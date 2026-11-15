import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from . import test_homework
from .models import (CourseworkTask, CourseworkSettings, SubmissionVersion, SubmissionGradeRevision,
                     Membership, AuditEvent)
from . import coursework_service as service


class CourseworkTests(TestCase):
    setUp = test_homework.HomeworkTests.setUp
    submit = test_homework.HomeworkTests.submit
    upload = test_homework.HomeworkTests.upload
    grade = test_homework.HomeworkTests.grade
    publication = test_homework.HomeworkTests.publication
    detail = test_homework.HomeworkTests.detail

    def seed(self):
        self.vid = self.submit(text_content='integral 2x from 0 to 1 = 2').data['id']
        self.task_url = f'/api/submission-versions/{self.vid}/ai-tasks/'
        self.rubric = [{'title': 'integration', 'maximum': '100', 'reference': 'x^2 from 0 to 1 = 1'}]

    def enqueue(self, key='one'):
        return self.tc.post(self.task_url, {'kind': 'grading', 'rubric': self.rubric, 'request_key': key}, format='json')

    def response(self, score='60.00'):
        return {'items': [{'id': 'c1', 'score': score, 'feedback': 'Antiderivative correct; boundary evaluation incorrect.'}]}

    def process(self, pk, score='60.00'):
        async def stream(*args, **kwargs):
            yield json.dumps(self.response(score)), 'test-model'
        with patch.object(service, 'model_stream', stream): service.process(pk)
        return CourseworkTask.objects.get(pk=pk)

    def reviewed_grade(self, pk, publish=True):
        return self.grade(self.vid, score='70', published=publish, ai_task_id=pk,
                          reviewed_items=[{'id': 'c1', 'score': '70', 'feedback': 'Teacher reviewed: boundary needs correction'}])

    def test_readonly_configuration_and_enqueue_idempotency(self):
        self.seed()
        self.assertEqual(self.tc.get(f'/api/courses/{self.course.pk}/coursework-settings/').status_code, 200)
        self.assertEqual(CourseworkSettings.objects.count(), 0)
        with patch.object(service, 'model_stream') as model:
            first = self.enqueue(); self.assertEqual(first.status_code, 202)
            self.assertEqual(self.enqueue().data['id'], first.data['id'])
            self.rubric[0]['reference'] = 'changed'
            self.assertEqual(self.enqueue().status_code, 409)
            self.assertEqual(self.tc.get(self.task_url).status_code, 200); model.assert_not_called()
        self.assertEqual(CourseworkTask.objects.count(), 1)
        self.assertIsNone(SubmissionVersion.objects.get(pk=self.vid).score)

    def test_roles_hidden_drafts_and_malformed_inputs(self):
        self.seed()
        self.assertEqual(self.sc.post(self.task_url, {'kind':'grading','request_key':'bad','rubric':self.rubric}, format='json').status_code, 403)
        pk = self.enqueue().data['id']; self.process(pk)
        self.assertEqual(self.sc.get(self.task_url).data, [])
        self.assertEqual(self.pc.get(self.task_url).status_code, 404)
        self.assertEqual(self.pc.get(f'/api/coursework-tasks/{pk}/').status_code, 404)
        self.assertEqual(self.sc.get(f'/api/coursework-tasks/{pk}/').status_code, 404)
        self.assertNotIn('Antiderivative', str(self.detail()))
        self.assertEqual(self.tc.post(self.task_url, {'kind':[], 'request_key':'bad'}, format='json').status_code, 409)
        self.assertEqual(self.sc.post(f'/api/courses/{self.course.pk}/coursework-settings/', {}, format='json').status_code, 403)

    def test_draft_never_grades_and_explicit_review_publication_drives_wrongs(self):
        self.seed(); pk=self.enqueue().data['id']; row=self.process(pk)
        self.assertEqual(row.status, 'draft'); self.assertEqual(row.result['score'], '60.00')
        self.assertEqual(SubmissionGradeRevision.objects.count(), 0)
        self.assertEqual(self.reviewed_grade(pk,False).status_code, 200)
        self.assertIsNone(self.detail()['my_versions'][0]['grade'])
        self.assertEqual(self.publication(self.vid,True,1).status_code, 200)
        grade=self.detail()['my_versions'][0]['grade']; self.assertEqual(grade['score'],'70.00')
        self.assertEqual(grade['reviewed_items'][0]['score'],'70.00')
        self.assertEqual(grade['ai_task_id'],pk)
        self.assertEqual(SubmissionGradeRevision.objects.get(revision=2).ai_task_id,pk)
        history=self.tc.get(f'/api/coursework-tasks/{pk}/').data
        self.assertFalse(history['current']);self.assertEqual(history['result']['score'],'60.00')
        self.assertTrue(AuditEvent.objects.filter(skill_id='homework-grading@1.0.0',action='coursework.execute').exists())

    def test_sum_shape_and_score_validation_before_grade_write(self):
        self.seed(); pk=self.enqueue().data['id']; self.process(pk)
        bad=self.grade(self.vid,score='80',ai_task_id=pk,reviewed_items=[{'id':'c1','score':'70','feedback':'review'}])
        self.assertEqual(bad.status_code,409); self.assertIsNone(SubmissionVersion.objects.get(pk=self.vid).score)
        for bad_score in ['NaN', 'Infinity', '100.01', '-1', '1.001', True]:
            with self.assertRaises(ValueError): service.validate_output(self.response(bad_score),CourseworkTask.objects.get(pk=pk).basis,'grading')
        output=self.response();output['items'][0]['id']='invented'
        with self.assertRaises(ValueError):service.validate_output(output,CourseworkTask.objects.get(pk=pk).basis,'grading')

    def test_new_submission_invalidates_draft_and_late_result(self):
        self.seed(); pk=self.enqueue().data['id']
        # ORM must stay in the sync worker, so simulate the change during extraction.
        def extract(task): self.submit(text_content='new answer');return []
        with patch.object(service,'extract_answers',extract),patch.object(service,'generate') as model:
            service.process(pk);model.assert_not_called()
        self.assertEqual(CourseworkTask.objects.get(pk=pk).status,'failed')
        self.assertEqual(SubmissionGradeRevision.objects.count(),0)

    def test_cancellation_retry_and_late_result_do_not_overwrite(self):
        self.seed();pk=self.enqueue().data['id'];row=CourseworkTask.objects.get(pk=pk)
        def extract(task):
            current=CourseworkTask.objects.get(pk=pk)
            response=self.tc.post(f'/api/coursework-tasks/{pk}/',{'action':'cancel','expected_revision':current.revision},format='json')
            self.assertEqual(response.status_code,200);return []
        with patch.object(service,'extract_answers',extract):service.process(pk)
        row.refresh_from_db();self.assertEqual(row.status,'cancelled');self.assertEqual(row.result,{})
        retried=self.tc.post(f'/api/coursework-tasks/{pk}/',{'action':'retry','expected_revision':row.revision,'request_key':'retry'},format='json')
        self.assertEqual(retried.status_code,202);self.assertEqual(retried.data['retry_of_id'],pk)
        self.process(retried.data['id']);row.refresh_from_db();self.assertEqual(row.status,'cancelled')

    def test_revocation_and_skill_changes_block_queued_and_completed_drafts(self):
        self.seed();pk=self.enqueue().data['id'];self.process(pk)
        config_url=f'/api/courses/{self.course.pk}/coursework-settings/'
        self.assertEqual(self.tc.post(config_url,{'grading_enabled':False,'explanation_enabled':True,'expected_revision':0},format='json').status_code,200)
        self.assertEqual(self.reviewed_grade(pk).status_code,409)
        self.assertEqual(self.enqueue('disabled').status_code,409)
        self.tc.post(config_url,{'grading_enabled':True,'explanation_enabled':True,'expected_revision':1},format='json')
        next_pk=self.enqueue('next').data['id']
        Membership.objects.filter(course=self.course,user=self.teacher).delete()
        with patch.object(service,'generate') as model:service.process(next_pk);model.assert_not_called()
        self.assertEqual(CourseworkTask.objects.get(pk=next_pk).status,'failed')

    def test_no_automatic_partial_grading_for_images_and_safe_errors(self):
        self.seed()
        v=self.submit(files=[self.upload('answer.png',b'fake-image')],text_content='partial text')
        self.assertEqual(v.status_code,201);self.vid=v.data['id'];self.task_url=f'/api/submission-versions/{self.vid}/ai-tasks/'
        pk=self.enqueue().data['id']
        with patch.object(service,'generate') as model:service.process(pk);model.assert_not_called()
        self.assertIn('人工批改',CourseworkTask.objects.get(pk=pk).error)
        self.assertEqual(SubmissionGradeRevision.objects.count(),0)

    def test_external_errors_and_expired_lease(self):
        self.seed();pk=self.enqueue().data['id']
        with patch.object(service,'extract_answers',side_effect=RuntimeError('https://secret.example?token=private')):service.process(pk)
        row=CourseworkTask.objects.get(pk=pk);self.assertEqual(row.status,'failed');self.assertNotIn('private',row.error)
        pk2=self.enqueue('second').data['id'];CourseworkTask.objects.filter(pk=pk2).update(status='running',lease_until=timezone.now()-timedelta(seconds=1))
        service.scan();self.assertEqual(CourseworkTask.objects.get(pk=pk2).status,'failed')

    def test_wrong_explanation_only_current_published_own_review_and_revocation(self):
        self.seed();pk=self.enqueue().data['id'];self.process(pk);self.assertEqual(self.reviewed_grade(pk).status_code,200)
        data={'kind':'explanation','item_id':'c1','request_key':'explain'}
        self.assertEqual(self.pc.post(self.task_url,data,format='json').status_code,404)
        response=self.sc.post(self.task_url,data,format='json');self.assertEqual(response.status_code,202)
        eid=response.data['id']
        async def stream(*args,**kwargs):yield 'Use $x^2$ and evaluate both endpoints.','test-model'
        with patch.object(service,'model_stream',stream):service.process(eid)
        task_url=f'/api/coursework-tasks/{eid}/'
        self.assertIn('explanation',self.sc.get(task_url).data['result'])
        self.assertEqual(self.publication(self.vid,False,1).status_code,200)
        self.assertEqual(self.sc.get(task_url).data['result'],{})
        self.assertEqual(self.sc.post(self.task_url,{**data,'request_key':'withdrawn'},format='json').status_code,409)
        self.assertEqual(SubmissionVersion.objects.get(pk=self.vid).score,Decimal('70'))

    def test_manual_regrading_clears_wrong_items_but_history_remains(self):
        self.seed();pk=self.enqueue().data['id'];self.process(pk);self.reviewed_grade(pk)
        self.assertEqual(self.grade(self.vid,score='100',published=True,expected_revision=1,reason='manual correction').status_code,200)
        self.assertEqual(self.detail()['my_versions'][0]['grade']['reviewed_items'],[])
        self.assertEqual(len(SubmissionGradeRevision.objects.get(revision=1).reviewed_items),1)

    def test_stale_revision_and_rubric_limits_do_not_enqueue(self):
        self.seed();self.rubric[0]['maximum']='99';self.assertEqual(self.enqueue().status_code,409)
        self.assertEqual(CourseworkTask.objects.count(),0)
        self.rubric[0]['maximum']='100';pk=self.enqueue().data['id']
        self.assertEqual(self.tc.post(f'/api/coursework-tasks/{pk}/',{'action':'cancel','expected_revision':999},format='json').status_code,409)
        self.assertEqual(CourseworkTask.objects.get(pk=pk).status,'queued')

    def test_personal_wrong_feed_uses_latest_public_revision_and_hides_peers(self):
        self.seed();url=f'/api/courses/{self.course.pk}/wrong-answers/'
        self.assertEqual(self.tc.get(url).status_code,403)
        self.assertEqual(self.grade(self.vid,score='70',published=True).status_code,200)
        self.assertEqual(self.sc.get(url).data['results'],[])
        pk=self.enqueue().data['id'];self.process(pk)
        grade=self.grade(self.vid,score='70',published=True,expected_revision=1,ai_task_id=pk,reviewed_items=[{'id':'c1','score':'70','feedback':'reviewed'}])
        self.assertEqual(grade.status_code,200)
        self.assertEqual(len(self.sc.get(url).data['results']),1)
        self.assertEqual(self.pc.get(url).data['results'],[])
        self.assertEqual(self.publication(self.vid,False,2).status_code,200)
        self.assertEqual(self.sc.get(url).data['results'],[])
        self.publication(self.vid,True,3);self.submit(text_content='new')
        self.assertEqual(self.sc.get(url).data['results'],[])

    def test_real_text_attachment_is_passed_with_source_kind_and_no_paths(self):
        self.seed();v=self.submit(files=[self.upload('work.txt',b'F(x)=x^2; result 2')])
        self.vid=v.data['id'];self.task_url=f'/api/submission-versions/{self.vid}/ai-tasks/'
        pk=self.enqueue().data['id'];seen=[]
        async def stream(messages,*args,**kwargs):
            payload=json.loads(messages[1]['content']);seen.append(payload)
            self.assertEqual(payload['attachments'][0]['source_kind'],'student_answer')
            self.assertIn('F(x)',payload['attachments'][0]['text'])
            self.assertNotIn('path',payload['attachments'][0])
            self.assertIn('当前只执行作业批改',messages[0]['content'])
            yield json.dumps(self.response()),'model'
        with patch.object(service,'model_stream',stream):service.process(pk)
        self.assertEqual(len(seen),1);self.assertEqual(CourseworkTask.objects.get(pk=pk).status,'draft')
        with patch.object(service,'generate') as model:
            self.assertFalse(service.process(pk));model.assert_not_called()

    def test_teacher_revoked_during_model_call_cannot_publish_draft(self):
        self.seed();pk=self.enqueue().data['id']
        def generation(*args,**kwargs):
            Membership.objects.filter(course=self.course,user=self.teacher).delete()
            return self.response(),'model'
        # Keep all DB mutation on the sync worker side, exactly at the completed call boundary.
        with patch.object(service,'async_to_sync',return_value=generation):service.process(pk)
        row=CourseworkTask.objects.get(pk=pk)
        self.assertEqual(row.status,'failed');self.assertEqual(row.result,{})
        self.assertEqual(SubmissionGradeRevision.objects.count(),0)
