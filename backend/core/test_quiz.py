from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import User,Course,Membership,Question,Quiz,QuizAttempt,KnowledgePoint,QuizGradeRevision
from .quiz_service import expire_attempts,quiz_statistics,finalize


class QuizTests(TestCase):
    def setUp(self):
        self.t=User.objects.create_user('qt@example.test','password-test')
        self.s=User.objects.create_user('qs@example.test','password-test')
        self.peer=User.objects.create_user('qp@example.test','password-test')
        self.c=Course.objects.create(name='Quiz',created_by=self.t)
        for u,role in [(self.t,'teacher'),(self.s,'student'),(self.peer,'student')]:Membership.objects.create(course=self.c,user=u,role=role)
        self.tc,self.sc,self.pc=[self.client_for(u) for u in [self.t,self.s,self.peer]]
        self.point=KnowledgePoint.objects.create(course=self.c,name='积分')
        self.q=[]
        for kind,options,values in [('single',['A','B'],['0']),('multiple',['A','B','C'],['0','2']),('boolean',[],['true']),('blank',[],['答案','answer']),('short',[],['评分参考'])]:
            response=self.tc.post(f'/api/courses/{self.c.id}/questions/',{'kind':kind,'body':kind+' question','options':options,'answer':{'values':values},'score':'10','point_ids':[self.point.id],'explanation':'解析'},format='json')
            self.assertEqual(response.status_code,201,response.data);self.q.append(response.data)
        now=timezone.now()
        self.quiz=Quiz.objects.create(course=self.c,title='Test',rules=[{'kind':q['kind'],'count':1} for q in self.q],
            opens_at=now-timedelta(minutes=1),closes_at=now+timedelta(hours=1),answers_at=now+timedelta(hours=1),max_attempts=2)
        self.assertEqual(self.tc.post(f'/api/quizzes/{self.quiz.id}/publish/',{},format='json').status_code,200)

    def client_for(self,user):
        c=APIClient();c.force_authenticate(user);return c

    def start(self):
        response=self.sc.post(f'/api/quizzes/{self.quiz.id}/attempts/',{},format='json');self.assertIn(response.status_code,[200,201]);return response.data

    def correct(self):
        return {str(q['id']):({'text':'我的推导','image_ids':[]} if q['kind']=='short' else q['answer']['values'] if q['kind']=='multiple' else '  答案  ' if q['kind']=='blank' else q['answer']['values'][0]) for q in self.q}

    def save(self,a,answers=None,rev=0,key='save1'):
        return self.sc.put(f"/api/quiz-attempts/{a['id']}/answers/",{'answers':answers if answers is not None else self.correct(),'expected_revision':rev,'key':key},format='json')

    def test_snapshot_survives_question_edit_and_no_answer_leak(self):
        a=self.start();self.assertTrue(all('answer' not in q and 'explanation' not in q for q in a['paper']))
        self.assertNotIn('scores',a)
        q=self.q[0];data={**q,'point_ids':[self.point.id],'expected_revision':q['revision'],'body':'changed'}
        self.assertEqual(self.tc.put(f"/api/questions/{q['id']}/",data,format='json').status_code,200)
        resumed=self.start();self.assertEqual(resumed['id'],a['id']);self.assertEqual(resumed['paper'],a['paper'])
        self.assertEqual(self.pc.get(f"/api/quiz-attempts/{a['id']}/").status_code,403)
        self.assertEqual(self.sc.get(f'/api/courses/{self.c.id}/questions/').status_code,403)

    def test_save_revision_idempotency_and_deadline(self):
        a=self.start();r=self.save(a);self.assertEqual(r.status_code,200)
        self.assertEqual(self.save(a).data['answer_revision'],1)
        self.assertEqual(self.save(a,{},key='save1').status_code,409)
        self.assertEqual(self.save(a,key='save2').status_code,409)
        QuizAttempt.objects.filter(pk=a['id']).update(deadline=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.save(a,rev=1,key='save3').status_code,409)
        self.assertEqual(expire_attempts(),1);self.assertEqual(expire_attempts(),0)
        response=self.sc.post(f"/api/quiz-attempts/{a['id']}/submit/",{},format='json')
        self.assertEqual(response.data['answers'],self.correct())
        self.assertEqual(QuizGradeRevision.objects.filter(attempt_id=a['id']).count(),1)

    def test_grading_review_publication_and_answer_release(self):
        a=self.start();self.assertEqual(self.save(a).status_code,200)
        url=f"/api/quiz-attempts/{a['id']}/"
        result=self.sc.post(url+'submit/',{},format='json');self.assertEqual(result.data['grading_status'],'awaiting_review')
        self.assertNotIn('scores',result.data)
        teacher=self.tc.get(url).data
        self.assertEqual(sum(Decimal(v) for v in teacher['scores'].values() if v is not None),40)
        scores={str(q['id']):'9' if q['kind']=='short' else '10' for q in self.q}
        data={'scores':scores,'feedback':{},'reason':'人工复核','expected_revision':1}
        self.assertEqual(self.sc.post(url+'review/',data,format='json').status_code,403)
        self.assertEqual(self.tc.post(url+'review/',data,format='json').status_code,200)
        self.assertEqual(self.tc.post(url+'review/',data,format='json').status_code,409)
        self.assertEqual(self.tc.post(f'/api/quizzes/{self.quiz.id}/publish/',{'action':'grades_publish'},format='json').status_code,200)
        student=self.sc.get(url).data;self.assertEqual(student['total'],'49.00');self.assertTrue(all('answer' not in q for q in student['paper']))
        Quiz.objects.filter(pk=self.quiz.id).update(answers_at=timezone.now()-timedelta(seconds=1))
        self.assertTrue(all('answer' in q for q in self.sc.get(url).data['paper']))
        data.update(expected_revision=2,reason='重评',scores={**scores,str(self.q[-1]['id']):'8'})
        self.assertEqual(self.tc.post(url+'review/',data,format='json').status_code,200)
        self.assertNotIn('scores',self.sc.get(url).data)

    def test_publication_blocked_by_pending_and_close_finalizes(self):
        a=self.start()
        url=f'/api/quizzes/{self.quiz.id}/publish/'
        self.assertEqual(self.tc.post(url,{'action':'grades_publish'},format='json').status_code,409)
        self.assertEqual(self.tc.post(url,{'action':'close'},format='json').status_code,200)
        self.assertEqual(self.save(a).status_code,409)
        self.assertEqual(expire_attempts(),1)

    def test_question_rules_and_foreign_points_rejected(self):
        other=Course.objects.create(name='other',created_by=self.t)
        foreign=KnowledgePoint.objects.create(course=other,name='secret')
        q=self.q[0]
        base={'kind':'single','body':'x','score':'1','options':['a','b'],'answer':{'values':['0']},'point_ids':[]}
        for change in [{'score':'-1'},{'point_ids':[foreign.id]},{'answer':{'values':['9']}},{'kind':'unknown'}]:
            self.assertEqual(self.tc.post(f'/api/courses/{self.c.id}/questions/',{**base,**change},format='json').status_code,400)
        self.quiz.status='draft';self.quiz.rules=[{'kind':'short','count':50}];self.quiz.save()
        self.assertEqual(self.tc.post(f'/api/quizzes/{self.quiz.id}/publish/',{},format='json').status_code,400)

    def test_five_type_scoring_rules(self):
        a=self.start();answers=self.correct()
        answers[str(self.q[1]['id'])]=['0'];answers[str(self.q[3]['id'])]='ANSWER'
        self.assertEqual(self.save(a,answers).status_code,200)
        self.sc.post(f"/api/quiz-attempts/{a['id']}/submit/",{},format='json')
        db=QuizAttempt.objects.get(pk=a['id'])
        self.assertEqual(db.scores[str(self.q[1]['id'])],'0.00');self.assertEqual(db.scores[str(self.q[3]['id'])],'0.00')
        self.assertIsNone(db.scores[str(self.q[4]['id'])])

    def test_handwriting_image_authorization(self):
        a=self.start();q=self.q[-1]
        stream=BytesIO();Image.new('RGB',(8,8),'white').save(stream,format='PNG')
        result=self.sc.post(f"/api/quiz-attempts/{a['id']}/images/{q['id']}/",{'file':SimpleUploadedFile('answer.png',stream.getvalue(),content_type='image/png')},format='multipart')
        self.assertEqual(result.status_code,201)
        self.assertEqual(self.pc.get(result.data['url']).status_code,403)
        self.assertEqual(self.tc.get(result.data['url']).status_code,200)
        answers=self.correct();answers[str(q['id'])]['image_ids']=[result.data['id']]
        self.assertEqual(self.save(a,answers).status_code,200)
        self.addCleanup(lambda:__import__('core.models',fromlist=['QuizAnswerImage']).QuizAnswerImage.objects.get(pk=result.data['id']).file.delete(save=False))

    def test_statistics_small_and_fixed_eight_student_fixture(self):
        # Same exact snapshot, eight distinct students; q1 split distinguishes groups.
        a=self.start();self.save(a);self.sc.post(f"/api/quiz-attempts/{a['id']}/submit/",{},format='json')
        original=QuizAttempt.objects.get(pk=a['id']);snapshot=original.snapshot
        original.delete()
        for index in range(8):
            student=User.objects.create_user(f'fixture-{index}@example.test','test-pass')
            values={str(q['id']):str(10 if index<4 else 0) for q in snapshot}
            QuizAttempt.objects.create(quiz=self.quiz,student=student,number=1,status='submitted',snapshot=snapshot,
                snapshot_hash='fixed',deadline=timezone.now(),submitted_at=timezone.now(),grading_status='finalized',scores=values)
        result=quiz_statistics(self.quiz);group=result['groups'][0]
        self.assertEqual(group['sample_size'],8);self.assertEqual(group['group_size'],2)
        self.assertTrue(all(Decimal(q['full_correct_rate'])==Decimal('.5') and Decimal(q['discrimination'])==1 for q in group['questions']))
        self.assertEqual(self.sc.get(f'/api/quizzes/{self.quiz.id}/statistics/').status_code,403)


