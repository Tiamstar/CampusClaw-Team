from io import StringIO
from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings

from .acceptance_seed import SeedAPI
from .models import (AcceptanceFixtureSet, Course, GraphEdge, KnowledgePoint, Membership,
                     QuizAttempt, QuizGradeRevision, StoredFile, User)


class AcceptanceSeedGuards(TestCase):
    def test_opt_in_and_nonempty_database_never_write(self):
        with self.assertRaisesMessage(CommandError, 'Requires'):
            call_command('seed_acceptance', stdout=StringIO())
        owner = User.objects.create_user('existing@example.invalid', None, display_name='保留用户')
        with self.assertRaisesMessage(CommandError, 'non-empty'):
            call_command('seed_acceptance', allow_synthetic_fixtures=True, stdout=StringIO())
        self.assertEqual(list(User.objects.values_list('pk', flat=True)), [owner.pk])
        self.assertFalse(AcceptanceFixtureSet.objects.exists())
        self.assertFalse(Course.objects.exists())

    def test_missing_or_weak_password_rejected_without_echo(self):
        for password in ['', '12345678']:
            with patch.dict(os.environ, {'ACCEPTANCE_FIXTURE_PASSWORD': password}):
                with self.assertRaisesMessage(CommandError, 'strong ACCEPTANCE_FIXTURE_PASSWORD'):
                    call_command('seed_acceptance', allow_synthetic_fixtures=True, stdout=StringIO())
        self.assertEqual(User.objects.count(), 0)

    def test_failed_import_rolls_back_database_and_receipt(self):
        def fail(password):
            User.objects.create_user('partial@example.invalid', None)
            raise CommandError('injected fixture failure')
        with patch.dict(os.environ, {'ACCEPTANCE_FIXTURE_PASSWORD': 'Synthetic-tests!4821'}), \
             patch('core.management.commands.seed_acceptance.build_dataset', side_effect=fail):
            with self.assertRaisesMessage(CommandError, 'injected fixture failure'):
                call_command('seed_acceptance', allow_synthetic_fixtures=True, stdout=StringIO())
        self.assertFalse(User.objects.exists())
        self.assertFalse(AcceptanceFixtureSet.objects.exists())


class AcceptanceSeedWorkflow(TestCase):
    def test_full_dataset_business_scores_statistics_isolation_and_readonly_rerun(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder), \
             patch.dict(os.environ, {'ACCEPTANCE_FIXTURE_PASSWORD': 'Synthetic-tests!4821'}), \
             patch('httpx.AsyncClient.send', side_effect=AssertionError('No external network calls')), \
             patch('httpx.Client.send', side_effect=AssertionError('No external network calls')), \
             patch('smtplib.SMTP', side_effect=AssertionError('No email calls')):
            output = StringIO()
            call_command('seed_acceptance', allow_synthetic_fixtures=True, stdout=output)
            result = json.loads(output.getvalue())
            self.assertFalse(result['reused'])
            m = result['manifest']
            self.assertNotIn('Synthetic-tests!4821', output.getvalue())
            self.assertEqual(User.objects.count(), 11)
            self.assertEqual(Course.objects.count(), 2)
            self.assertEqual(Membership.objects.filter(course_id=m['courses']['A']['id']).count(), 9)
            self.assertTrue(User.objects.get(pk=m['accounts']['T_A']['id']).check_password('Synthetic-tests!4821'))
            teacher = SeedAPI(User.objects.get(pk=m['accounts']['T_A']['id']))
            student = SeedAPI(User.objects.get(pk=m['accounts']['S_A1']['id']))
            foreign = SeedAPI(User.objects.get(pk=m['accounts']['S_B1']['id']))
            grades = teacher.call('get', f"courses/{m['courses']['A']['id']}/gradebook/")
            rows = grades['snapshots'][0]['rows']
            totals = {r['student_id']: r['total'] for r in rows}
            for i, value in enumerate(m['grades']['expected_totals'], 1):
                self.assertEqual(totals[m['accounts'][f'S_A{i}']['id']], value)
            self.assertEqual(QuizAttempt.objects.filter(grading_status='finalized').count(), 16)
            self.assertEqual(QuizGradeRevision.objects.count(), 32)
            groups = teacher.call('get', f"quizzes/{m['statistics']['quiz']}/statistics/")['groups']
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]['sample_size'], 8)
            question = next(q for q in groups[0]['questions'] if q['question_id'] == m['statistics']['designated_question'])
            self.assertEqual(question['full_correct_rate'], '0.5')
            self.assertEqual(question['discrimination'], '1')
            foreign.call('get', f"quiz-attempts/{m['quizzes']['core_attempts'][0]}/", expected=403)
            student.post(f"courses/{m['courses']['A']['id']}/questions/", m['negative_inputs']['question_invalid_kind'], 403)
            teacher.post(f"courses/{m['courses']['A']['id']}/questions/", m['negative_inputs']['question_cross_course_point'], 400)
            teacher.post(f"quizzes/{m['quizzes']['expired_draft']}/publish/", {}, 400)
            teacher.post(f"graph/candidates/{m['graph']['cycle_candidate']}/review/", {
                'action': 'approve', 'proposal': m['graph']['cycle_proposal'], 'reason': '尝试环负例', 'expected_revision': 1}, 409)
            self.assertEqual(GraphEdge.objects.count(), 2)
            self.assertFalse(KnowledgePoint.objects.get(pk=m['graph']['points']['K4']).question_set.exists())
            # Rerun after an examiner edits the fixture: no silent reset or
            # password rotation, no new API requests, grades, files or rows.
            Course.objects.filter(pk=m['courses']['A']['id']).update(name='人工验收修改必须保留')
            before = {model.__name__: model.objects.count() for model in [User, Course, QuizAttempt, QuizGradeRevision, StoredFile]}
            with patch.dict(os.environ, {'ACCEPTANCE_FIXTURE_PASSWORD': ''}), \
                 patch('core.management.commands.seed_acceptance.build_dataset', side_effect=AssertionError('Rerun must not build')):
                repeated = StringIO()
                call_command('seed_acceptance', allow_synthetic_fixtures=True, stdout=repeated)
            self.assertTrue(json.loads(repeated.getvalue())['reused'])
            self.assertEqual(json.loads(repeated.getvalue())['manifest'], m)
            self.assertEqual(before, {model.__name__: model.objects.count() for model in [User, Course, QuizAttempt, QuizGradeRevision, StoredFile]})
            self.assertEqual(Course.objects.get(pk=m['courses']['A']['id']).name, '人工验收修改必须保留')


class AcceptanceSeedConcurrency(TransactionTestCase):
    def test_simultaneous_imports_share_one_receipt(self):
        def invoke(_):
            close_old_connections()
            try:
                output = StringIO()
                call_command('seed_acceptance', allow_synthetic_fixtures=True, stdout=output)
                return json.loads(output.getvalue())
            finally:
                close_old_connections()
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder), \
             patch.dict(os.environ, {'ACCEPTANCE_FIXTURE_PASSWORD': 'Synthetic-tests!4821'}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(invoke, range(2)))
        self.assertEqual(sorted(r['reused'] for r in results), [False, True])
        self.assertEqual(results[0]['manifest'], results[1]['manifest'])
        self.assertEqual(AcceptanceFixtureSet.objects.count(), 1)
        self.assertEqual(User.objects.count(), 11)
        self.assertEqual(Course.objects.count(), 2)
