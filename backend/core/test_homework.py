from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from .models import User, Course, Membership, Assignment, SubmissionVersion, StoredFile

class HomeworkTests(TestCase):
    def setUp(self):
        folder=TemporaryDirectory(); self.addCleanup(folder.cleanup)
        setting=override_settings(MEDIA_ROOT=folder.name); setting.enable(); self.addCleanup(setting.disable)
        self.teacher=User.objects.create_user('review@example.test','pass',display_name='Teacher')
        self.student=User.objects.create_user('author@example.test','pass',display_name='Student')
        self.peer=User.objects.create_user('peer@example.test','pass',display_name='Peer')
        self.course=Course.objects.create(name='Homework',created_by=self.teacher)
        for user,role in [(self.teacher,'teacher'),(self.student,'student'),(self.peer,'student')]:
            Membership.objects.create(course=self.course,user=user,role=role)
        self.a=Assignment.objects.create(course=self.course,title='Task',due_at=timezone.now()+timedelta(days=1))
        self.tc=APIClient(); self.tc.force_authenticate(self.teacher)
        self.sc=APIClient(); self.sc.force_authenticate(self.student)
        self.pc=APIClient(); self.pc.force_authenticate(self.peer)
        self.url=f'/api/assignments/{self.a.id}/'
    def upload(self,name='answer.txt',content=b'answer'):
        return SimpleUploadedFile(name,content)
    def submit(self,**data):
        return self.sc.post(self.url+'submit/',data,format='multipart')
    def detail(self):
        return self.sc.get(self.url).data
    def grade(self,version,**data):
        return self.tc.post(f'/api/submission-versions/{version}/grade/',{'score':'85.50','feedback':'private feedback','expected_revision':0,**data},format='json')
    def publication(self,version,value,revision):
        return self.tc.post(f'/api/submission-versions/{version}/publication/',{'published':value,'expected_revision':revision},format='json')
    def test_text_files_mixed_and_retry(self):
        self.assertEqual(self.detail()['submission_status'],'unsubmitted')
        first=self.submit(text_content='text answer',submission_key='retry-1')
        self.assertEqual(first.status_code,201); self.assertEqual(first.data['files'],[])
        self.assertEqual(self.submit(text_content='text answer',submission_key='retry-1').status_code,200)
        self.assertEqual(self.submit(text_content='changed',submission_key='retry-1').status_code,409)
        second=self.submit(files=[self.upload(),self.upload('second.txt')],text_content='mixed')
        self.assertEqual(second.status_code,201); self.assertEqual(len(second.data['files']),2)
        self.assertEqual(second.data['number'],2)
        for file in second.data['files']:
            for client,status in [(self.sc,200),(self.tc,200),(self.pc,403)]:
                response=client.get(file['preview_url']); self.assertEqual(response.status_code,status)
                response=client.get(file['download_url']); self.assertEqual(response.status_code,status)
                if getattr(response,'file_to_stream',None): response.file_to_stream.close()
        self.a.due_at=timezone.now()-timedelta(seconds=1); self.a.save()
        self.assertEqual(self.submit(text_content='text answer',submission_key='retry-1').status_code,200)
        self.assertEqual(self.submit(text_content='late').status_code,403)
    def test_grading_release_revoke_and_resubmit(self):
        roster=self.tc.get(self.url+'submissions/').data
        self.assertEqual(len(roster),2); self.assertTrue(all(x['status']=='unsubmitted' for x in roster))
        version=self.submit(text_content='answer').data['id']
        self.assertEqual(self.pc.post(f'/api/submission-versions/{version}/review/').status_code,403)
        self.assertEqual(self.tc.post(f'/api/submission-versions/{version}/review/').status_code,200)
        self.assertEqual(self.detail()['submission_status'],'pending_review')
        self.assertEqual(self.grade(version).status_code,200)
        detail=self.detail(); self.assertEqual(detail['submission_status'],'graded')
        self.assertIsNone(detail['my_versions'][0]['grade'])
        self.assertNotIn('private feedback',str(detail))
        self.assertNotIn('grade_history',detail['my_versions'][0])
        self.assertEqual(self.publication(version,True,1).status_code,200)
        self.assertEqual(self.detail()['my_versions'][0]['grade']['score'],'85.50')
        self.assertEqual(self.publication(version,False,2).status_code,200)
        self.assertIsNone(self.detail()['my_versions'][0]['grade'])
        self.assertEqual(self.grade(version,score='90',expected_revision=3).status_code,400)
        self.assertEqual(self.grade(version,score='90',expected_revision=3,reason='recheck').status_code,200)
        self.assertEqual(self.grade(version,expected_revision=3).status_code,409)
        self.submit(text_content='new answer')
        self.assertEqual(self.detail()['submission_status'],'submitted')
        self.assertEqual(self.publication(version,True,4).status_code,409)
        self.assertEqual(self.grade(version,expected_revision=4).status_code,409)
    def test_validation_and_atomic_file_rollback(self):
        self.assertEqual(self.submit().status_code,400)
        self.assertEqual(self.submit(files=[self.upload(str(i)+'.txt') for i in range(11)]).status_code,400)
        self.assertEqual(self.submit(files=[self.upload('bad.exe')]).status_code,400)
        self.assertEqual(self.submit(text_content='x'*50001).status_code,400)
        version=self.submit(text_content='answer').data['id']
        for score in ['NaN','Infinity','-1','100.01','1.001',True,None]:
            self.assertEqual(self.grade(version,score=score).status_code,400)
        before=StoredFile.objects.count()
        with patch('core.assignment_views.SubmissionVersion.objects.create',side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError): self.submit(files=[self.upload()])
        self.assertEqual(StoredFile.objects.count(),before)
        from django.conf import settings
        from pathlib import Path
        self.assertFalse(any(p.is_file() for p in Path(settings.MEDIA_ROOT).rglob('*')))
    def test_preview_formats_and_escaped_content(self):
        import pymupdf
        from docx import Document
        from PIL import Image
        pdf=pymupdf.open(); pdf.new_page(); pdf_bytes=pdf.tobytes(); pdf.close()
        doc=Document(); doc.add_paragraph('<script>alert(1)</script>'); doc.add_table(rows=1,cols=1).cell(0,0).text='table'
        word=BytesIO(); doc.save(word)
        picture=BytesIO(); Image.new('RGB',(2,2)).save(picture,format='PNG')
        for name,content,status in [('a.pdf',pdf_bytes,200),('a.docx',word.getvalue(),200),('a.png',picture.getvalue(),200),('a.txt',b'<script>alert(1)</script>',200),('a.zip',b'zip',415),('broken.pdf',b'bad',422),('broken.docx',b'bad',422)]:
            submitted=self.submit(files=[self.upload(name,content)])
            self.assertEqual(submitted.status_code,201)
            url=submitted.data['files'][0]['preview_url']
            response=self.sc.get(url); self.assertEqual(response.status_code,status,(name,str(getattr(response,'data',''))))
            if name in ('a.docx','a.txt'):
                self.assertNotIn(b'<script>',response.content); self.assertIn(b'&lt;script&gt;',response.content)
            if getattr(response,'file_to_stream',None): response.file_to_stream.close()
            self.assertEqual(self.pc.get(url).status_code,403)