class QuizConcurrencyTests(TransactionTestCase):
    def test_repeated_start_and_parallel_submit_only_one_grade(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections
        teacher=User.objects.create_user('concurrent-qt@example.test','test-pass')
        student=User.objects.create_user('concurrent-qs@example.test','test-pass')
        course=Course.objects.create(name='Parallel quiz',created_by=teacher)
        Membership.objects.create(course=course,user=student,role='student')
        Question.objects.create(course=course,kind='boolean',body='判断',options=[],answer={'values':['true']},score=10)
        now=timezone.now()
        quiz=Quiz.objects.create(course=course,title='Concurrent',status='published',rules=[{'kind':'boolean','count':1}],
            opens_at=now-timedelta(hours=1),closes_at=now+timedelta(hours=1),answers_at=now+timedelta(hours=1))
        def call(path):
            close_old_connections()
            try:
                client=APIClient();client.force_authenticate(User.objects.get(pk=student.pk))
                response=client.post(path,{},format='json')
                return response.status_code,response.data
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(call,[f'/api/quizzes/{quiz.id}/attempts/']*2))
        self.assertEqual({r[1]['id'] for r in results},{QuizAttempt.objects.get().id})
        aid=results[0][1]['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(call,[f'/api/quiz-attempts/{aid}/submit/']*2))
        self.assertEqual([r[0] for r in results],[200,200])
        self.assertEqual(QuizGradeRevision.objects.count(),1)
