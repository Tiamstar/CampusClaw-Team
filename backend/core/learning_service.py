"""Shared, reproducible mastery calculations over authorized formal quiz evidence."""
from datetime import timedelta
from datetime import datetime
from decimal import Decimal
from .models import KnowledgePoint, Membership, QuizAttempt
from .quiz_service import fingerprint

POLICY = 'latest_valid_per_student_question; frozen_point_tags; submitted_at_UTC; weekly_latest; v1'


def evidence(course_id, student_ids, start, end, include_unpublished=False):
    attempts = QuizAttempt.objects.filter(quiz__course_id=course_id, student_id__in=student_ids,
        status='submitted', grading_status='finalized', submitted_at__gte=start, submitted_at__lt=end).select_related('quiz').order_by('submitted_at', 'id')
    if not include_unpublished:
        attempts = attempts.filter(quiz__grades_published=True)
    point_ids = set(KnowledgePoint.objects.filter(course_id=course_id).values_list('id', flat=True))
    result = []
    for attempt in attempts:
        for question in attempt.snapshot:
            raw = attempt.scores.get(str(question['id']))
            try:
                score, maximum = Decimal(str(raw)), Decimal(str(question['score']))
                if not score.is_finite() or not maximum.is_finite() or maximum <= 0 or not 0 <= score <= maximum:
                    continue
            except Exception:
                continue
            tags = {p['id']: p['name'] for p in question.get('points', []) if p.get('id') in point_ids}
            # Include untagged records in selection: a later untagged revision must not revive old tags.
            result.append({'student_id': attempt.student_id, 'question_id': question['id'],
                'question_revision': question['revision'], 'attempt_id': attempt.id, 'quiz_id': attempt.quiz_id,
                'grade_revision': attempt.grade_revision, 'score': str(score), 'maximum': str(maximum),
                'points': [{'id': key, 'name': value} for key, value in sorted(tags.items())],
                'submitted_at': attempt.submitted_at.isoformat(), 'published': attempt.quiz.grades_published})
    return result


def latest(records):
    selected = {}
    for record in records:
        selected[(record['student_id'], record['question_id'])] = record
    return list(selected.values())


def band(ratio):
    if ratio is None:
        return 'unknown'
    return 'consolidate' if ratio < Decimal('.6') else 'developing' if ratio < Decimal('.8') else 'secure'


def points_for(points, records):
    rows = []
    for point in points:
        used = [r for r in records if any(p['id'] == point['id'] for p in r['points'])]
        maximum = sum((Decimal(r['maximum']) for r in used), Decimal(0))
        earned = sum((Decimal(r['score']) for r in used), Decimal(0))
        ratio = earned / maximum if maximum else None
        rows.append({**point, 'earned': str(earned), 'maximum': str(maximum), 'sample_size': len(used),
                     'mastery': str(ratio) if ratio is not None else None, 'band': band(ratio),
                     'evidence': used})
    return rows


def learning_data(course_id, start, end, student_id=None, include_unpublished=False):
    students = list(Membership.objects.filter(course_id=course_id, role='student').select_related('user').order_by('user_id'))
    if student_id is not None:
        students = [s for s in students if s.user_id == student_id]
    points = list(KnowledgePoint.objects.filter(course_id=course_id).order_by('id').values('id', 'name'))
    records = evidence(course_id, [s.user_id for s in students], start, end, include_unpublished)
    people = []
    for member in students:
        own = [r for r in records if r['student_id'] == member.user_id]
        trend = []
        cursor = start
        while cursor < end:
            stop = min(cursor + timedelta(days=7), end)
            selected = latest([r for r in own if cursor <= datetime.fromisoformat(r['submitted_at']) < stop])
            used = [r for r in selected if r['points']]
            maximum = sum((Decimal(r['maximum']) for r in used), Decimal(0))
            score = sum((Decimal(r['score']) for r in used), Decimal(0))
            trend.append({'start': cursor.isoformat(), 'end': stop.isoformat(), 'sample_size': len(used),
                          'score_rate': str(score / maximum) if maximum else None})
            cursor = stop
        people.append({'student_id': member.user_id, 'name': member.user.display_name,
                       'points': points_for(points, latest(own)), 'trend': trend})
    aggregate = []
    for index, point in enumerate(points):
        observed = [p['points'][index] for p in people if p['points'][index]['mastery'] is not None]
        average = sum((Decimal(p['mastery']) for p in observed), Decimal(0)) / len(observed) if observed else None
        aggregate.append({**point, 'mastery': str(average) if average is not None else None,
                          'band': band(average), 'students_with_data': len(observed),
                          'sample_size': sum(p['sample_size'] for p in observed)})
    payload = {'window': {'start': start.isoformat(), 'end': end.isoformat(), 'end_exclusive': True,
                          'timezone': 'UTC', 'bucket_days': 7},
               'policy': POLICY, 'include_unpublished': include_unpublished, 'students': people,
               'class_points': aggregate if student_id is None else [],
               'student_count': len(students), 'evidence_versions': records}
    version = fingerprint(payload)
    # Individual evidence already accompanies each point. Avoid returning duplicate records.
    payload.pop('evidence_versions')
    return {**payload, 'data_version': version}
