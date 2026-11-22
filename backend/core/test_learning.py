from datetime import timedelta, timezone as utc_timezone
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import User, Course, Membership, KnowledgePoint, Quiz, QuizAttempt
from .learning_service import learning_data


class LearningTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('learning-t@example.test', 'test-password')
        self.student = User.objects.create_user('learning-s@example.test', 'test-password')
        self.peer = User.objects.create_user('learning-p@example.test', 'test-password')
        self.course = Course.objects.create(name='Learning', created_by=self.teacher)
        for user, role in [(self.teacher,'teacher'),(self.student,'student'),(self.peer,'student')]:
            Membership.objects.create(course=self.course,user=user,role=role)
        self.point = KnowledgePoint.objects.create(course=self.course,name='积分')
        self.empty = KnowledgePoint.objects.create(course=self.course,name='暂无证据')
        self.start = timezone.now().astimezone(utc_timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=14)
        self.end = self.start+timedelta(days=14)
        self.quiz = Quiz.objects.create(course=self.course,title='Learning evidence',status='closed',grades_published=True,
            opens_at=self.start,closes_at=self.end,answers_at=self.end)
        self.tc,self.sc,self.pc=[self.client_for(u) for u in [self.teacher,self.student,self.peer]]
        self.path=f'/api/courses/{self.course.id}/learning/'
        self.window={'start':self.start.isoformat(),'end':self.end.isoformat()}

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user);return client

    def attempt(self, student=None, day=1, qid=1, score='8', maximum='10', tags=None, quiz=None, status='finalized', revision=1):
        student=student or self.student;quiz=quiz or self.quiz
        question={'id':qid,'revision':revision,'score':maximum,'points':tags if tags is not None else [{'id':self.point.id,'name':'积分（当时）'}]}
        return QuizAttempt.objects.create(quiz=quiz,student=student,number=quiz.attempts.filter(student=student).count()+1,
            status='submitted',submitted_at=self.start+timedelta(days=day),deadline=self.end,
            grading_status=status,snapshot=[question],snapshot_hash='fixture',scores={str(qid):score},grade_revision=revision)

    def test_latest_question_in_window_and_frozen_tags(self):
        self.attempt(day=1,score='10');latest=self.attempt(day=8,score='4',revision=2)
        self.attempt(day=9,qid=2,score='6')
        self.point.name='积分新名';self.point.save()
        response=self.sc.get(self.path,self.window);self.assertEqual(response.status_code,200)
        data=response.data;point=data['students'][0]['points'][0]
        self.assertEqual(Decimal(point['mastery']),Decimal('.5'))
        self.assertEqual(point['sample_size'],2);self.assertEqual(point['name'],'积分新名')
        self.assertEqual(point['evidence'][0]['attempt_id'],latest.id)
        self.assertEqual(point['evidence'][0]['points'][0]['name'],'积分（当时）')
        self.assertEqual([Decimal(b['score_rate']) for b in data['students'][0]['trend']],[Decimal(1),Decimal('.5')])
        self.assertEqual(data['class_points'],[])

    def test_unknown_pending_and_unpublished_never_become_zero(self):
        self.attempt(status='awaiting_review',score=None)
        self.quiz.grades_published=False;self.quiz.save();self.attempt(qid=2)
        data=self.sc.get(self.path,self.window).data
        self.assertTrue(all(p['mastery'] is None and p['sample_size']==0 for p in data['students'][0]['points']))
        self.assertEqual(self.sc.get(self.path,{**self.window,'include_unpublished':'true'}).status_code,403)
        teacher=self.tc.get(self.path,{**self.window,'include_unpublished':'true'}).data
        self.assertTrue(teacher['include_unpublished'])
        point=teacher['students'][0]['points'][0]
        self.assertEqual(point['sample_size'],1);self.assertFalse(point['evidence'][0]['published'])

    def test_class_averages_people_not_total_points_or_missing_people(self):
        self.attempt(score='10',maximum='10');self.attempt(qid=2,score='100',maximum='100')
        self.attempt(student=self.peer,score='0')
        extra=User.objects.create_user('learning-empty@example.test','test-password')
        Membership.objects.create(course=self.course,user=extra,role='student')
        result=self.tc.get(self.path,self.window).data
        p=result['class_points'][0]
        self.assertEqual(Decimal(p['mastery']),Decimal('.5'))
        self.assertEqual(p['students_with_data'],2);self.assertEqual(result['student_count'],3)
        self.assertIsNone(result['class_points'][1]['mastery'])

    def test_window_boundaries_timezone_and_input_permissions(self):
        self.attempt(day=0,score='10');self.attempt(day=14,qid=2,score='0')
        response=self.sc.get(self.path,self.window)
        self.assertEqual(response.data['students'][0]['points'][0]['sample_size'],1)
        for params in [{'start':'bad'},{'end':'bad'},{'start':'2026-01-01T00:00:00'},
                       {'start':self.end.isoformat(),'end':self.start.isoformat()},
                       {'start':(self.start-timedelta(days=366)).isoformat(),'end':self.end.isoformat()},
                       {'student_id':'invalid'},{'include_unpublished':'yes'},{'sql':'select 1'}]:
            self.assertEqual(self.sc.get(self.path,{**self.window,**params}).status_code,400,params)
        self.assertEqual(self.sc.get(self.path,{**self.window,'student_id':self.peer.id}).status_code,403)
        self.assertEqual(self.tc.get(self.path,{**self.window,'student_id':self.teacher.id}).status_code,404)
        shifted={k:timezone.datetime.fromisoformat(v).astimezone(timezone.get_fixed_timezone(480)).isoformat() for k,v in self.window.items()}
        self.assertEqual(self.sc.get(self.path,shifted).data['data_version'],response.data['data_version'])

    def test_withdrawal_regrading_changes_version_and_revocation_denies(self):
        a=self.attempt();before=self.sc.get(self.path,self.window).data
        a.grade_revision+=1;a.scores={'1':'2'};a.save()
        after=self.sc.get(self.path,self.window).data
        self.assertNotEqual(after['data_version'],before['data_version'])
        self.assertEqual(Decimal(after['students'][0]['points'][0]['mastery']),Decimal('.2'))
        self.quiz.grades_published=False;self.quiz.save()
        self.assertIsNone(self.sc.get(self.path,self.window).data['students'][0]['points'][0]['mastery'])
        Membership.objects.filter(course=self.course,user=self.student).delete()
        self.assertEqual(self.sc.get(self.path,self.window).status_code,403)

    def test_multitag_untagged_revision_and_foreign_tag(self):
        other=Course.objects.create(name='Other',created_by=self.teacher)
        foreign=KnowledgePoint.objects.create(course=other,name='private')
        tags=[{'id':self.point.id,'name':'积分'},{'id':self.empty.id,'name':'暂无证据'},{'id':foreign.id,'name':'private'}]
        self.attempt(tags=tags)
        first=learning_data(self.course.id,self.start,self.end,self.student.id)
        self.assertEqual([p['sample_size'] for p in first['students'][0]['points']],[1,1])
        self.attempt(day=2,tags=[],revision=2)
        after=self.sc.get(self.path,self.window).data
        self.assertTrue(all(p['mastery'] is None for p in after['students'][0]['points']))
        self.assertNotIn('private',str(after))

    def test_cross_course_and_invalid_scores_excluded(self):
        other=Course.objects.create(name='Other',created_by=self.teacher)
        q=Quiz.objects.create(course=other,title='private',status='closed',grades_published=True,
            opens_at=self.start,closes_at=self.end,answers_at=self.end)
        self.attempt(quiz=q)
        self.attempt(score='NaN');self.attempt(qid=2,maximum='0');self.attempt(qid=3,score='11')
        data=self.sc.get(self.path,self.window).data
        self.assertIsNone(data['students'][0]['points'][0]['mastery'])
        self.assertNotIn('private',str(data))
