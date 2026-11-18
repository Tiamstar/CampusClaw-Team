import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import CommandError
from unittest.mock import patch
from asgiref.sync import async_to_sync

from . import test_quiz
from .models import QuizAttempt, QuizSuggestion, Membership


class QuizAIReviewTests(test_quiz.QuizTests):
    def submitted(self):
        a = self.start()
        self.save(a)
        self.sc.post(f"/api/quiz-attempts/{a['id']}/submit/", {}, format='json')
        return QuizAttempt.objects.get(pk=a['id'])

    def test_choice_answers_sent_to_model_include_unambiguous_labels(self):
        a = self.submitted()
        from .quiz_ai import model_answers
        answers = model_answers(a)
        single = answers[str(self.q[0]['id'])]
        self.assertEqual(single['encoding'], 'zero_based_option_index')
        self.assertEqual(single['selected_options'], [{'index': '0', 'label': 'A', 'text': 'A'}])
        multiple = answers[str(self.q[1]['id'])]
        self.assertEqual([r['label'] for r in multiple['selected_options']], ['A', 'C'])
        self.assertEqual(answers[str(self.q[-1]['id'])]['raw']['text'], '我的推导')

    def test_real_verifier_requires_opt_in_and_retains_only_metadata(self):
        a = self.submitted()
        async def model(*args, **kwargs):
            for q in a.snapshot:
                yield json.dumps({'question_id': q['id'], 'score': '5', 'feedback': 'private feedback marker'})+'\n', 'fixture'
        with tempfile.TemporaryDirectory() as folder:
            output = str(Path(folder)/'evidence.json')
            args = {'teacher_email': self.t.email, 'course_id': self.c.id,
                    'attempt_ids': str(a.id), 'output': output, 'stdout': StringIO()}
            with self.assertRaises(CommandError):
                call_command('verify_quiz_review', **args)
            with patch.dict(os.environ, {'MODEL_PROVIDER': 'openai'}), patch('core.quiz_ai.model_stream', model):
                call_command('verify_quiz_review', real=True, **args)
            evidence = Path(output).read_text(encoding='utf-8')
            self.assertNotIn('private feedback marker', evidence)
            self.assertNotIn(self.s.email, evidence)
            self.assertTrue(json.loads(evidence)['cases'][0]['passed'])
            self.assertEqual(QuizSuggestion.objects.filter(attempt=a).count(), 1)
            a.refresh_from_db()
            self.assertEqual(a.grade_revision, 1)

    def test_model_uses_scores_from_locked_revision_not_initial_lookup(self):
        a = self.submitted()
        stale = QuizAttempt.objects.select_related('quiz').get(pk=a.id)
        key = str(self.q[0]['id'])
        QuizAttempt.objects.filter(pk=a.id).update(scores={**a.scores, key: '3.00'}, grade_revision=2)
        async def model(*args, **kwargs):
            for q in a.snapshot:
                yield json.dumps({'question_id': q['id'], 'score': '5', 'feedback': '核对步骤'})+'\n', 'fixture'
        with patch('core.quiz_views.accessible_attempt', return_value=(stale, True)), patch('core.quiz_ai.model_stream', model):
            result = self.tc.post(f'/api/quiz-attempts/{a.id}/suggestion/', {}, format='json')
        self.assertEqual(result.data['status'], 'awaiting_review')
        body = json.loads(result.data['body'])
        self.assertEqual(body['grade_revision'], 2)
        self.assertEqual(next(r for r in body['items'] if r['question_id']==int(key))['score'], '3.00')

    def test_incremental_suggestions_do_not_write_grades_and_are_teacher_only(self):
        a = self.submitted()
        before = dict(a.scores)
        url = f'/api/quiz-attempts/{a.id}/suggestion/'
        self.assertEqual(self.sc.post(url, {'stream': True}, format='json').status_code, 403)

        async def model(*args, **kwargs):
            for q in a.snapshot:
                line = json.dumps({'question_id': q['id'], 'score': '8.50', 'feedback': '依据实际作答，步骤完整但需补充说明。'}) + '\n'
                yield line[:20], 'fixture-flash'
                yield line[20:], 'fixture-flash'

        async def read(response):
            return b''.join([c async for c in response.streaming_content]).decode()

        with patch('core.quiz_ai.model_stream', model):
            response = self.tc.post(url, {'stream': True}, format='json')
            wire = async_to_sync(read)(response)
        self.assertIn('event: status', wire)
        self.assertEqual(wire.count('event: item'), len(a.snapshot))
        self.assertIn('event: complete', wire)
        item = QuizSuggestion.objects.get(attempt=a)
        self.assertEqual(item.status, 'awaiting_review')
        self.assertEqual(len(json.loads(item.body)['items']), 5)
        for row in json.loads(item.body)['items']:
            if before[str(row['question_id'])] is not None:
                self.assertEqual(row['score'], str(before[str(row['question_id'])]))
        a.refresh_from_db()
        self.assertEqual(a.scores, before)
        self.assertIsNone(a.scores[str(self.q[-1]['id'])])

    def test_invalid_score_fails_without_exposing_model_output(self):
        a = self.submitted()
        async def model(*args, **kwargs):
            yield json.dumps({'question_id': a.snapshot[0]['id'], 'score': '99999', 'feedback': 'private injected marker'}), 'fixture'
        with patch('core.quiz_ai.model_stream', model):
            r = self.tc.post(f'/api/quiz-attempts/{a.id}/suggestion/', {}, format='json')
        self.assertEqual(r.data['status'], 'failed')
        self.assertNotIn('private injected marker', r.data['body'])
        self.assertIsNone(QuizAttempt.objects.get(pk=a.id).scores[str(self.q[-1]['id'])])

    def test_running_duplicate_rejected_and_stale_grade_cannot_be_adopted(self):
        a = self.submitted()
        url = f'/api/quiz-attempts/{a.id}/suggestion/'
        old = QuizSuggestion.objects.create(attempt=a)
        self.assertEqual(self.tc.post(url, {}, format='json').status_code, 409)
        old.status = 'failed'; old.save()
        async def model(*args, **kwargs):
            for q in a.snapshot:
                yield json.dumps({'question_id': q['id'], 'score': '5', 'feedback': '需复核'}) + '\n', 'fixture'
            # Simulate a separate teacher changing the grade while the model runs.
            from asgiref.sync import sync_to_async
            await sync_to_async(QuizAttempt.objects.filter(pk=a.id).update)(grade_revision=9)
        with patch('core.quiz_ai.model_stream', model):
            r = self.tc.post(url, {}, format='json')
        self.assertEqual(r.data['status'], 'failed')
