"""Teacher-only aggregate operations data; no student questions, answers or model text."""
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Aggregate, Count, Avg, Sum, Min, Q, FloatField
from django.db.models.functions import TruncHour
from django.utils import timezone
from .models import (Course, CourseworkTask, ModelCall, SkillMetricSample, SkillAlert,
                     SkillAlertEvent, SkillMonitorHeartbeat)
from .coursework_service import SKILLS


class P95(Aggregate):
    function='PERCENTILE_CONT'
    template='PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY %(expressions)s)'
    output_field=FloatField()


RULES={'failure_rate':{'threshold':.2,'minimum':5,'window_minutes':15},
       'model_p95_ms':{'threshold':15000,'minimum':5,'window_minutes':15},
       'queue_age_seconds':{'threshold':60,'minimum':1,'window_minutes':15}}


def alert_policy():
    values = {'for_seconds':settings.SKILL_ALERT_FOR_SECONDS,
              'recovery_seconds':settings.SKILL_ALERT_RECOVERY_SECONDS,
              'max_gap_seconds':settings.SKILL_ALERT_MAX_GAP_SECONDS}
    if any(type(v) is not int or not 0 <= v <= 86400 for v in values.values()) or values['max_gap_seconds'] < 30:
        raise ValueError('Invalid skill alert duration policy')
    return values


def observe_alert(alert, observation, value, size, definition, now, policy):
    """Unknown samples never prove recovery; evaluator lock protects transitions."""
    if now < alert.evaluated_at:return False
    key = ':'.join(str(v) for v in [definition['threshold'], definition['minimum'], definition['window_minutes'], *policy.values()])
    if alert.policy_key != key or (now-alert.evaluated_at).total_seconds() > policy['max_gap_seconds']:
        alert.pending_since = None
    alert.policy_key = key
    alert.observation = observation
    alert.threshold = definition['threshold']
    alert.sample_size = size
    if value is not None:alert.value = value
    alert.evaluated_at = now
    changed = False
    if observation == 'unknown' or (observation == 'breaching') == alert.firing:
        alert.pending_since = None
    else:
        alert.pending_since = alert.pending_since or now
        duration = policy['recovery_seconds'] if alert.firing else policy['for_seconds']
        if (now-alert.pending_since).total_seconds() >= duration:
            alert.firing = not alert.firing
            alert.pending_since = None
            alert.changed_at = now
            changed = True
    alert.save()
    return changed


def summary(course_id, start, now=None):
    now=now or timezone.now()
    calls={r['skill_id']:r for r in ModelCall.objects.filter(course_id=course_id,started_at__gte=start,skill_id__in=SKILLS.values()).values('skill_id').annotate(
        calls=Count('id'),succeeded=Count('id',filter=Q(status='succeeded')),failed=Count('id',filter=Q(status__in=['failed','cancelled','interrupted'])),
        inflight=Count('id',filter=Q(status='running')),mock=Count('id',filter=Q(provider='mock')),
        usage_complete=Count('id',filter=Q(usage_state='complete')),usage_partial=Count('id',filter=Q(usage_state='partial')),
        usage_missing=Count('id',filter=Q(usage_state='missing')),usage_invalid=Count('id',filter=Q(usage_state='invalid')),
        input_tokens=Sum('input_tokens',filter=Q(usage_state='complete')),output_tokens=Sum('output_tokens',filter=Q(usage_state='complete')),
        partial_tokens=Sum('total_tokens',filter=Q(usage_state='partial')),total_tokens=Sum('total_tokens',filter=Q(usage_state='complete')),
        latency_samples=Count('id',filter=Q(duration_ms__isnull=False)&~Q(provider='mock')),
        avg_ms=Avg('duration_ms',filter=~Q(provider='mock')),p95_ms=P95('duration_ms',filter=~Q(provider='mock')))}
    jobs={r['skill_id']:r for r in CourseworkTask.objects.filter(course_id=course_id,finished_at__gte=start).values('skill_id').annotate(
        finished_tasks=Count('id'),failed_tasks=Count('id',filter=Q(status='failed')),cancelled_tasks=Count('id',filter=Q(status='cancelled')))}
    queues={r['skill_id']:r for r in CourseworkTask.objects.filter(course_id=course_id,status__in=['queued','running']).values('skill_id').annotate(
        queued=Count('id',filter=Q(status='queued')),running=Count('id',filter=Q(status='running')),oldest=Min('created_at',filter=Q(status='queued')))}
    result=[]
    for kind,skill in SKILLS.items():
        row={'kind':kind,'skill_id':skill,**calls.get(skill,{}),**jobs.get(skill,{}),**queues.get(skill,{})}
        for key in ['latency_samples','calls','succeeded','failed','inflight','mock','usage_complete','usage_partial','usage_missing','usage_invalid','finished_tasks','failed_tasks','cancelled_tasks','queued','running']:
            row.setdefault(key,0)
        for key in ['input_tokens','output_tokens','total_tokens','partial_tokens','avg_ms','p95_ms']: row.setdefault(key,None)
        row['oldest_queue_seconds']=max(0,(now-row.pop('oldest')).total_seconds()) if row.get('oldest') else 0
        row.pop('oldest',None)
        real=row['calls']-row['mock'];row['usage_coverage']=row['usage_complete']/real if real else None
        # Explicit cancellation is not a skill failure, and has its own counter.
        denominator=row['finished_tasks']-row['cancelled_tasks']
        row['failure_rate']=row['failed_tasks']/denominator if denominator else None
        result.append(row)
    return result


