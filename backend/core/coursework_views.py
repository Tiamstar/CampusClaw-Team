import uuid
from decimal import Decimal
from django.db import transaction
from django.db.models import OuterRef, Subquery, F
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Course, Membership, Submission, SubmissionVersion, CourseworkTask
from .coursework_models import WrongAnswerReview
from . import coursework_service as service


def access(user, course_id):
    return Membership.objects.filter(course_id=course_id, user=user, user__is_active=True).first()


def task_data(task, teacher=False):
    try: current = service.valid_basis(task)
    except ValueError: current = False
    return {'id': task.pk, 'kind': task.kind, 'version_id': task.version_id, 'status': task.status,
            'question': task.basis.get('question','') if task.kind=='guidance' else '',
            'item_title': task.basis.get('item', {}).get('title', ''),
            'phase': task.phase, 'revision': task.revision, 'skill_id': task.skill_id,
            'settings_revision': task.settings_revision, 'model': task.model, 'error': task.error,
            'current': current, 'result': task.result if current or teacher else {}, 'events': task.events,
            'retry_of_id': task.retry_of_id, 'created_at': task.created_at, 'finished_at': task.finished_at}


@api_view(['GET', 'POST'])
def settings(request, course_id):
    membership = access(request.user, course_id)
    if not membership: return Response({'error': '课程不存在'}, status=404)
    if request.method == 'POST' and membership.role != 'teacher': return Response({'error': '仅任课教师可配置教学技能'}, status=403)
    if request.method == 'POST':
        data = request.data
        if not isinstance(data, dict) or any(type(data.get(k)) is not bool for k in ['grading_enabled', 'explanation_enabled']) or type(data.get('expected_revision')) is not int:
            return Response({'error': '技能配置格式无效'}, status=400)
        if 'guidance_enabled' in data and type(data['guidance_enabled']) is not bool: return Response({'error':'解题引导开关无效'},status=400)
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course_id)
            if not Membership.objects.filter(course_id=course_id, user=request.user, role='teacher').exists(): return Response({'error': '权限已撤销'}, status=403)
            config = service.settings_for(course_id)
            if config.revision != data['expected_revision']: return Response({'error': '配置已变化，请刷新'}, status=409)
            config.grading_enabled, config.explanation_enabled = data['grading_enabled'], data['explanation_enabled']
            if 'guidance_enabled' in data: config.guidance_enabled=data['guidance_enabled']
            config.revision += 1; config.save()
    config = service.settings_for(course_id)
    return Response({'grading_enabled': config.grading_enabled, 'explanation_enabled': config.explanation_enabled,
                     'guidance_enabled':config.guidance_enabled, 'revision': config.revision})


@api_view(['GET', 'POST'])
def version_tasks(request, version_id):
    version = get_object_or_404(SubmissionVersion.objects.select_related('submission__assignment', 'attachment'), pk=version_id)
    membership = access(request.user, version.submission.assignment.course_id)
    if not membership: return Response({'error': '提交不存在'}, status=404)
    if membership.role != 'teacher' and version.submission.student_id != request.user.pk: return Response({'error': '提交不存在'}, status=404)
    if request.method == 'GET':
        rows = version.ai_tasks.order_by('-id')
        if membership.role != 'teacher': rows = rows.filter(creator=request.user, kind='explanation')
        return Response([task_data(t, membership.role == 'teacher') for t in rows[:30]])
    if not isinstance(request.data, dict): return Response({'error': '请求必须为对象'}, status=400)
    try:
        task = service.enqueue(version, request.user, request.data.get('kind'), request.data.get('request_key'),
            rubric=request.data.get('rubric'), item_id=request.data.get('item_id'), request_id=request.request_id)
    except PermissionError as exc: return Response({'error': str(exc)}, status=403)
    except ValueError as exc: return Response({'error': str(exc)}, status=409)
    return Response(task_data(task), status=202)


