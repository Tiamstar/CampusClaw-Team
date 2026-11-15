"""One-use authorizations; never hold a DB transaction over an external RPC."""
import hashlib
import json
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .audit import record_audit
from .models import ToolConfirmation


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def fingerprint(spec,arguments):
    raw=encoded({'tool':spec.name,'version':spec.version,'schema':spec.input_schema,
                 'binding':spec.confirmation_binding,'arguments':arguments})
    if len(raw.encode())>65536: raise ValueError('待确认参数最多64KiB，请缩小调用')
    return hashlib.sha256(raw.encode()).hexdigest()


def audit(row,context,action,status):
    record_audit(actor_id=context.user.pk,course_id=row.course_id,action=action,
        object_ref=str(row.pk),status=status,request_id=context.request_id)


def data(row):
    status='expired' if row.status=='pending' and row.expires_at<=timezone.now() else row.status
    return {'id':str(row.pk),'tool_name':row.tool_name,'arguments':row.arguments,'status':status,
        'expires_at':row.expires_at.isoformat(),'created_at':row.created_at.isoformat(),
        'result':row.result,'error':row.error,
        'uncertain':bool(row.status=='executing' and row.started_at and row.started_at<timezone.now()-timedelta(minutes=2))}


def authorize(spec,arguments,context):
    from .skill_runtime import assert_runtime_current,current_mcp_binding
    if not context.thread: raise PermissionError('确认需要当前对话')
    if spec.confirmation_binding:current_mcp_binding(spec.confirmation_binding)
    digest=fingerprint(spec,arguments)
    if not context.confirmation_id:
        # Bound duplicate model calls to the same still-pending action.
        row=ToolConfirmation.objects.filter(owner=context.user,thread=context.thread,fingerprint=digest,
            config_revision=context.config_revision,status='pending',expires_at__gt=timezone.now()).order_by('-created_at').first()
        if row is None:
            row=ToolConfirmation.objects.create(owner=context.user,thread=context.thread,course_id=context.thread.course_id,
                tool_name=spec.name,arguments=arguments,fingerprint=digest,config_revision=context.config_revision,
                expires_at=timezone.now()+timedelta(minutes=5))
            audit(row,context,'tool.confirmation.requested','pending')
        return {'confirmation_required':True,'confirmation_id':str(row.pk),'message':'等待用户核对工具和完整参数后确认；尚未执行。'}
    with transaction.atomic():
        row=ToolConfirmation.objects.select_for_update().filter(pk=context.confirmation_id,owner=context.user,
            thread=context.thread,course_id=context.thread.course_id).first()
        if row is None: raise PermissionError('确认不存在或不属于当前对话')
        assert_runtime_current(context.user,context.thread,context.config_revision)
        if row.status!='pending' or row.expires_at<=timezone.now():
            audit(row,context,'tool.confirmation.denied','409')
            raise PermissionError('确认已使用、过期或取消；禁止重放')
        if row.fingerprint!=digest or row.config_revision!=context.config_revision:
            audit(row,context,'tool.confirmation.denied','409')
            raise PermissionError('工具、参数或配置已变化，请重新发起')
        row.status='executing';row.started_at=timezone.now();row.save(update_fields=['status','started_at'])
        audit(row,context,'tool.confirmation.consumed','ok')
    return None


def finish(row,result=None,error=''):
    # Execution is never replayed, even after an RPC timeout or an ambiguous transport failure.
    ToolConfirmation.objects.filter(pk=row.pk,status='executing').update(status='failed' if error else 'succeeded',
        result=result or {},error=error[:500],finished_at=timezone.now())
