"""Versioned homework submissions, teacher review, and explicit grade release."""
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import hashlib
import re

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import Assignment, Membership, Submission, SubmissionGradeRevision, SubmissionVersion
from .views import EXTENSIONS, MAX_BYTES, fail, file_data, member, store_file, validate_file

MAX_FILES = 10
MAX_TEXT = 50000


def version_status(version):
    if version is None:
        return 'unsubmitted'
    if version.score is not None:
        return 'graded'
    return 'pending_review' if version.review_started_at else 'submitted'


def version_data(version, teacher=False):
    files = list(version.files.all())
    if not files and version.attachment_id:
        files = [version.attachment]
    grade = None
    if teacher or version.published_at:
        if version.score is not None:
            grade = {'score': str(version.score), 'feedback': version.feedback,
                     'graded_at': version.graded_at, 'published': bool(version.published_at),
                     'published_at': version.published_at, 'revision': version.grading_revision}
    data = {'id': version.id, 'number': version.number, 'submitted_at': version.submitted_at,
            'is_late': version.is_late, 'text_content': version.text_content,
            'files': [file_data(item) for item in files],
            'attachment': file_data(files[0]) if files else None,
            'status': version_status(version), 'grade': grade,
            'grade_published': bool(version.published_at)}
    if teacher:
        data['grading_revision'] = version.grading_revision
        data['grade_history'] = [
            {'revision': row.revision, 'score': str(row.score), 'feedback': row.feedback,
             'published': row.published, 'reason': row.reason, 'created_at': row.created_at}
            for row in version.grade_revisions.all()
        ]
    return data


def version_queryset():
    return SubmissionVersion.objects.select_related('attachment').prefetch_related('files', 'grade_revisions').order_by('-number')


def assignment_data(assignment, user, role=None):
    data = {'id': assignment.id, 'title': assignment.title, 'description': assignment.description,
            'due_at': assignment.due_at, 'allow_late': assignment.allow_late,
            'allowed_extensions': assignment.allowed_extensions, 'max_file_size_mb': assignment.max_file_size_mb,
            'max_score': str(assignment.max_score), 'created_at': assignment.created_at,
            'attachment': file_data(assignment.attachment) if assignment.attachment else None,
            'submission_limits': {'max_files': MAX_FILES, 'max_total_bytes': MAX_BYTES, 'max_text_length': MAX_TEXT}}
    if role == 'student' or (role is None and member(user, assignment.course_id, 'student')):
        submissions = getattr(assignment, '_my_submissions', None)
        submission = submissions[0] if submissions else None
        if submissions is None:
            submission = Submission.objects.filter(assignment=assignment, student=user).prefetch_related(
                Prefetch('versions', queryset=version_queryset())).first()
        versions = list(submission.versions.all()) if submission else []
        data['submission_status'] = version_status(versions[0] if versions else None)
        data['my_versions'] = [version_data(version) for version in versions]
    return data


def score_value(raw, maximum):
    if isinstance(raw, bool) or len(str(raw)) > 30:
        raise ValueError('分数格式无效')
    try:
        value = Decimal(str(raw))
        if not value.is_finite() or value < 0 or value > maximum or value != value.quantize(Decimal('.01')):
            raise ValueError(f'分数须在 0–{maximum} 之间，最多两位小数')
    except InvalidOperation as error:
        raise ValueError('分数格式无效') from error
    return value.quantize(Decimal('.01'))


