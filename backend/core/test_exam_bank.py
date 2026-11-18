import asyncio
import json
import tempfile
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch, AsyncMock
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient
from PIL import Image
from docx import Document
import fitz
from .models import User,Course,Membership,ExamSource,Question,QuestionGroup,QuestionAsset,Quiz,QuizAttempt,AgentThread,ExamPaperEntry,ExamPaperRevision
from .exam_service import extract_source,scan_sources,clean_draft
from .quiz_service import paper,objective_grade,attempt_data


class ExamBankTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.settings=override_settings(MEDIA_ROOT=self.temp.name);self.settings.enable();self.addCleanup(self.settings.disable)
        self.t=User.objects.create_user('owner@example.test','test-password')
        self.other=User.objects.create_user('other@example.test','test-password')
        self.s=User.objects.create_user('student@example.test','test-password')
        self.c=Course.objects.create(name='Exam bank',created_by=self.t)
        for user,role in [(self.t,'teacher'),(self.other,'teacher'),(self.s,'student')]:Membership.objects.create(course=self.c,user=user,role=role)
        self.tc,self.oc,self.sc=[self.client_for(u) for u in [self.t,self.other,self.s]]

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user);return client

    def upload(self,key='upload-key-00000001',raw=b'English passage. Question one?',name='exam.txt'):
        response=self.tc.post(f'/api/courses/{self.c.id}/exam-sources/',{'file':SimpleUploadedFile(name,raw),'request_key':key},format='multipart')
        self.assertIn(response.status_code,[200,201],response.data)
        return response.data

    def draft(self):
        return {'groups':[{'title':'Reading','material':'Shared passage with $x^2$', 'source_units':[1], 'questions':[
            {'kind':'single','body':'Choose an answer','options':['A','B'],'answer':{'values':[]},'explanation':'','source_units':[1]},
            {'kind':'short','body':'Explain the passage','options':[],'answer':{'values':[]},'explanation':'','source_units':[1]}]}]}

    def ready(self):
        result=self.upload();row=ExamSource.objects.get(pk=result['id']);row.status='ready'
        row.units=[{'id':1,'label':'source one','text':'Original','asset_ids':[]}];row.draft=self.draft();row.save()
        return row

    def commit(self,row):
        return self.tc.post(f'/api/exam-sources/{row.id}/',{'action':'commit','confirmed':True,'expected_revision':row.revision},format='json')

    def test_upload_idempotent_owner_private_and_get_readonly(self):
        row=self.upload();self.assertEqual(self.upload()['id'],row['id'])
        response=self.tc.post(f'/api/courses/{self.c.id}/exam-sources/',{'file':SimpleUploadedFile('exam.txt',b'new'),'request_key':'upload-key-00000001'},format='multipart')
        self.assertEqual(response.status_code,409)
        for client in [self.oc,self.sc]:
            self.assertEqual(client.get(f"/api/exam-sources/{row['id']}/").status_code,403)
            self.assertEqual(client.get(row['download_url']).status_code,403)
        count=ExamSource.objects.count()
        self.assertEqual(self.tc.get(f"/api/exam-sources/{row['id']}/").data['status'],'queued')
        self.assertEqual(ExamSource.objects.count(),count)
        self.assertEqual(self.oc.get(f'/api/courses/{self.c.id}/exam-sources/').data['items'],[])

    def test_committed_paper_edits_keep_ids_soft_remove_and_reject_stale_bank(self):
        row=self.ready();self.assertEqual(self.commit(row).status_code,200)
        url=f'/api/exam-sources/{row.id}/'
        loaded=self.tc.get(url).data
        ids=[x['question_id'] for x in loaded['mapping']]
        baseline=ExamPaperRevision.objects.count()
        self.tc.get(url)
        self.assertEqual(ExamPaperRevision.objects.count(),baseline)
        # A separate bank edit must invalidate even a removal of that question.
        Question.objects.filter(pk=ids[1]).update(revision=2)
        loaded['draft']['groups'][0]['questions'].pop()
        response=self.tc.put(url,{'draft':loaded['draft'],'bank_versions':loaded['bank_versions'],'group_versions':loaded['group_versions'],'expected_revision':loaded['revision']},format='json')
        self.assertEqual(response.status_code,409)
        self.assertEqual(ExamPaperEntry.objects.count(),2)
        loaded=self.tc.get(url).data
        group=loaded['draft']['groups'][0];group['questions'].pop();group['questions'][0]['body']='Corrected live question'
        response=self.tc.put(url,{'draft':loaded['draft'],'bank_versions':loaded['bank_versions'],'group_versions':loaded['group_versions'],'expected_revision':loaded['revision']},format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['mapping'][0]['question_id'],ids[0])
        self.assertEqual(Question.objects.get(pk=ids[0]).body,'Corrected live question')
        self.assertFalse(Question.objects.get(pk=ids[1]).active)
        self.assertEqual(ExamPaperEntry.objects.count(),1)
        self.assertEqual(ExamPaperRevision.objects.count(),baseline+1)

    def test_paper_edit_foreign_ids_and_whole_batch_validation(self):
        row=self.ready();self.commit(row);url=f'/api/exam-sources/{row.id}/'
        loaded=self.tc.get(url).data
        loaded['draft']['groups'][0]['questions'][0]['question_id']=99999
        result=self.tc.put(url,{'draft':loaded['draft'],'bank_versions':loaded['bank_versions'],'group_versions':loaded['group_versions'],'expected_revision':loaded['revision']},format='json')
        self.assertEqual(result.status_code,422)
        self.assertEqual(ExamPaperEntry.objects.count(),2)
        self.assertEqual(Question.objects.filter(active=True).count(),2)
        self.assertEqual(self.oc.put(url,{},format='json').status_code,403)

    def test_bank_crud_updates_paper_membership_and_revision(self):
        row=self.ready();self.commit(row);row.refresh_from_db();before=row.revision
        group=QuestionGroup.objects.get(source=row)
        response=self.tc.post(f'/api/courses/{self.c.id}/questions/',{'kind':'short','body':'A new follow-up',
            'answer':{'values':[]},'group_id':group.id,'point_ids':[]},format='json')
        self.assertEqual(response.status_code,201,response.data)
        qid=response.data['id'];row.refresh_from_db()
        self.assertEqual(row.revision,before+1)
        self.assertEqual(list(row.entries.values_list('question_id',flat=True))[-1],qid)
        self.assertEqual(Question.objects.get(pk=qid).source_id,row.id)
        response=self.tc.put(f'/api/questions/{qid}/',{'kind':'short','body':'Edited in bank','answer':{'values':[]},
            'point_ids':[],'active':False,'expected_revision':1},format='json')
        self.assertEqual(response.status_code,200,response.data)
        row.refresh_from_db();self.assertEqual(row.revision,before+2)
        loaded=self.tc.get(f'/api/exam-sources/{row.id}/').data
        self.assertEqual(loaded['draft']['groups'][0]['questions'][-1]['body'],'Edited in bank')
        saved=self.tc.put(f'/api/exam-sources/{row.id}/',{'draft':loaded['draft'],
            'bank_versions':loaded['bank_versions'],'group_versions':loaded['group_versions'],
            'expected_revision':loaded['revision']},format='json')
        self.assertEqual(saved.status_code,200,saved.data)
        self.assertFalse(Question.objects.get(pk=qid).active)

    def test_archive_restore_rename_preserve_original_file_and_bank(self):
        row=self.ready();self.commit(row);url=f'/api/exam-sources/{row.id}/'
        loaded=self.tc.get(url).data
        renamed=self.tc.post(url,{'action':'rename','name':'My editable paper','expected_revision':loaded['revision']},format='json')
        self.assertEqual(renamed.status_code,200)
        row.refresh_from_db();self.assertIn('English passage',extract_source(row)[0]['text'])
        archived=self.tc.post(url,{'action':'archive','expected_revision':renamed.data['revision']},format='json')
        self.assertEqual(archived.status_code,200)
        self.assertEqual(self.tc.get(f'/api/courses/{self.c.id}/exam-sources/').data['items'],[])
        self.assertEqual(len(self.tc.get(f'/api/courses/{self.c.id}/exam-sources/?archived=1').data['items']),1)
        self.assertEqual(self.tc.put(url,{'expected_revision':archived.data['revision']},format='json').status_code,409)
        restored=self.tc.post(url,{'action':'restore','expected_revision':archived.data['revision']},format='json')
        self.assertEqual(restored.status_code,200);self.assertEqual(Question.objects.filter(active=True).count(),2)

    def test_manual_crop_is_private_and_only_creates_selected_figure(self):
        from .exam_service import save_image
        row=self.ready();buf=BytesIO();Image.new('RGB',(200,100),'white').save(buf,'PNG')
        asset=save_image(row,buf.getvalue(),'page',is_page=True)
        url=f'/api/exam-sources/{row.id}/'
        payload={'action':'crop','expected_revision':row.revision,'asset_id':asset.id,'box':[250,100,750,900]}
        self.assertEqual(self.sc.post(url,payload,format='json').status_code,403)
        result=self.tc.post(url,payload,format='json');self.assertEqual(result.status_code,201,result.data)
        figure=QuestionAsset.objects.get(pk=result.data['id']);self.assertFalse(figure.is_page)
        with figure.file.open('rb') as f,Image.open(f) as image:self.assertEqual(image.size,(100,80))
        payload['box']=[1,1,1,1]
        self.assertEqual(self.tc.post(url,payload,format='json').status_code,400)

    def test_multiple_photos_are_one_ordered_idempotent_source(self):
        def photos():
            result=[]
            for color in ['red','blue']:
                out=BytesIO();Image.new('RGB',(100,150),color).save(out,'PNG')
                result.append(SimpleUploadedFile(color+'.png',out.getvalue(),content_type='image/png'))
            return result
        url=f'/api/courses/{self.c.id}/exam-sources/'
        result=self.tc.post(url,{'file':photos(),'request_key':'photo-key-00000001'},format='multipart')
        self.assertEqual(result.status_code,201,result.data)
        again=self.tc.post(url,{'file':photos(),'request_key':'photo-key-00000001'},format='multipart')
        self.assertEqual(again.data['id'],result.data['id'])
        row=ExamSource.objects.get(pk=result.data['id']);units=extract_source(row)
        self.assertEqual(len(units),2)
        first=QuestionAsset.objects.get(pk=units[0]['asset_ids'][0])
        with first.file.open('rb') as f,Image.open(f) as image:self.assertGreater(image.getpixel((5,5))[0],200)

    def test_optional_answers_no_bank_score_atomic_commit_and_revision(self):
        row=self.ready();row.draft['groups'][0]['questions'][1]['body']='';row.save()
        self.assertEqual(self.commit(row).status_code,422)
        self.assertEqual(Question.objects.count(),0);self.assertEqual(QuestionGroup.objects.count(),0)
        row.draft=self.draft();row.save()
        response=self.commit(row);self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(Question.objects.count(),2)
        self.assertTrue(all(q.score is None and q.answer=={'values':[]} for q in Question.objects.all()))
        self.assertEqual(self.commit(row).status_code,200);self.assertEqual(Question.objects.count(),2)
        q=Question.objects.first()
        self.assertEqual(self.oc.put(f'/api/questions/{q.id}/',{},format='json').status_code,403)
        self.assertEqual(self.sc.get(f'/api/courses/{self.c.id}/questions/').status_code,403)
        self.assertEqual(self.oc.get(f'/api/courses/{self.c.id}/questions/').data['items'],[])
        edit={'kind':q.kind,'body':'Changed','options':q.options,'expected_revision':0}
        self.assertEqual(self.tc.put(f'/api/questions/{q.id}/',edit,format='json').status_code,409)

    def test_fixed_groups_exam_scores_and_old_snapshot(self):
        row=self.ready();self.assertEqual(self.commit(row).status_code,200)
        ids=list(Question.objects.order_by('position').values_list('id',flat=True));now=timezone.now()
        payload={'title':'Reading exam','opens_at':(now-timedelta(minutes=1)).isoformat(),'closes_at':(now+timedelta(hours=1)).isoformat(),
                 'answers_at':(now+timedelta(hours=2)).isoformat(),'question_ids':ids}
        url=f'/api/courses/{self.c.id}/quizzes/'
        self.assertEqual(self.tc.post(url,payload,format='json').status_code,400)
        payload['question_scores']={str(ids[0]):'3',str(ids[1]):'7'}
        response=self.tc.post(url,payload,format='json');self.assertEqual(response.status_code,201,response.data)
        quiz_id=response.data['id']
        publish=f'/api/quizzes/{quiz_id}/publish/'
        self.assertEqual(self.tc.post(publish,{},format='json').status_code,200)
        started=self.sc.post(f'/api/quizzes/{quiz_id}/attempts/',{},format='json');self.assertEqual(started.status_code,201,started.data)
        snapshot=started.data['paper'];self.assertEqual([q['id'] for q in snapshot],ids)
        self.assertEqual([q['score'] for q in snapshot],['3.00','7.00'])
        self.assertNotIn('answer',snapshot[0]);self.assertEqual(snapshot[0]['group']['material'],'Shared passage with $x^2$')
        QuestionGroup.objects.update(material='edited material');Question.objects.update(body='edited question',active=False)
        resumed=self.sc.get(f"/api/quiz-attempts/{started.data['id']}/").data
        self.assertEqual(resumed['paper'],snapshot)
        attempt=QuizAttempt.objects.get(pk=started.data['id']);self.assertEqual(objective_grade(attempt),{str(i):None for i in ids})
        q=Quiz.objects.get(pk=quiz_id);q.question_ids=[ids[0]];Question.objects.update(active=True)
        with self.assertRaisesMessage(ValueError,'完整题组'):paper(q)

    def test_public_solution_and_page_asset_authorization(self):
        row=self.ready();image=Image.new('RGB',(40,30),'white');buf=BytesIO();image.save(buf,'PNG')
        uploaded=self.tc.post(f'/api/courses/{self.c.id}/question-assets/',{'file':SimpleUploadedFile('diagram.png',buf.getvalue())},format='multipart')
        self.assertEqual(uploaded.status_code,201,uploaded.data);aid=uploaded.data['id']
        solution=QuestionAsset.objects.create(course=self.c,owner=self.t,digest='a'*64)
        solution.file.save('solution.png',ContentFile(buf.getvalue()),save=True)
        whole=QuestionAsset.objects.create(course=self.c,owner=self.t,digest='b'*64,is_page=True)
        whole.file.save('page.png',ContentFile(buf.getvalue()),save=True)
        row.draft['groups'][0]['material']=f'{{{{asset:{aid}}}}}'
        row.draft['groups'][0]['questions'][0]['explanation']=f'{{{{asset:{solution.id}}}}}';row.save()
        self.assertEqual(self.commit(row).status_code,200)
        ids=list(Question.objects.values_list('id',flat=True));now=timezone.now()
        quiz=Quiz.objects.create(course=self.c,owner=self.t,title='pictures',question_ids=ids,question_scores={str(i):'1' for i in ids},opens_at=now,closes_at=now+timedelta(hours=1),answers_at=now+timedelta(hours=1))
        attempt=QuizAttempt.objects.create(quiz=quiz,student=self.s,number=1,snapshot=paper(quiz),snapshot_hash='x'*64,deadline=now+timedelta(hours=1))
        self.assertNotIn('solution_asset_ids',attempt_data(attempt)['paper'][0])
        self.assertEqual(self.sc.get(f'/api/question-assets/{aid}/').status_code,200)
        self.assertEqual(self.sc.get(f'/api/question-assets/{solution.id}/').status_code,403)
        self.assertEqual(self.oc.get(f'/api/question-assets/{aid}/').status_code,403)
        attempt.status='submitted';attempt.save();quiz.answers_at=now-timedelta(seconds=1);quiz.save()
        self.assertEqual(self.sc.get(f'/api/question-assets/{solution.id}/').status_code,200)
        self.assertEqual(self.sc.get(f'/api/question-assets/{whole.id}/').status_code,403)

    def test_source_parsers_text_scanned_pdf_docx_image_and_limits(self):
        row=self.ready()
        self.assertIn('English passage',extract_source(row)[0]['text'])
        buf=BytesIO();Image.new('RGB',(80,60),'white').save(buf,'PNG')
        row.name='scan.png';row.file.save('scan.png',ContentFile(buf.getvalue()),save=True)
        self.assertEqual(len(extract_source(row)[0]['asset_ids']),1)
        document=fitz.open();page=document.new_page();page.insert_image(fitz.Rect(0,0,80,60),stream=buf.getvalue());raw=document.tobytes();document.close()
        row.name='scan.pdf';row.file.save('scan.pdf',ContentFile(raw),save=True)
        units=extract_source(row);self.assertEqual(len(units),1);self.assertEqual(units[0]['text'],'')
        document=Document();document.add_paragraph('Reading passage');document.add_picture(BytesIO(buf.getvalue()));out=BytesIO();document.save(out)
        row.name='paper.docx';row.file.save('paper.docx',ContentFile(out.getvalue()),save=True)
        units=extract_source(row);self.assertIn('Reading passage',units[0]['text']);self.assertEqual(len(units[0]['asset_ids']),1)
        doc=fitz.open()
        for _ in range(13):doc.new_page()
        raw=doc.tobytes();doc.close();row.name='long.pdf';row.file.save('long.pdf',ContentFile(raw),save=True)
        with self.assertRaisesMessage(ValueError,'1–12'):extract_source(row)

    def test_worker_failure_manual_retry_and_expired_lease(self):
        row=self.ready();row.status='queued';row.save()
        with patch('core.exam_service.recognize',new=AsyncMock(return_value=(self.draft(),'test-model'))):
            self.assertEqual(scan_sources(),1)
        row.refresh_from_db();self.assertEqual(row.status,'ready');self.assertEqual(row.model,'test-model')
        row.status='running';row.lease_until=timezone.now()-timedelta(seconds=1);row.lease_token='old';row.save()
        self.assertEqual(scan_sources(),0);row.refresh_from_db();self.assertEqual(row.status,'failed')
        self.assertEqual(Question.objects.count(),0)
        response=self.tc.post(f'/api/exam-sources/{row.id}/',{'action':'manual','expected_revision':row.revision},format='json')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['status'],'ready')
        response=self.tc.post(f'/api/exam-sources/{row.id}/',{'action':'retry','expected_revision':row.revision},format='json')
        self.assertEqual(response.status_code,409)

    def test_bank_tool_checks_teacher_and_owner_each_execution(self):
        from asgiref.sync import async_to_sync
        from .agent_runtime import builtin_tool_registry,ToolContext
        row=self.ready();self.commit(row)
        thread=AgentThread.objects.create(owner=self.t,course=self.c,title='bank')
        registry=builtin_tool_registry();context=ToolContext(self.t,thread,frozenset({'questionbank.read'}),'test-bank')
        result=async_to_sync(registry.execute)('search_question_bank',{'query':'Choose'},context)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['source_id'],row.id)
        membership=Membership.objects.get(course=self.c,user=self.t);membership.role='student';membership.save()
        with self.assertRaises(PermissionError):async_to_sync(registry.execute)('search_question_bank',{},context)

    def test_bad_source_mapping_and_raw_page_rejected_at_commit(self):
        row=self.ready();draft=self.draft();draft['groups'][0]['source_units']=[999]
        with self.assertRaises(ValueError):clean_draft(draft,row.units)
        row.draft['groups'][0]['material']='![external](https://example.test/private.png)';row.save()
        self.assertEqual(self.commit(row).status_code,422);self.assertEqual(Question.objects.count(),0)

    def test_recognition_never_promotes_model_invented_answers_or_scores(self):
        from asgiref.sync import async_to_sync
        from .exam_service import recognize
        row=self.ready();draft=self.draft()
        draft['groups'][0]['questions'][0].update(answer={'values':['0']},score='100',explanation='Invented solution')
        async def stream(*args,**kwargs):
            yield json.dumps({**draft,'crops':[]}), 'test-model'
        with patch('core.exam_service.model_stream',stream):
            result,model=async_to_sync(recognize)(row,row.units)
        self.assertEqual(model,'test-model')
        self.assertEqual(result['groups'][0]['questions'][0]['answer'],{'values':[]})
        self.assertEqual(result['groups'][0]['questions'][0]['explanation'],'')
        self.assertNotIn('score',result['groups'][0]['questions'][0])

    def test_manual_group_reordering_and_missing_answers_are_valid(self):
        response=self.tc.post(f'/api/courses/{self.c.id}/question-groups/',{'title':'Shared','material':'Text'},format='json')
        self.assertEqual(response.status_code,201)
        group=response.data;ids=[]
        for body in ['First','Second']:
            response=self.tc.post(f'/api/courses/{self.c.id}/questions/',{'kind':'short','body':body,'group_id':group['id']},format='json')
            self.assertEqual(response.status_code,201,response.data);self.assertIsNone(response.data['score']);ids.append(response.data['id'])
        response=self.tc.put(f"/api/question-groups/{group['id']}/",{'title':'Shared','material':'Text','question_ids':list(reversed(ids)),'expected_revision':1},format='json')
        self.assertEqual(response.status_code,200,response.data);self.assertEqual(response.data['question_ids'],list(reversed(ids)))

    def test_bank_combined_filters_and_authorization(self):
        from .models import KnowledgePoint
        point=KnowledgePoint.objects.create(course=self.c,name='Filters')
        matching=Question.objects.create(course=self.c,owner=self.t,kind='short',body='matching',answer={'values':[]},active=False)
        matching.points.add(point)
        Question.objects.create(course=self.c,owner=self.t,kind='short',body='other',answer={'values':['reference']})
        Question.objects.create(course=self.c,owner=self.other,kind='short',body='private',answer={'values':[]},active=False).points.add(point)
        url=f'/api/courses/{self.c.id}/questions/'
        params={'kind':'short','point_id':point.pk,'answer_state':'missing','active':'false'}
        response=self.tc.get(url,params)
        self.assertEqual(response.status_code,200)
        self.assertEqual([q['id'] for q in response.data['items']],[matching.pk])
        self.assertEqual(self.sc.get(url,params).status_code,403)
        self.assertEqual([q['body'] for q in self.tc.get(url,{'answer_state':'present'}).data['items']],['other'])
        for params in ({'kind':'invented'},{'answer_state':'all'},{'active':'1'},{'point_id':'-1'},{'group_id':'abc'},{'point_id':'9'*5000}):
            self.assertEqual(self.tc.get(url,params).status_code,400,params)

    def test_bank_filtered_pagination_does_not_mix_results(self):
        for i in range(23):
            Question.objects.create(course=self.c,owner=self.t,kind='short',body=f'pending {i}',answer={'values':[]})
        Question.objects.create(course=self.c,owner=self.t,kind='short',body='answered',answer={'values':['yes']})
        url=f'/api/courses/{self.c.id}/questions/'
        first=self.tc.get(url,{'answer_state':'missing'}).data
        second=self.tc.get(url,{'answer_state':'missing','page':2}).data
        self.assertEqual(len(first['items']),20)
        self.assertEqual(len(second['items']),3)
        self.assertEqual(first['next_page'],2)
        self.assertIsNone(second['next_page'])
        self.assertFalse({q['id'] for q in first['items']} & {q['id'] for q in second['items']})
