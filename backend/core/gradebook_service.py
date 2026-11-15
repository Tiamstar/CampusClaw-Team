"""Deterministic grade snapshots; GET reads never materialize business records."""
from decimal import Decimal, ROUND_HALF_UP
from .models import Assignment, SubmissionVersion, Quiz, GradePolicy, Membership
from .quiz_service import fingerprint


def validate_items(course_id, items):
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError('成绩项须为 1–50 项')
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'kind', 'source_id', 'weight'}:
            raise ValueError('成绩项字段无效')
        kind, source_id = item['kind'], item['source_id']
        if kind not in {'assignment', 'quiz'} or type(source_id) is not int or (kind, source_id) in seen:
            raise ValueError('成绩来源无效或重复')
        try:
            weight = Decimal(str(item['weight']))
            if not weight.is_finite() or not 0 < weight <= 100 or weight != weight.quantize(Decimal('.01')):
                raise ValueError()
        except Exception:
            raise ValueError('权重须为大于零、至多两位小数的百分比')
        model = Assignment if kind == 'assignment' else Quiz
        source = model.objects.filter(pk=source_id, course_id=course_id).first()
        if source is None or (kind == 'assignment' and source.max_score <= 0) or (kind == 'quiz' and source.status == 'draft'):
            raise ValueError('成绩来源不存在、未发布或满分无效')
        seen.add((kind, source_id))
        result.append({'kind': kind, 'source_id': source_id, 'weight': str(weight)})
    if sum(Decimal(i['weight']) for i in result) != 100:
        raise ValueError('权重合计必须为 100%')
    return result


def collect(course_id):
    policy = GradePolicy.objects.filter(course_id=course_id).first()
    if not policy:
        return {'policy_revision': 0, 'items': [], 'rows': [], 'fingerprint': None}
    students = list(Membership.objects.filter(course_id=course_id, role='student').select_related('user').order_by('user_id'))
    items, sources = [], []
    for rule in policy.items:
        if rule['kind'] == 'assignment':
            source = Assignment.objects.filter(pk=rule['source_id'], course_id=course_id).first()
            versions = SubmissionVersion.objects.filter(submission__assignment=source).select_related('submission').order_by('number', 'id') if source else []
            selected = {v.submission.student_id: v for v in versions}
            values = {}
            for sid, v in selected.items():
                values[sid] = {'status': 'finalized' if v.score is not None else 'awaiting_review',
                    'score': str(v.score) if v.score is not None else None, 'max_score': str(source.max_score),
                    'source_record': v.id, 'grade_revision': v.grading_revision, 'published': v.published_at is not None}
            maximum = str(source.max_score) if source else None
        else:
            source = Quiz.objects.filter(pk=rule['source_id'], course_id=course_id).first()
            values = {}
            if source:
                for a in source.attempts.filter(status='submitted', grading_status='finalized').order_by('submitted_at', 'id'):
                    total = sum(Decimal(v) for v in a.scores.values())
                    if a.student_id not in values or total >= Decimal(values[a.student_id]['score']):
                        values[a.student_id] = {'status': 'finalized', 'score': str(total),
                            'max_score': str(sum(Decimal(q['score']) for q in a.snapshot)),
                            'source_record': a.id, 'grade_revision': a.grade_revision, 'published': source.grades_published,
                            'paper_hash': a.snapshot_hash}
                for a in source.attempts.order_by('id'):
                    if a.student_id not in values:
                        values[a.student_id] = {'status': 'in_progress' if a.status == 'in_progress' else 'awaiting_review',
                            'score': None, 'max_score': None, 'source_record': a.id, 'grade_revision': a.grade_revision, 'published': False}
            maximum = None  # Random papers carry their own immutable maximum.
        items.append({**rule, 'title': source.title if source else '来源已失效', 'max_score': maximum,
                      'selection': 'latest_submission' if rule['kind'] == 'assignment' else 'highest_finalized_then_latest'})
        sources.append(values)
    rows = []
    for member in students:
        entries = []
        total = Decimal(0)
        complete, publishable = True, True
        for item, values in zip(items, sources):
            value = values.get(member.user_id, {'status': 'missing', 'score': None, 'max_score': None,
                                               'source_record': None, 'grade_revision': None, 'published': False})
            if value['status'] == 'finalized' and (not value['max_score'] or Decimal(value['max_score']) <= 0 or not 0 <= Decimal(value['score']) <= Decimal(value['max_score'])):
                value = {**value, 'status': 'invalid_score', 'published': False}
            entries.append({**value, 'kind': item['kind'], 'source_id': item['source_id']})
            if value['status'] != 'finalized' or not value['max_score'] or Decimal(value['max_score']) <= 0:
                complete = False
            else:
                total += Decimal(value['score']) / Decimal(value['max_score']) * Decimal(item['weight'])
            publishable = publishable and value['published']
        rows.append({'student_id': member.user_id, 'name': member.user.display_name, 'entries': entries,
                     'complete': complete, 'publishable': bool(complete and publishable),
                     'total': str(total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if complete else None})
    data = {'policy_revision': policy.revision, 'items': items, 'rows': rows}
    return {**data, 'fingerprint': fingerprint(data)}


def snapshot_data(snapshot, current, student_id=None):
    stale = snapshot.fingerprint != current['fingerprint']
    rows = snapshot.rows if student_id is None else [r for r in snapshot.rows if r['student_id'] == student_id]
    visible_fingerprint = snapshot.fingerprint if student_id is None else fingerprint({'policy_revision': snapshot.policy_revision, 'items': snapshot.items, 'rows': rows})
    return {'id': snapshot.id, 'policy_revision': snapshot.policy_revision, 'items': snapshot.items,
            'rows': rows, 'fingerprint': visible_fingerprint, 'created_at': snapshot.created_at,
            'published_at': snapshot.published_at, 'stale': stale}


def authorized_grades(user, course_id):
    from .forum_views import access
    from .models import GradeSnapshot
    teacher = access(user, course_id).role == 'teacher'
    current = collect(course_id)
    snapshots = GradeSnapshot.objects.filter(course_id=course_id).order_by('-id')
    if teacher:
        return {'current': current, 'snapshots': [snapshot_data(s, current) for s in snapshots[:20]]}
    visible = snapshots.filter(published_at__isnull=False, fingerprint=current['fingerprint']).first() if current['fingerprint'] else None
    return {'snapshot': snapshot_data(visible, current, user.id) if visible else None}