@api_view(['GET', 'POST'])
def assignments(request, course_id):
    membership = member(request.user, course_id)
    if not membership:
        return fail('无权访问课程', 403)
    if request.method == 'GET':
        rows = Assignment.objects.filter(course_id=course_id).select_related('attachment').order_by('-created_at', '-id')
        if membership.role == 'student':
            mine = Submission.objects.filter(student=request.user).prefetch_related(Prefetch('versions', queryset=version_queryset()))
            rows = rows.prefetch_related(Prefetch('submissions', queryset=mine, to_attr='_my_submissions'))
        return Response([assignment_data(row, request.user, membership.role) for row in rows])
    if membership.role != 'teacher':
        return fail('仅教师可发布作业', 403)
    if not isinstance(request.data, Mapping):
        return fail('请求必须是对象')
    title = str(request.data.get('title', '')).strip()
    try:
        due = parse_datetime(str(request.data.get('due_at', '')))
    except ValueError:
        due = None
    if not title or len(title) > 200 or not due or timezone.is_naive(due):
        return fail('请填写有效标题和带时区的截止时间')
    raw_extensions = str(request.data.get('allowed_extensions', '')).strip().lower()
    extensions = [part.strip().lstrip('.') for part in raw_extensions.split(',') if part.strip()]
    if any(extension not in EXTENSIONS for extension in extensions):
        return fail('包含不支持的文件格式')
    try:
        max_mb = int(request.data.get('max_file_size_mb', 50))
        maximum = score_value(request.data.get('max_score', '100'), Decimal('99999.99'))
        if not 1 <= max_mb <= 50 or maximum <= 0:
            raise ValueError('单文件限制须为 1–50 MB，满分须大于零')
    except (ValueError, TypeError) as error:
        return fail(str(error))
    upload = request.FILES.get('file')
    if upload:
        error = validate_file(upload)
        if error:
            return fail(error)
    created_files = []
    try:
        with transaction.atomic():
            attached = store_file(membership.course, request.user, upload, 'assignment') if upload else None
            if attached:
                created_files.append(attached)
            assignment = Assignment.objects.create(
                course_id=course_id, title=title, description=str(request.data.get('description', '')),
                due_at=due, allow_late=str(request.data.get('allow_late', 'false')).lower() == 'true',
                allowed_extensions=extensions, max_file_size_mb=max_mb, max_score=maximum, attachment=attached,
            )
    except BaseException:
        for item in created_files:
            item.file.delete(save=False)
        raise
    return Response(assignment_data(assignment, request.user, membership.role), status=201)


@api_view(['GET'])
def assignment_detail(request, assignment_id):
    assignment = get_object_or_404(Assignment.objects.select_related('attachment'), pk=assignment_id)
    membership = member(request.user, assignment.course_id)
    if not membership:
        return fail('无权访问作业', 403)
    return Response(assignment_data(assignment, request.user, membership.role))


@api_view(['GET'])
def submissions(request, assignment_id):
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    if not member(request.user, assignment.course_id, 'teacher'):
        return fail('仅教师可查看提交', 403)
    rows = Submission.objects.filter(assignment=assignment).prefetch_related(Prefetch('versions', queryset=version_queryset()))
    by_student = {row.student_id: row for row in rows}
    students = Membership.objects.filter(course_id=assignment.course_id, role='student').select_related('user').order_by('joined_at', 'id')
    result = []
    for membership in students:
        submission = by_student.get(membership.user_id)
        versions = list(submission.versions.all()) if submission else []
        result.append({'id': submission.id if submission else None,
                       'student': {'id': membership.user_id, 'name': membership.user.display_name, 'email': membership.user.email},
                       'status': version_status(versions[0] if versions else None),
                       'versions': [version_data(version, teacher=True) for version in versions]})
    return Response(result)


def submission_hash(text, uploads):
    raw_text = text.encode('utf-8')
    digest = hashlib.sha256(len(raw_text).to_bytes(8, 'big') + raw_text + len(uploads).to_bytes(2, 'big'))
    for upload in uploads:
        name = upload.name.encode('utf-8')
        digest.update(len(name).to_bytes(4, 'big') + name + upload.size.to_bytes(8, 'big'))
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
    return digest.hexdigest()


@api_view(['POST'])
def submit(request, assignment_id):
    assignment = get_object_or_404(Assignment, pk=assignment_id)
    if not member(request.user, assignment.course_id, 'student'):
        return fail('仅本课程学生可提交', 403)
    if not isinstance(request.data, Mapping):
        return fail('请求必须是对象')
    text = request.data.get('text_content', '')
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        return fail(f'文字作答最多 {MAX_TEXT} 字')
    uploads = request.FILES.getlist('files') + request.FILES.getlist('file')
    if not text.strip() and not uploads:
        return fail('请填写文字作答或添加附件')
    if len(uploads) > MAX_FILES or sum(upload.size for upload in uploads) > MAX_BYTES:
        return fail('最多 10 个附件，合计不能超过 50 MB')
    for upload in uploads:
        error = validate_file(upload, set(assignment.allowed_extensions) if assignment.allowed_extensions else EXTENSIONS,
                              assignment.max_file_size_mb * 1024 * 1024)
        if error:
            return fail(f'{upload.name}：{error}')
    key = request.headers.get('Idempotency-Key', request.data.get('submission_key', ''))
    if not isinstance(key, str) or (key and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key)):
        return fail('提交标识无效')
    fingerprint = submission_hash(text, uploads)
    created_files = []
    try:
        with transaction.atomic():
            submission, _ = Submission.objects.select_for_update().get_or_create(assignment=assignment, student=request.user)
            existing = submission.versions.filter(submission_key=key).first() if key else None
            if existing:
                if existing.content_hash != fingerprint:
                    return fail('相同提交标识对应的内容已变化，请重新提交', 409)
                return Response(version_data(existing))
            late = timezone.now() >= assignment.due_at
            if late and not assignment.allow_late:
                raise PermissionDenied('作业已截止')
            for upload in uploads:
                created_files.append(store_file(assignment.course, request.user, upload, 'submission'))
            next_number = (submission.versions.order_by('-number').values_list('number', flat=True).first() or 0) + 1
            version = SubmissionVersion.objects.create(
                submission=submission, number=next_number, text_content=text, is_late=late,
                attachment=created_files[0] if created_files else None, submission_key=key, content_hash=fingerprint,
            )
            version.files.set(created_files)
    except BaseException:
        for item in created_files:
            item.file.delete(save=False)
        raise
    return Response(version_data(version), status=201)


