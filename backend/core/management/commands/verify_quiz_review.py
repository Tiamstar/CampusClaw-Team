"""Explicit retained real-model draft experiment; never changes formal grades."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIClient
from core.models import User, Membership, QuizAttempt, QuizSuggestion


class Command(BaseCommand):
    help = 'Verify up to two existing submitted quiz drafts with a real model; retain suggestions.'

    def add_arguments(self, parser):
        parser.add_argument('--real', action='store_true')
        parser.add_argument('--teacher-email', required=True)
        parser.add_argument('--course-id', type=int, required=True)
        parser.add_argument('--attempt-ids', required=True)
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        if not options['real'] or os.getenv('MODEL_PROVIDER', 'mock') == 'mock':
            raise CommandError('Explicit --real and configured real model required')
        try:
            ids = [int(value) for value in options['attempt_ids'].split(',')]
        except ValueError:
            raise CommandError('Invalid attempt IDs') from None
        if not 1 <= len(ids) <= 2 or len(set(ids)) != len(ids):
            raise CommandError('Choose one or two distinct existing attempts')
        user = User.objects.get(email=options['teacher_email'])
        if not Membership.objects.filter(user=user, course_id=options['course_id'], role='teacher').exists():
            raise CommandError('Teacher membership required')
        attempts = list(QuizAttempt.objects.filter(id__in=ids, quiz__course_id=options['course_id'],
                        status='submitted').select_related('quiz'))
        if len(attempts) != len(ids):
            raise CommandError('All attempts must be submitted in the authorized course')
        client = APIClient(); client.force_authenticate(user)
        evidence = {'transport': 'Django APIClient with real configured model', 'retained': True,
                    'formal_grades_written': False, 'cases': []}
        failed = False
        for attempt in attempts:
            before = (attempt.scores, attempt.feedback, attempt.grade_revision, attempt.grading_status,
                      attempt.quiz.grades_published, attempt.grade_history.count())
            response = client.post(f'/api/quiz-attempts/{attempt.id}/suggestion/', {}, format='json', HTTP_HOST='localhost')
            row = {'attempt_id': attempt.id, 'http_status': response.status_code}
            if response.status_code == 201:
                result = response.data
                row.update(suggestion_id=result['id'], status=result['status'], model=result['model'])
                if result['status'] == 'awaiting_review':
                    body = json.loads(result['body'])
                    row.update(items=len(body['items']), grade_revision=body['grade_revision'],
                        null_scores=sum(i['score'] is None for i in body['items']),
                        missing_references=sum(i['needs_reference'] for i in body['items']),
                        complete=set(i['question_id'] for i in body['items']) == set(q['id'] for q in attempt.snapshot))
                    restored = client.get(f'/api/quiz-attempts/{attempt.id}/suggestion/', HTTP_HOST='localhost')
                    row['recoverable'] = restored.status_code == 200 and any(i['id'] == result['id'] for i in restored.data)
                else:
                    row['failure'] = 'Model draft failed; inspect authorized UI for safe diagnostics'
            attempt.refresh_from_db(); attempt.quiz.refresh_from_db()
            after = (attempt.scores, attempt.feedback, attempt.grade_revision, attempt.grading_status,
                     attempt.quiz.grades_published, attempt.grade_history.count())
            row['formal_state_unchanged'] = before == after
            row['passed'] = row.get('complete', False) and row.get('recoverable', False) and row['formal_state_unchanged']
            failed = failed or not row['passed']
            evidence['cases'].append(row)
        # Only metadata; no student names, answers, feedback, secrets or provider error bodies.
        Path(options['output']).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(evidence, ensure_ascii=False))
        if failed:
            raise CommandError('Real draft verification incomplete; evidence and suggestions retained')