@api_view(['GET', 'POST'])
def task_detail(request, task_id):
    task = get_object_or_404(CourseworkTask.objects.select_related('version__submission__assignment'), pk=task_id)
    membership = access(request.user, task.course_id)
    if not membership or (membership.role != 'teacher' and task.creator_id != request.user.pk): return Response({'error': '任务不存在'}, status=404)
    if task.kind=='guidance' and task.creator_id!=request.user.pk: return Response({'error':'任务不存在'},status=404)
    if request.method == 'GET': return Response(task_data(task, membership.role == 'teacher'))
    if not isinstance(request.data, dict): return Response({'error': '请求必须为对象'}, status=400)
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=task.course_id)
        row = CourseworkTask.objects.select_for_update(of=('self',)).select_related('version__submission__assignment').get(pk=task.pk)
        membership = access(request.user, row.course_id)
        if not membership or (membership.role != 'teacher' and row.creator_id != request.user.pk): return Response({'error': '权限已撤销'}, status=403)
        if type(request.data.get('expected_revision')) is not int or row.revision != request.data['expected_revision']: return Response({'error': '任务已变化，请刷新'}, status=409)
        if request.data.get('action') == 'cancel':
            if row.status not in ['queued', 'running']: return Response({'error': '任务已结束'}, status=409)
            service.finish(row, 'cancelled', '用户已取消'); return Response(task_data(row))
        if request.data.get('action') == 'retry':
            if row.status not in ['failed', 'cancelled']: return Response({'error': '仅失败或取消任务可重试'}, status=409)
            # New creator is the actual caller; teachers cannot impersonate students for explanations.
            try:
                if row.kind=='guidance':
                    result=service.enqueue_guidance(row.course_id,request.user,row.basis['question'],request.data.get('request_key',uuid.uuid4().hex),request.request_id,row)
                else:
                    result = service.enqueue(row.version, request.user, row.kind, request.data.get('request_key', uuid.uuid4().hex),
                        rubric=row.basis.get('rubric'), item_id=row.basis.get('item', {}).get('id'), retry_of=row, request_id=request.request_id)
            except PermissionError as exc: return Response({'error': str(exc)}, status=403)
            except ValueError as exc: return Response({'error': str(exc)}, status=409)
            return Response(task_data(result), status=202)
    return Response({'error': '操作应为 cancel 或 retry'}, status=400)


@api_view(['GET','POST'])
def guidance_tasks(request,course_id):
    membership=access(request.user,course_id)
    if not membership:return Response({'error':'课程不存在'},status=404)
    if request.method=='GET':
        return Response([task_data(t) for t in CourseworkTask.objects.filter(course_id=course_id,creator=request.user,kind='guidance').order_by('-id')[:30]])
    if not isinstance(request.data,dict):return Response({'error':'请求须为对象'},status=400)
    try:task=service.enqueue_guidance(course_id,request.user,request.data.get('question'),request.data.get('request_key'),request.request_id)
    except PermissionError as exc:return Response({'error':str(exc)},status=403)
    except ValueError as exc:return Response({'error':str(exc)},status=409)
    return Response(task_data(task),status=202)