def teacher_version(request, version_id):
    version = get_object_or_404(SubmissionVersion.objects.select_related('submission__assignment'), pk=version_id)
    if not member(request.user, version.submission.assignment.course_id, 'teacher'):
        raise PermissionDenied('仅任课教师可批改')
    return version


def current_version(version):
    return version.submission.versions.order_by('-number').values_list('id', flat=True).first() == version.id


@api_view(['POST'])
def start_review(request, version_id):
    initial = teacher_version(request, version_id)
    with transaction.atomic():
        Submission.objects.select_for_update().get(pk=initial.submission_id)
        version = SubmissionVersion.objects.select_for_update().get(pk=initial.id)
        if not current_version(version):
            return fail('学生已有更新提交，请刷新后批改最新版本', 409)
        if not version.review_started_at:
            version.review_started_at = timezone.now()
            version.save(update_fields=['review_started_at'])
    return Response(version_data(version, teacher=True))


def save_grade_revision(version, actor, reason):
    version.grading_revision += 1
    version.save()
    SubmissionGradeRevision.objects.create(
        version=version, revision=version.grading_revision, score=version.score, feedback=version.feedback,
        published=bool(version.published_at), actor=actor, reason=reason,
    )


@api_view(['POST'])
def grade_submission(request, version_id):
    initial = teacher_version(request, version_id)
    if not isinstance(request.data, Mapping):
        return fail('请求必须是对象')
    try:
        score = score_value(request.data.get('score'), initial.submission.assignment.max_score)
    except ValueError as error:
        return fail(str(error))
    feedback, reason = request.data.get('feedback', ''), request.data.get('reason', '')
    published = request.data.get('published', False)
    revision = request.data.get('expected_revision')
    if not isinstance(feedback, str) or len(feedback) > 10000 or not isinstance(reason, str) or len(reason) > 500:
        return fail('评语最多 10000 字，修改说明最多 500 字')
    if not isinstance(published, bool) or type(revision) is not int:
        return fail('公开选项或批改版本无效')
    with transaction.atomic():
        Submission.objects.select_for_update().get(pk=initial.submission_id)
        version = SubmissionVersion.objects.select_for_update().get(pk=initial.id)
        if not current_version(version) or version.grading_revision != revision:
            return fail('提交或批改记录已更新，请刷新后重试', 409)
        if version.score is not None and version.score != score and not reason.strip():
            return fail('修改成绩时请填写修改说明')
        version.score, version.feedback = score, feedback
        version.graded_by, version.graded_at = request.user, timezone.now()
        version.review_started_at = version.review_started_at or version.graded_at
        version.published_at = version.graded_at if published else None
        save_grade_revision(version, request.user, reason.strip())
    return Response(version_data(version, teacher=True))


@api_view(['POST'])
def publish_grade(request, version_id):
    initial = teacher_version(request, version_id)
    if not isinstance(request.data, Mapping) or not isinstance(request.data.get('published'), bool) or type(request.data.get('expected_revision')) is not int:
        return fail('公开选项或批改版本无效')
    with transaction.atomic():
        Submission.objects.select_for_update().get(pk=initial.submission_id)
        version = SubmissionVersion.objects.select_for_update().get(pk=initial.id)
        if not current_version(version) or version.grading_revision != request.data['expected_revision']:
            return fail('提交或批改记录已更新，请刷新后重试', 409)
        if version.score is None:
            return fail('请先保存批改成绩')
        version.published_at = timezone.now() if request.data['published'] else None
        save_grade_revision(version, request.user, '公开成绩' if version.published_at else '撤回公开')
    return Response(version_data(version, teacher=True))
