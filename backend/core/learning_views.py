from datetime import timedelta, timezone as dt_timezone
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound
from .forum_views import api_view, access
from .models import Membership
from .views import fail
from .learning_service import learning_data


def authorized_learning(user, course_id, params):
    membership = access(user, course_id)
    teacher = membership.role == 'teacher'
    try:
        allowed = {'start', 'end', 'student_id', 'include_unpublished'}
        if set(params) - allowed:
            raise ValueError('未知分析参数')
        end = parse_datetime(params['end']) if 'end' in params else timezone.now()
        start = parse_datetime(params['start']) if 'start' in params else end - timedelta(days=90)
        if start is None or end is None or timezone.is_naive(start) or timezone.is_naive(end):
            raise ValueError('分析时间须带时区')
        start, end = start.astimezone(dt_timezone.utc), end.astimezone(dt_timezone.utc)
        if not timedelta(0) < end - start <= timedelta(days=366):
            raise ValueError('分析窗口须大于零且不超过 366 天')
        raw = params.get('include_unpublished', 'false')
        if raw not in {'true', 'false'}:
            raise ValueError('未公开选项须为 true/false')
        unpublished = raw == 'true'
        if unpublished and not teacher:
            raise PermissionDenied('学生不能查询未公开评分')
        sid = int(params['student_id']) if 'student_id' in params else None
        if not teacher:
            if sid is not None and sid != user.id:
                raise PermissionDenied('仅能查询本人学情')
            sid = user.id
        if sid is not None and not Membership.objects.filter(course_id=course_id, user_id=sid, role='student').exists():
            raise NotFound('无可见的学生学情')
    except (ValueError, TypeError, OverflowError) as e:
        raise ValueError(str(e) or '分析参数无效') from e
    return learning_data(course_id, start, end, sid, unpublished)


@api_view(['GET'])
def analytics(request, course_id):
    try:
        return Response(authorized_learning(request.user, course_id, request.GET))
    except ValueError as e:
        return fail(str(e))
