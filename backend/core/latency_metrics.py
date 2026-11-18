"""Bounded DB aggregates. Percentiles are computed from raw observations, never from other P95s."""
from django.db.models import Avg, Count, DateTimeField, ExpressionWrapper, F, FloatField, Func, Q
from django.db.models.functions import Extract, TruncHour
from .models import RequestMetric, ModelCall, CourseworkTask
from .coursework_service import SKILLS
from .skill_monitor import P95


class FiveMinuteBucket(Func):
    template = "DATE_BIN(INTERVAL '5 minutes', %(expressions)s, TIMESTAMPTZ '2000-01-01 00:00:00+00')"
    output_field = DateTimeField()


def milliseconds(end, start):
    return ExpressionWrapper(Extract(F(end)-F(start), 'epoch')*1000, output_field=FloatField())


def http_dashboard(course_id, start, end, hours):
    metrics = RequestMetric.objects.filter(course_id=course_id, finished_at__gte=start, finished_at__lte=end)
    complete = Q(outcome='completed')
    rows = list(metrics.values('route', 'method', 'streaming').annotate(
        requests=Count('id'), completed=Count('id', filter=complete),
        closed=Count('id', filter=Q(outcome='closed')), transport_errors=Count('id', filter=Q(outcome='error')),
        client_errors=Count('id', filter=Q(status_code__gte=400, status_code__lt=500)),
        server_errors=Count('id', filter=Q(status_code__gte=500)),
        avg_ms=Avg('duration_ms', filter=complete), p95_ms=P95('duration_ms', filter=complete)
    ).order_by('-requests', 'route', 'method', 'streaming')[:51])
    selected = rows[:50]
    predicate = Q(pk__in=[])
    for row in selected: predicate |= Q(route=row['route'], method=row['method'], streaming=row['streaming'])
    truncate = TruncHour if hours>6 else FiveMinuteBucket
    curves = list(metrics.filter(predicate).annotate(time=truncate('finished_at')).values('route','method','streaming','time').annotate(
        requests=Count('id'), samples=Count('id', filter=complete),
        avg_ms=Avg('duration_ms', filter=complete), p95_ms=P95('duration_ms', filter=complete)
    ).order_by('time','route','method','streaming'))
    return {'routes': selected, 'curve': curves, 'routes_truncated': len(rows)>50,
        'interval': 'hour' if hours>6 else 'five_minutes',
        'note': 'HTTP计时从请求进入到响应内容消费结束；流式含模型等待和传输，非首字延迟。关闭/传输异常单列且不进入耗时分位数。HTTP 200不保证业务或模型成功。仅按服务器URL资源归属课程；无资源标识的集合/平台接口不分摊到课程。旧审计耗时不混入、不回填。'}


def skill_duration_curves(course_id, start, end, hours):
    truncate = TruncHour if hours>6 else FiveMinuteBucket
    calls = ModelCall.objects.filter(course_id=course_id, skill_id__in=SKILLS.values(),
        finished_at__gte=start, finished_at__lte=end, duration_ms__isnull=False).exclude(provider='mock')
    models = list(calls.annotate(time=truncate('finished_at')).values('skill_id','time').annotate(
        samples=Count('id'), avg_ms=Avg('duration_ms'), p95_ms=P95('duration_ms')).order_by('time','skill_id'))
    jobs = CourseworkTask.objects.filter(
        course_id=course_id, skill_id__in=SKILLS.values(), finished_at__gte=start, finished_at__lte=end,
        ).filter(finished_at__gte=F('created_at'))
    jobs = jobs.annotate(time=truncate('finished_at'), total_ms=milliseconds('finished_at','created_at'),
        processing_ms=milliseconds('finished_at','started_at'), wait_ms=milliseconds('started_at','created_at'))
    valid_start = Q(started_at__isnull=False, started_at__gte=F('created_at'), started_at__lte=F('finished_at'))
    tasks = list(jobs.values('skill_id','time').annotate(
        samples=Count('id'), avg_ms=Avg('total_ms'), p95_ms=P95('total_ms'),
        processing_samples=Count('id', filter=valid_start),
        processing_avg_ms=Avg('processing_ms', filter=valid_start), processing_p95_ms=P95('processing_ms', filter=valid_start),
        queue_avg_ms=Avg('wait_ms', filter=valid_start), queue_p95_ms=P95('wait_ms', filter=valid_start)
    ).order_by('time','skill_id'))
    return {'model': models, 'task': tasks, 'interval': 'hour' if hours>6 else 'five_minutes',
        'note': '按结束时间分桶，从原始样本计算平均/P95，不平均各桶P95。模型排除mock；任务总耗时截止后台产出、失败或取消，包含排队、检索和输出校验，不含教师后续复核；也包含演示及失败/取消。处理/排队耗时仅统计有本轮新增领取时间的有效记录，旧任务未知不补零。空桶不补样本，非容量验收结论。'}