def evaluate(now=None):
    now=now or timezone.now();bucket=now.replace(second=0,microsecond=0)
    policy=alert_policy()
    # A dedicated evaluator serializes with a row lock, avoiding duplicate transitions across replicas.
    with transaction.atomic():
        heartbeat,_=SkillMonitorHeartbeat.objects.get_or_create(name='skills',defaults={'evaluated_at':now})
        heartbeat=SkillMonitorHeartbeat.objects.select_for_update().get(pk=heartbeat.pk)
        if now < heartbeat.evaluated_at:return
        ModelCall.objects.filter(status='running',started_at__lt=now-timedelta(minutes=10)).update(
            status='interrupted',error_code='worker_interrupted',finished_at=now,usage_state='missing')
        course_ids=set(CourseworkTask.objects.values_list('course_id',flat=True))|set(SkillAlert.objects.values_list('course_id',flat=True))
        for course_id in sorted(course_ids):
            for row in summary(course_id,now-timedelta(minutes=15),now):
                SkillMetricSample.objects.update_or_create(course_id=course_id,skill_id=row['skill_id'],bucket=bucket,
                    defaults={'queued':row['queued'],'running':row['running']})
                for rule,definition in RULES.items():
                    value={'failure_rate':row['failure_rate'],'model_p95_ms':row['p95_ms'],'queue_age_seconds':row['oldest_queue_seconds']}[rule]
                    size={'failure_rate':row['finished_tasks']-row['cancelled_tasks'],'model_p95_ms':row['latency_samples'],'queue_age_seconds':row['queued']}[rule]
                    known=value is not None and (size>=definition['minimum'] or rule=='queue_age_seconds' and size==0)
                    observation='unknown' if not known else 'breaching' if value>definition['threshold'] else 'normal'
                    alert=SkillAlert.objects.filter(course_id=course_id,skill_id=row['skill_id'],rule=rule).first()
                    # Quiet rules don't create a history of invented incidents.
                    if alert is None and observation!='breaching': continue
                    if alert is None:
                        alert=SkillAlert(course_id=course_id,skill_id=row['skill_id'],rule=rule,firing=False,
                            value=value or 0,threshold=definition['threshold'],sample_size=size,changed_at=now,evaluated_at=now)
                    changed=observe_alert(alert,observation,value,size,definition,now,policy)
                    if changed: SkillAlertEvent.objects.create(alert=alert,firing=alert.firing,value=alert.value,sample_size=size,created_at=now)
        heartbeat.evaluated_at=now;heartbeat.save()


def dashboard(course_id,hours=24):
    from .latency_metrics import http_dashboard, skill_duration_curves
    now=timezone.now();start=now-timedelta(hours=hours)
    samples=SkillMetricSample.objects.filter(course_id=course_id,bucket__gte=start)
    if hours>6:
        curve=list(samples.annotate(time=TruncHour('bucket')).values('skill_id','time').annotate(queued=Avg('queued'),running=Avg('running')).order_by('time','skill_id'))
    else:
        curve=[{'time':s['bucket'],'skill_id':s['skill_id'],'queued':s['queued'],'running':s['running']} for s in samples.values('bucket','skill_id','queued','running').order_by('bucket','skill_id')]
    heartbeat=SkillMonitorHeartbeat.objects.filter(name='skills').first()
    alerts=list(SkillAlert.objects.filter(course_id=course_id).values('id','skill_id','rule','firing','value','threshold','sample_size','changed_at','evaluated_at','pending_since','observation'))
    triggered=set(SkillAlertEvent.objects.filter(alert__course_id=course_id,firing=True).values_list('alert_id',flat=True))
    for alert in alerts:alert['has_fired']=alert['firing'] or alert['id'] in triggered
    events=list(SkillAlertEvent.objects.filter(alert__course_id=course_id,created_at__gte=start).order_by('-id').values('id','alert__skill_id','alert__rule','firing','value','sample_size','created_at')[:50])
    return {'window':{'start':start,'end':now,'hours':hours},'skills':summary(course_id,start),'queue_curve':curve,
            'http_latency':http_dashboard(course_id,start,now,hours),
            'duration_curves':skill_duration_curves(course_id,start,now,hours),
            'curve_interval':'hour_average' if hours>6 else 'minute_sample','rules':RULES,'alert_policy':alert_policy(),'alerts':alerts,'events':events,
            'monitor_evaluated_at':heartbeat.evaluated_at if heartbeat else None,
            'monitor_stale':not heartbeat or heartbeat.evaluated_at<now-timedelta(seconds=120),
            'usage_note':'仅累计网关完整上报的LLM用量；未上报、无效和部分上报不当作零，不含嵌入调用，不估算费用。队列曲线为后台采样，不回填历史。'}
