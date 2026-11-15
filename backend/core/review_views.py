from datetime import datetime,timedelta,timezone as dt_timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from .forum_views import api_view,access,page
from .views import fail
from .models import Course,ReviewPlan,ReviewReminder
from .review_service import basis_for,current_basis,ordered_steps
from .gradebook_views import audit


def owned(request,plan_id):
    plan=get_object_or_404(ReviewPlan,pk=plan_id)
    access(request.user,plan.course_id)
    if plan.owner_id!=request.user.id:raise PermissionDenied('仅能管理本人的复习计划')
    return plan


def stale(plan):
    try:return current_basis(plan)['fingerprint']!=plan.basis['fingerprint']
    except ValueError:return True


def plan_data(plan):
    changed=stale(plan)
    # A withdrawn grade or resource must not remain readable through a frozen plan.
    steps=plan.steps if not changed else []
    return {'id':plan.id,'status':plan.status,'revision':plan.revision,'steps':steps,
            'selected_ids':plan.selected_ids,'schedule':plan.schedule,'model':plan.model,'skill':plan.skill,
            'error':plan.error,'stale':changed,'basis_version':plan.basis['fingerprint'],
            'window':plan.basis['learning']['window'],'created_at':plan.created_at,
            'confirmed_at':plan.confirmed_at,'cancelled_at':plan.cancelled_at,
            'reminders':[{'id':r.id,'point_id':r.point_id,'due_at':r.due_at,'offset_days':r.offset_days,
                'schedule_revision':r.schedule_revision,'state':r.state,'completed_at':r.completed_at,
                'due':r.state=='scheduled' and r.due_at<=timezone.now() and plan.status=='active' and not changed,
                'actionable':r.state=='scheduled' and plan.status=='active' and not changed}
                for r in plan.reminders.order_by('-schedule_revision','due_at','id')[:500]]}


