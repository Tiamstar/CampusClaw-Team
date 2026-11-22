import uuid
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Course, Material, MaterialIndexTask, Membership
from .index_service import enqueue, task_data, transition, IndexConflict


def task_access(user, task_id):
    task = get_object_or_404(MaterialIndexTask.objects.select_related('material__attachment'), pk=task_id)
    membership = Membership.objects.filter(course_id=task.course_id, user=user).first()
    if not membership:
        return None, Response({'error': '任务不存在'}, status=404)
    if membership.role != 'teacher':
        return None, Response({'error': '仅任课教师可查看或管理索引任务'}, status=403)
    return task, None


@api_view(['GET', 'POST'])
def task_detail(request, task_id):
    task, error = task_access(request.user, task_id)
    if error is not None:
        return error
    if request.method == 'GET':
        return Response(task_data(task))
    data = request.data
    if not isinstance(data, dict):
        return Response({'error': '请求必须为 JSON 对象'}, status=400)
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=task.course_id)
        task = MaterialIndexTask.objects.select_for_update().select_related('material__attachment').get(pk=task_id)
        if not Membership.objects.filter(course_id=task.course_id, user=request.user, role='teacher').exists():
            return Response({'error': '任课教师权限已撤销'}, status=403)
        if type(data.get('expected_revision')) is not int or data['expected_revision'] != task.revision:
            return Response({'error': '任务状态已变化，请刷新后重试'}, status=409)
        action = data.get('action')
        if action == 'cancel':
            if task.status not in ('queued', 'running'):
                return Response({'error': '任务已结束'}, status=409)
            transition(task, 'cancelled', error_code='cancelled', error='教师已取消索引，可重新排队')
            return Response(task_data(task))
        if action == 'retry':
            if task.status not in ('failed', 'cancelled'):
                return Response({'error': '仅失败或取消任务可重试'}, status=409)
            try:
                retried = enqueue(task.material, request.user, request_key=data.get('request_key', uuid.uuid4().hex),
                                  request_id=request.request_id, retry_of=task)
            except PermissionError as exc:
                return Response({'error': str(exc)}, status=403)
            except IndexConflict as exc:
                return Response({'error': str(exc)}, status=409)
            except ValueError as exc:
                return Response({'error': str(exc)}, status=400)
            return Response(task_data(retried), status=202)
        return Response({'error': '操作应为 cancel 或 retry'}, status=400)


@api_view(['GET'])
def task_history(request, material_id):
    material = get_object_or_404(Material, pk=material_id)
    membership = Membership.objects.filter(course_id=material.course_id, user=request.user).first()
    if not membership:
        return Response({'error': '资料不存在'}, status=404)
    if membership.role != 'teacher':
        return Response({'error': '仅任课教师可查看索引历史'}, status=403)
    try:
        page = int(request.query_params.get('page', '1'))
        if not 1 <= page <= 10000:
            raise ValueError
    except (ValueError, TypeError):
        return Response({'error': '页码无效'}, status=400)
    rows = list(material.index_tasks.order_by('-id')[(page - 1) * 20:page * 20 + 1])
    return Response({'results': [task_data(t) for t in rows[:20]], 'has_more': len(rows) > 20})
