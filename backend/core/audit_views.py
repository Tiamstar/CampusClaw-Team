"""Bounded, metadata-only course audit access for current course teachers."""
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import AuditEvent, Membership


@api_view(['GET'])
def events(request, course_id):
    membership = Membership.objects.filter(course_id=course_id, user=request.user).first()
    if not membership:
        return Response({'error': '课程不存在'}, status=404)
    if membership.role != 'teacher':
        return Response({'error': '仅任课教师可查看审计'}, status=403)
    try:
        limit = int(request.query_params.get('limit', '50'))
        before = int(request.query_params.get('before', str(2**63-1)))
        if not 1 <= limit <= 100 or not 1 <= before <= 2**63-1:
            raise ValueError()
    except (ValueError, TypeError):
        return Response({'error': '分页参数无效'}, status=400)
    rows = list(AuditEvent.objects.filter(course_id=course_id, id__lt=before).order_by('-id').values(
        'id', 'created_at', 'actor_id', 'course_id', 'action', 'object_ref', 'status',
        'request_id', 'skill_id', 'duration_ms', 'tokens')[:limit+1])
    return Response({'results': rows[:limit], 'next_before': rows[limit-1]['id'] if len(rows)>limit else None})