@api_view(['GET','POST'])
def plans(request,course_id):
    member=access(request.user,course_id)
    if member.role!='student':return fail('复习路径为学生个人功能',403)
    if request.method=='GET':
        offset,number=page(request)
        rows=list(ReviewPlan.objects.filter(course_id=course_id,owner=request.user).prefetch_related('reminders').order_by('-id')[offset:offset+21])
        return Response({'items':[plan_data(p) for p in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
    if set(request.data)-{'start','end'}:return fail('路径参数只支持分析时间窗口')
    try:
        end=parse_datetime(request.data['end']) if 'end' in request.data else timezone.now()
        start=parse_datetime(request.data['start']) if 'start' in request.data else end-timedelta(days=90)
        if not start or not end or timezone.is_naive(start) or timezone.is_naive(end) or not timedelta(0)<end-start<=timedelta(days=366):raise ValueError('路径分析时间须带时区、窗口大于零且不超过366天')
        start,end=start.astimezone(dt_timezone.utc),end.astimezone(dt_timezone.utc)
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course_id)
            if ReviewPlan.objects.filter(course_id=course_id,owner=request.user,status__in=['queued','running']).exists():return fail('已有路径任务排队或执行中',409)
            basis=basis_for(course_id,request.user.id,start,end)
            if not ordered_steps(basis):return fail('请教师先建立可用知识点')
            plan=ReviewPlan.objects.create(course_id=course_id,owner=request.user,basis=basis)
            audit(request,course_id,'review.queue',plan.id)
    except (ValueError,TypeError,OverflowError) as e:return fail(str(e) or '时间格式无效')
    return Response(plan_data(plan),status=201)


@api_view(['GET'])
def detail(request,plan_id):
    return Response(plan_data(owned(request,plan_id)))


def validate_schedule(data,plan):
    ids=data.get('point_ids');schedule=data.get('schedule')
    if not isinstance(ids,list) or not ids or len(ids)>30 or any(type(i) is not int for i in ids) or len(set(ids))!=len(ids):raise ValueError('请勾选不重复的复习步骤')
    by_id={s['point_id']:s for s in plan.steps}
    if any(i not in by_id for i in ids):raise ValueError('步骤不属于此路径')
    if any(p not in ids for i in ids for p in by_id[i]['prerequisite_ids']):raise ValueError('必须同时保留所选步骤的先修知识')
    if not isinstance(schedule,dict) or set(schedule)!={'timezone','start_date','local_time','offset_days'}:raise ValueError('提醒设置无效')
    try:zone=ZoneInfo(schedule['timezone']);date=datetime.strptime(schedule['start_date'],'%Y-%m-%d').date();clock=datetime.strptime(schedule['local_time'],'%H:%M').time()
    except (ValueError,TypeError,ZoneInfoNotFoundError):raise ValueError('时区、日期或提醒时刻无效')
    offsets=schedule['offset_days']
    if not isinstance(offsets,list) or not 1<=len(offsets)<=8 or any(type(i) is not int or not 0<=i<=365 for i in offsets) or offsets!=sorted(set(offsets)):raise ValueError('间隔须为递增、不重复的0–365天，最多8次')
    if date<timezone.now().astimezone(zone).date() or date>timezone.now().astimezone(zone).date()+timedelta(days=365):raise ValueError('开始日期须在今天至一年内')
    times=[]
    for offset in offsets:
        naive=datetime.combine(date+timedelta(days=offset),clock)
        local=naive.replace(tzinfo=zone,fold=0)
        # Refuse DST gaps and ambiguous times instead of silently shifting a reminder.
        if local.astimezone(dt_timezone.utc).astimezone(zone).replace(tzinfo=None)!=naive or local.utcoffset()!=naive.replace(tzinfo=zone,fold=1).utcoffset():raise ValueError('提醒时间遇夏令时跳变或重复，请选择其他时刻')
        due=local.astimezone(dt_timezone.utc)
        if due<=timezone.now():raise ValueError('提醒时间必须晚于当前时间')
        times.append((offset,due))
    ordered=[s['point_id'] for s in plan.steps if s['point_id'] in ids]
    return ordered,schedule,times


@api_view(['POST'])
def action(request,plan_id):
    initial=owned(request,plan_id);command=request.data.get('action')
    if command not in {'confirm','reschedule','cancel'}:return fail('计划操作无效')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=initial.course_id)
        plan=ReviewPlan.objects.select_for_update().get(pk=plan_id)
        access(request.user,plan.course_id)
        if type(request.data.get('expected_revision')) is not int or request.data['expected_revision']!=plan.revision:return fail('计划已变化，请刷新',409)
        if command=='cancel':
            if plan.status!='cancelled':
                plan.status='cancelled';plan.cancelled_at=timezone.now();plan.revision+=1;plan.save()
                plan.reminders.filter(state='scheduled').update(state='cancelled')
        else:
            if plan.status!=('awaiting_confirmation' if command=='confirm' else 'active'):return fail('计划状态不允许确认或调整',409)
            if stale(plan):return fail('评分、图谱或资源已变化，请重新生成路径',409)
            try:ids,schedule,times=validate_schedule(request.data,plan)
            except ValueError as e:return fail(str(e))
            plan.reminders.filter(state='scheduled').update(state='cancelled')
            plan.revision+=1;plan.status='active';plan.selected_ids=ids;plan.schedule=schedule
            plan.confirmed_at=plan.confirmed_at or timezone.now();plan.save()
            ReviewReminder.objects.bulk_create([ReviewReminder(plan=plan,schedule_revision=plan.revision,point_id=pid,offset_days=offset,due_at=due) for pid in ids for offset,due in times])
        audit(request,plan.course_id,'review.'+command,plan.id)
    return Response(plan_data(plan))


@api_view(['POST'])
def reminder(request,reminder_id):
    original=get_object_or_404(ReviewReminder,pk=reminder_id);initial=owned(request,original.plan_id)
    command=request.data.get('action')
    if command not in {'complete','cancel'}:return fail('提醒操作无效')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=initial.course_id)
        plan=ReviewPlan.objects.select_for_update().get(pk=initial.id)
        access(request.user,plan.course_id)
        item=ReviewReminder.objects.select_for_update().get(pk=reminder_id)
        if plan.status!='active':return fail('计划未启用或已取消',409)
        if command=='complete' and stale(plan):return fail('学习依据已变化，请重新核对路径',409)
        desired='completed' if command=='complete' else 'cancelled'
        if item.state not in {'scheduled',desired}:return fail('提醒状态已变化',409)
        if item.state=='scheduled':
            item.state=desired;item.completed_at=timezone.now() if desired=='completed' else None;item.save()
        audit(request,plan.course_id,'review.reminder.'+command,item.id)
    return Response({'id':item.id,'state':item.state,'completed_at':item.completed_at})
