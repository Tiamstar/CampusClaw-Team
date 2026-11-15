from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Membership
from .skill_monitor import dashboard


@api_view(['GET'])
def skill_monitor(request,course_id):
    membership=Membership.objects.filter(course_id=course_id,user=request.user).first()
    if not membership:return Response({'error':'课程不存在'},status=404)
    if membership.role!='teacher':return Response({'error':'仅任课教师可查看运维统计'},status=403)
    try:
        hours=int(request.query_params.get('hours','24'))
        if hours not in [1,6,24,168]:raise ValueError()
    except (ValueError,TypeError):return Response({'error':'时间范围仅支持1、6、24或168小时'},status=400)
    return Response(dashboard(course_id,hours))
