from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import (User,Course,Membership,KnowledgePoint,Quiz,QuizAttempt,DiagnosticReport,DiagnosticVersion,DiagnosticSettings)
from .diagnostic_service import process_report,validate_claims,basis_for_report,render_exports,content_for


class DiagnosticTests(TestCase):
    def setUp(self):
        self.teacher=User.objects.create_user('diag-t@example.test','test-password')
        self.student=User.objects.create_user('diag-s@example.test','test-password')
        self.peer=User.objects.create_user('diag-p@example.test','test-password')
        self.course=Course.objects.create(name='Diagnostic',created_by=self.teacher)
        for u,r in [(self.teacher,'teacher'),(self.student,'student'),(self.peer,'student')]:Membership.objects.create(course=self.course,user=u,role=r)
        self.tc=self.client_for(self.teacher);self.sc=self.client_for(self.student);self.pc=self.client_for(self.peer)
        self.point=KnowledgePoint.objects.create(course=self.course,name='积分')
        self.base=f'/api/courses/{self.course.id}/diagnostic-reports/'
        now=timezone.now()
        self.quiz=Quiz.objects.create(course=self.course,title='测验',opens_at=now-timedelta(days=5),closes_at=now+timedelta(days=5),answers_at=now+timedelta(days=5),grades_published=True)
        self.attempt=QuizAttempt.objects.create(quiz=self.quiz,student=self.student,number=1,status='submitted',grading_status='finalized',submitted_at=now-timedelta(days=1),deadline=now,snapshot_hash='fixture',grade_revision=2,
            snapshot=[{'id':1,'revision':1,'kind':'short','body':'SECRET QUESTION','answer':{'text':'SECRET KEY'},'score':'10','points':[{'id':self.point.id,'name':self.point.name}]}],scores={'1':'6'},answers={'1':{'text':'ANSWER SECRET','image_ids':[123]}})

    def client_for(self,user):
        c=APIClient();c.force_authenticate(user);return c

    def create(self):
        r=self.tc.post(self.base,{'student_id':self.student.id},format='json');self.assertEqual(r.status_code,201,r.data)
        return DiagnosticReport.objects.get(pk=r.data['id'])

    def claims(self):return [{'point_id':self.point.id,'finding':'得分6/10，需巩固概念','recommendation':'回看课程定义并比较例题','refs':[f'a{self.attempt.id}:q1:g2']}]

    def ready(self):
        p=self.create()
        async def generated(basis):return self.claims(),'test-model'
        with patch('core.diagnostic_service.generate',side_effect=generated):self.assertTrue(process_report(p.id))
        p.refresh_from_db();self.assertEqual(p.status,'draft',p.error)
        return p

    def act(self,p,action,**extra):
        return self.tc.post(f'/api/diagnostic-reports/{p.id}/action/',{'action':action,'expected_revision':p.revision,'reason':'已逐条核查本人评分和引用','checked_point_ids':[self.point.id],**extra},format='json')

    def test_get_no_writes_queue_no_model_and_permissions(self):
        self.assertEqual(self.tc.get(f'/api/courses/{self.course.id}/diagnostic-settings/').status_code,200)
        self.assertFalse(DiagnosticSettings.objects.exists())
        with patch('core.diagnostic_service.generate') as model:p=self.create();model.assert_not_called()
        self.assertFalse(DiagnosticVersion.objects.exists())
        self.assertEqual(self.tc.post(self.base,{'student_id':self.student.id},format='json').status_code,409)
        self.assertEqual(self.sc.post(self.base,{'student_id':self.student.id},format='json').status_code,403)
        self.assertEqual(self.sc.get(f'/api/diagnostic-reports/{p.id}/').status_code,403)
        self.assertEqual(self.sc.get(self.base).data['items'],[])
        for body in [{'student_id':True},{'student_id':99999},{'student_id':self.student.id,'end':'bad'},{'student_id':self.student.id,'sql':'select'}]:
            self.assertEqual(self.tc.post(self.base,body,format='json').status_code,400)

    def test_teacher_review_publish_export_same_version_withdraw(self):
        p=self.ready();v=p.versions.get()
        self.assertEqual(self.act(p,'publish').status_code,409)
        self.assertEqual(self.act(p,'review',checked_point_ids=[]).status_code,400)
        self.assertEqual(self.act(p,'review').status_code,200)
        p.refresh_from_db();self.assertEqual(self.act(p,'publish').status_code,200)
        self.assertEqual(self.sc.get(self.base).data['items'][0]['version']['content_hash'],v.content_hash)
        self.assertEqual(self.pc.get(f'/api/diagnostic-reports/{p.id}/').status_code,403)
        for kind in ['html','pdf']:
            r=self.sc.get(f'/api/diagnostic-versions/{v.id}/{kind}/');self.assertEqual(r.status_code,200)
            self.assertEqual(r['X-Report-Content-Hash'],v.content_hash);self.assertEqual(r['Cache-Control'],'no-store')
        p.refresh_from_db();self.assertEqual(self.act(p,'withdraw').status_code,200)
        self.assertEqual(self.sc.get(f'/api/diagnostic-versions/{v.id}/pdf/').status_code,403)

    def test_no_evidence_never_calls_model_and_no_unsupported_claim(self):
        self.quiz.grades_published=False;self.quiz.save();p=self.create()
        with patch('core.diagnostic_service.model_stream') as model:process_report(p.id);model.assert_not_called()
        p.refresh_from_db();self.assertEqual(p.status,'draft')
        self.assertEqual(p.versions.get().content['claims'],[])
        with self.assertRaises(ValueError):validate_claims({'claims':self.claims()},p.basis)

    def test_snapshot_never_leaks_answer_keys_or_unreleased_answers(self):
        p=self.create();encoded=str(p.basis)
        self.assertNotIn('SECRET KEY',encoded);self.assertNotIn('SECRET QUESTION',encoded);self.assertNotIn('ANSWER SECRET',encoded)
        self.assertFalse(p.basis['answers'][0]['answers_released'])
        self.quiz.answers_at=timezone.now()-timedelta(days=1);self.quiz.save()
        b=basis_for_report(self.course.id,self.student.id,timezone.now()-timedelta(days=90),timezone.now())
        self.assertEqual(b['answers'][0]['answer'],{'text':'ANSWER SECRET'})

    def test_claim_schema_refs_and_point_must_match(self):
        p=self.create()
        for edit in [{'refs':['a999:q1:g2']},{'point_id':999},{'finding':''},{'refs':[]},{'point_id':True}]:
            with self.assertRaises(ValueError):validate_claims({'claims':[{**self.claims()[0],**edit}]},p.basis)
        with self.assertRaises(ValueError):validate_claims({'claims':self.claims()*2},p.basis)

    def test_stale_grades_hide_report_and_block_publish(self):
        p=self.ready();self.act(p,'review');p.refresh_from_db();self.act(p,'publish');p.refresh_from_db()
        self.quiz.grades_published=False;self.quiz.save()
        self.assertIsNone(self.tc.get(f'/api/diagnostic-reports/{p.id}/').data['version'])
        self.assertEqual(self.sc.get(f'/api/diagnostic-reports/{p.id}/').status_code,403)
        self.assertEqual(self.tc.get(f'/api/diagnostic-versions/{p.versions.get().id}/pdf/').status_code,409)

    def test_late_cancel_disable_and_revoke(self):
        p=self.create()
        async def cancelled(basis):
            from asgiref.sync import sync_to_async
            await sync_to_async(DiagnosticReport.objects.filter(pk=p.id).update)(status='cancelled')
            return self.claims(),'late'
        with patch('core.diagnostic_service.generate',side_effect=cancelled):self.assertFalse(process_report(p.id))
        self.assertFalse(DiagnosticVersion.objects.exists());self.assertFalse(process_report(p.id))
        p=self.create();Membership.objects.filter(course=self.course,user=self.teacher).delete()
        with patch('core.diagnostic_service.generate') as model:process_report(p.id);model.assert_not_called()
        p.refresh_from_db();self.assertEqual(p.status,'failed')

    def test_disabled_skill_no_queue(self):
        DiagnosticSettings.objects.create(course=self.course,enabled=False)
        self.assertEqual(self.tc.post(self.base,{'student_id':self.student.id},format='json').status_code,409)
        self.assertFalse(DiagnosticReport.objects.exists())

    def test_late_config_change_stale_source_and_model_failure_do_not_publish(self):
        from asgiref.sync import sync_to_async
        p=self.create()
        async def disabled(basis):
            await sync_to_async(DiagnosticSettings.objects.create)(course=self.course,enabled=False,revision=1)
            return self.claims(),'late'
        with patch('core.diagnostic_service.generate',side_effect=disabled):process_report(p.id)
        p.refresh_from_db();self.assertEqual(p.status,'failed');self.assertFalse(p.versions.exists())
        DiagnosticSettings.objects.all().delete();p=self.create()
        async def changed(basis):
            await sync_to_async(Quiz.objects.filter(pk=self.quiz.id).update)(grades_published=False)
            return self.claims(),'late'
        with patch('core.diagnostic_service.generate',side_effect=changed):process_report(p.id)
        p.refresh_from_db();self.assertEqual(p.status,'failed');self.assertFalse(p.versions.exists())
        self.quiz.grades_published=True;self.quiz.save();p=self.create()
        with patch('core.diagnostic_service.generate',side_effect=RuntimeError('private upstream token')):process_report(p.id)
        p.refresh_from_db();self.assertEqual(p.status,'failed');self.assertNotIn('private upstream token',p.error)

    def test_other_teacher_cannot_operate_and_stale_revisions_do_not_overwrite(self):
        other=User.objects.create_user('diag-other@example.test','test-password')
        Membership.objects.create(course=self.course,user=other,role='teacher');c=self.client_for(other)
        p=self.ready()
        self.assertEqual(c.get(f'/api/diagnostic-reports/{p.id}/').status_code,403)
        self.assertEqual(c.post(f'/api/diagnostic-reports/{p.id}/action/',{'action':'cancel','expected_revision':p.revision},format='json').status_code,403)
        self.assertEqual(self.act(p,'review').status_code,200)
        self.assertEqual(self.act(p,'publish').status_code,409)
        p.refresh_from_db();self.assertEqual(p.status,'draft');self.assertIsNone(p.published_version)

    def test_revision_keeps_html_pdf_immutable_and_requires_rereview(self):
        p=self.ready();v=p.versions.get();old=bytes(v.pdf);self.act(p,'review');p.refresh_from_db()
        claims=self.claims();claims[0]['finding']='<script>alert(1)</script> 教师核对得分'
        r=self.tc.post(f'/api/diagnostic-reports/{p.id}/revise/',{'claims':claims,'reason':'更正措辞','expected_revision':p.revision},format='json')
        self.assertEqual(r.status_code,200,r.data);p.refresh_from_db();v.refresh_from_db()
        self.assertEqual(bytes(v.pdf),old);self.assertEqual(p.current_version,2);self.assertEqual(p.phase,'awaiting_review')
        history=self.tc.get(f'/api/diagnostic-reports/{p.id}/versions/')
        self.assertEqual([v['number'] for v in history.data['items']],[2,1])
        self.assertEqual(self.sc.get(f'/api/diagnostic-reports/{p.id}/versions/').status_code,403)
        self.assertEqual(self.tc.get(f'/api/diagnostic-versions/{v.id}/pdf/').status_code,200)
        self.assertNotIn('<script>',p.versions.get(number=2).html)
        self.assertEqual(self.act(p,'publish').status_code,409)

    def test_chinese_pdf_paginates_long_text_and_shared_projection(self):
        import pymupdf
        p=self.create();claims=self.claims();claims[0]['finding']='中文分页检查。'*170;claims[0]['recommendation']='多页建议验证。'*170
        content=content_for(p,claims,1);html,pdf=render_exports(content)
        with pymupdf.open(stream=pdf,filetype='pdf') as doc:
            self.assertGreater(len(doc),1)
            text=''.join(page.get_text() for page in doc)
            self.assertIn('学习诊断报告',text);self.assertIn('评分 v2',text);self.assertIn('复习建议',text)
        self.assertIn('中文分页检查',html)
