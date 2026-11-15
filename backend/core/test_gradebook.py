from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import (User, Course, Membership, Assignment, Submission, SubmissionVersion,
                     Quiz, QuizAttempt, GradePolicy, GradeSnapshot)


class GradebookTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('gb-t@example.test', 'test-password')
        self.student = User.objects.create_user('gb-s@example.test', 'test-password', display_name='=1+1')
        self.peer = User.objects.create_user('gb-p@example.test', 'test-password')
        self.course = Course.objects.create(name='Gradebook', created_by=self.teacher)
        for user, role in [(self.teacher, 'teacher'), (self.student, 'student')]:
            Membership.objects.create(course=self.course, user=user, role=role)
        self.tc, self.sc, self.pc = [self.client_for(u) for u in (self.teacher, self.student, self.peer)]
        self.base = f'/api/courses/{self.course.id}/'
        now = timezone.now()
        self.assignment = Assignment.objects.create(course=self.course, title='=HYPERLINK("evil")', due_at=now, max_score=80)
        submission = Submission.objects.create(assignment=self.assignment, student=self.student)
        self.version = SubmissionVersion.objects.create(submission=submission, number=1, score=60,
            grading_revision=1, published_at=now)
        self.quiz = Quiz.objects.create(course=self.course, title='Quiz', status='published',
            opens_at=now-timedelta(days=1), closes_at=now+timedelta(days=1), answers_at=now+timedelta(days=1), grades_published=True)
        self.attempt = QuizAttempt.objects.create(quiz=self.quiz, student=self.student, number=1,
            status='submitted', submitted_at=now, deadline=now, snapshot=[{'id':1,'score':'50'}],
            snapshot_hash='fixture', grading_status='finalized', scores={'1':'40'}, grade_revision=2)
        self.items = [{'kind':'assignment','source_id':self.assignment.id,'weight':'60'},
                      {'kind':'quiz','source_id':self.quiz.id,'weight':'40'}]

    def client_for(self, user):
        client = APIClient(); client.force_authenticate(user); return client

    def configure(self):
        response = self.tc.put(self.base+'grade-policy/', {'items':self.items,'expected_revision':0}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def generate(self):
        response = self.tc.post(self.base+'gradebook/', {}, format='json')
        self.assertIn(response.status_code, (200,201), response.data)
        return response.data

    def publish(self, snapshot):
        return self.tc.post(f"/api/grade-snapshots/{snapshot['id']}/publication/", {'published':True}, format='json')

    def test_reads_no_writes_and_scope(self):
        self.assertEqual(self.tc.get(self.base+'grade-policy/').data, {'revision':0,'items':[]})
        self.assertEqual(self.sc.get(self.base+'gradebook/').data, {'snapshot':None})
        self.assertEqual(GradePolicy.objects.count(),0); self.assertEqual(GradeSnapshot.objects.count(),0)
        self.assertEqual(self.sc.put(self.base+'grade-policy/',{},format='json').status_code,403)
        self.assertEqual(self.pc.get(self.base+'gradebook/').status_code,403)

    def test_weight_validation_and_compare_revision(self):
        for items in [[], [dict(self.items[0], weight='99')], [dict(self.items[0], weight='NaN')],
                      [dict(self.items[0], source_id=999)], [self.items[0],self.items[0]]]:
            self.assertEqual(self.tc.put(self.base+'grade-policy/',{'items':items,'expected_revision':0},format='json').status_code,400)
        self.configure()
        self.assertEqual(self.tc.put(self.base+'grade-policy/',{'items':self.items,'expected_revision':0},format='json').status_code,409)
        self.assertEqual(GradePolicy.objects.get().revision,1)

    def test_decimal_snapshot_idempotency_and_publication_privacy(self):
        self.configure(); snapshot = self.generate()
        self.assertEqual(snapshot['rows'][0]['total'],'77.00')
        self.assertEqual(self.generate()['id'],snapshot['id']); self.assertEqual(GradeSnapshot.objects.count(),1)
        self.assertIsNone(self.sc.get(self.base+'gradebook/').data['snapshot'])
        self.assertEqual(self.publish(snapshot).status_code,200)
        result=self.sc.get(self.base+'gradebook/').data['snapshot']
        self.assertEqual(result['rows'][0]['total'],'77.00')
        self.assertEqual([r['student_id'] for r in result['rows']],[self.student.id])
        self.assertEqual(result['rows'][0]['entries'][1]['grade_revision'],2)

    def test_changed_or_withdrawn_sources_invalidate_published_snapshot(self):
        self.configure(); snapshot=self.generate(); self.publish(snapshot)
        self.version.score=Decimal(70); self.version.grading_revision+=1; self.version.published_at=None; self.version.save()
        self.assertIsNone(self.sc.get(self.base+'gradebook/').data['snapshot'])
        self.assertTrue(self.tc.get(self.base+'gradebook/').data['snapshots'][0]['stale'])
        self.assertEqual(self.publish(snapshot).status_code,409)
        replacement=self.generate()
        self.assertEqual(self.publish(replacement).status_code,409)
        self.assertEqual(GradeSnapshot.objects.get(pk=snapshot['id']).rows[0]['total'],'77.00')

    def test_missing_and_latest_ungraded_submission_not_silent_zero(self):
        self.configure()
        SubmissionVersion.objects.create(submission=self.version.submission,number=2,text_content='new submission')
        Membership.objects.create(course=self.course,user=self.peer,role='student')
        snapshot=self.generate()
        self.assertTrue(all(r['total'] is None and not r['complete'] for r in snapshot['rows']))
        self.assertEqual(snapshot['rows'][0]['entries'][0]['status'],'awaiting_review')
        self.assertEqual(snapshot['rows'][1]['entries'][0]['status'],'missing')
        self.assertEqual(self.publish(snapshot).status_code,409)

    def test_excel_matches_immutable_rows_and_never_contains_formula_nodes(self):
        self.configure(); snapshot=self.generate()
        path=f"/api/grade-snapshots/{snapshot['id']}/export/"
        self.assertEqual(self.sc.get(path).status_code,403)
        response=self.tc.get(path); self.assertEqual(response.status_code,200)
        with ZipFile(BytesIO(response.content)) as book:
            sheet=ElementTree.fromstring(book.read('xl/worksheets/sheet1.xml'))
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual(sheet.findall('.//s:f',ns),[])
            texts=[node.text for node in sheet.findall('.//s:t',ns)]
            self.assertIn('=1+1',texts); self.assertIn('77.00',texts)
            self.assertTrue(any('评分v2' in (t or '') for t in texts))
            self.assertTrue(all(c.get('t')=='inlineStr' for c in sheet.findall('.//s:c',ns)))

    def test_changed_maximum_does_not_publish_out_of_range_grade(self):
        self.configure()
        self.assignment.max_score=50; self.assignment.save()
        snapshot=self.generate()
        self.assertIsNone(snapshot['rows'][0]['total'])
        self.assertEqual(snapshot['rows'][0]['entries'][0]['status'],'invalid_score')
        self.assertEqual(self.publish(snapshot).status_code,409)