@api_view(['GET'])
def wrong_answers(request, course_id):
    membership = access(request.user, course_id)
    if not membership: return Response({'error': '课程不存在'}, status=404)
    if membership.role != 'student': return Response({'error': '个人错题仅供本人学生账号查看'}, status=403)
    try:
        page = int(request.query_params.get('page', '1'))
        if not 1 <= page <= 10000: raise ValueError()
    except (ValueError, TypeError): return Response({'error': '页码无效'}, status=400)
    current = SubmissionVersion.objects.filter(submission_id=OuterRef('submission_id')).order_by('-number').values('pk')[:1]
    rows = (SubmissionVersion.objects.filter(submission__student=request.user, submission__assignment__course_id=course_id,
                published_at__isnull=False, grade_revisions__revision=F('grading_revision'),
                grade_revisions__reviewed_items__0__isnull=False).filter(pk=Subquery(current))
            .select_related('submission__assignment', 'attachment').prefetch_related('files', 'grade_revisions')
            .order_by('-graded_at', '-id'))
    versions = list(rows[(page-1)*20:page*20+1])
    from .assignment_views import version_data
    results = []
    for version in versions[:20]:
        data = version_data(version)
        if any(float(r['score']) < float(r['maximum']) for r in data['grade']['reviewed_items']):
            assignment = version.submission.assignment
            # No roster, classmate data or unpublished grades enter this projection.
            item_ids={str(item['id']) for item in data['grade']['reviewed_items'] if float(item['score']) < float(item['maximum'])}
            reviews=review_projection(WrongAnswerReview.objects.filter(student=request.user,version=version,grade_revision=version.grading_revision,item_id__in=item_ids))
            results.append({'assignment': {'id': assignment.pk, 'course_id': course_id, 'title': assignment.title, 'max_score': str(assignment.max_score)}, 'version': data, 'reviews':reviews})
    return Response({'results': results, 'has_more': len(versions)>20})


def review_projection(rows):
    return {r.item_id:{'status':r.status,'note':r.note,'revision':r.revision,'updated_at':r.updated_at} for r in rows}


@api_view(['GET', 'POST'])
def wrong_answer_reviews(request, version_id):
    initial=get_object_or_404(SubmissionVersion.objects.select_related('submission__assignment'),pk=version_id)
    course_id=initial.submission.assignment.course_id
    membership=access(request.user,course_id)
    if not membership or membership.role!='student' or initial.submission.student_id!=request.user.pk:
        return Response({'error':'错题记录不存在'},status=404)
    if request.method=='POST':
        data=request.data
        if not isinstance(data,dict) or not isinstance(data.get('item_id'),str) or not 1<=len(data['item_id'])<=120 or not isinstance(data.get('status'),str) or data['status'] not in dict(WrongAnswerReview.STATUS_CHOICES) or type(data.get('expected_revision')) is not int or type(data.get('grade_revision')) is not int:
            return Response({'error':'错题复习状态格式无效'},status=400)
        if not isinstance(data.get('note',''),str) or len(data.get('note',''))>500:
            return Response({'error':'复习备注最多500字'},status=400)
    with transaction.atomic():
        # Same lock ordering as grading/publication/submission to recheck current evidence.
        Course.objects.select_for_update().get(pk=course_id)
        membership=access(request.user,course_id)
        if not membership or membership.role!='student':return Response({'error':'课程权限已变化'},status=404)
        Submission.objects.select_for_update().get(pk=initial.submission_id)
        version=SubmissionVersion.objects.select_for_update().get(pk=version_id)
        latest=SubmissionVersion.objects.filter(submission_id=version.submission_id).order_by('-number').values_list('pk',flat=True).first()
        formal=version.grade_revisions.filter(revision=version.grading_revision,published=True).first() if version.published_at and latest==version.pk else None
        items={str(i['id']) for i in formal.reviewed_items if Decimal(i['score'])<Decimal(i['maximum'])} if formal else set()
        rows=WrongAnswerReview.objects.filter(student=request.user,version=version,grade_revision=version.grading_revision,item_id__in=items)
        if request.method=='GET':return Response(review_projection(rows))
        if data['item_id'] not in items or data['grade_revision']!=version.grading_revision:
            return Response({'error':'评分依据已变化，请刷新错题'},status=409)
        row=rows.filter(item_id=data['item_id']).first()
        if data['expected_revision']!=(row.revision if row else 0):return Response({'error':'复习记录已变化，请刷新'},status=409)
        if row is None:row=WrongAnswerReview(version=version,student=request.user,item_id=data['item_id'],grade_revision=version.grading_revision)
        row.status=data['status'];row.note=data.get('note','');row.revision+=1;row.save()
        return Response({'item_id':row.item_id,**review_projection([row])[row.item_id]})
