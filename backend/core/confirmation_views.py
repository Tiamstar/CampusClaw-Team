import asyncio
from asgiref.sync import async_to_sync
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from .agent_views import agent_auth_required,_accessible_thread,_json
from .agent_runtime import builtin_tool_registry,ToolContext,model_tools
from .skill_runtime import runtime_config,configure_registry,assert_runtime_current
from .models import ToolConfirmation,AgentMessage
from . import tool_confirmation as service


@agent_auth_required
def confirmations(request,thread_id):
    if request.method!='GET': return JsonResponse({'error':'仅支持读取'},status=405)
    thread=_accessible_thread(request.user,thread_id)
    if not thread: return JsonResponse({'error':'对话不存在'},status=404)
    rows=ToolConfirmation.objects.filter(thread=thread,owner=request.user).order_by('-created_at')[:30]
    return JsonResponse([service.data(row) for row in rows],safe=False)


@agent_auth_required
def action(request,thread_id,confirmation_id):
    if request.method!='POST': return JsonResponse({'error':'仅支持POST'},status=405)
    thread=_accessible_thread(request.user,thread_id)
    if not thread: return JsonResponse({'error':'对话不存在'},status=404)
    row=ToolConfirmation.objects.filter(pk=confirmation_id,thread=thread,owner=request.user).first()
    if not row: return JsonResponse({'error':'确认不存在'},status=404)
    payload=_json(request)
    if set(payload)!={'action'} or payload.get('action') not in ['confirm','reject']:
        return JsonResponse({'error':'仅接受confirm或reject，不接受覆盖参数'},status=400)
    config,app,selected,mcp,unavailable=runtime_config(request.user,thread.course_id)
    context=ToolContext(request.user,thread,frozenset({'artifact.create','skill.read','course.read','mcp.call'}),
        request.request_id,config.revision if config else None,str(row.pk))
    if payload['action']=='reject':
        with transaction.atomic():
            row=ToolConfirmation.objects.select_for_update().get(pk=row.pk)
            if row.status!='pending':return JsonResponse({'error':'确认已处理'},status=409)
            row.status='rejected';row.finished_at=timezone.now();row.save(update_fields=['status','finished_at'])
            service.audit(row,context,'tool.confirmation.rejected','ok')
        return JsonResponse(service.data(row))
    registry=builtin_tool_registry();configure_registry(registry,selected,mcp)
    try:
        assert_runtime_current(request.user,thread,row.config_revision)
        if row.status!='pending' or row.expires_at<=timezone.now(): raise PermissionError('确认已使用、过期或取消')
        candidates={t['function']['name'] for t in model_tools(registry,context.permissions)}
        if row.tool_name not in candidates: raise PermissionError('工具不再绑定，不能执行旧确认')
        if not registry.get(row.tool_name)[0].requires_confirmation: raise PermissionError('确认策略已变化')
        async def execute():
            return await asyncio.wait_for(registry.execute(row.tool_name,row.arguments,context),50)
        result=async_to_sync(execute)()
        if isinstance(result,dict) and result.get('confirmation_required'):raise PermissionError('确认未被消费')
        if isinstance(result,dict) and result.get('isError'):
            service.finish(row,result,error='工具返回失败；可能存在副作用，请核对后再发起新操作')
        else:service.finish(row,result)
        service.audit(row,context,'tool.confirmation.finished','error' if isinstance(result,dict) and result.get('isError') else 'ok')
        outcome='工具返回失败，可能存在副作用，请核对外部状态。' if isinstance(result,dict) and result.get('isError') else '工具调用完成，请查看确认卡片中的真实结果。'
        AgentMessage.objects.create(thread=thread,role='assistant',content=f'{row.tool_name}：{outcome}',
            metadata={'confirmation_id':str(row.pk)})
    except Exception as exc:
        # Avoid exposing remote addresses, secrets or arbitrary transport exception text.
        message=str(exc)[:500] if isinstance(exc,(PermissionError,ValueError)) else '执行失败或超时，结果可能不确定；请核对外部状态，勿自动重试'
        service.finish(row,error=message)
        service.audit(row,context,'tool.confirmation.denied','409')
        row.refresh_from_db()
        return JsonResponse({'error':message,'confirmation':service.data(row)},status=409)
    row.refresh_from_db()
    return JsonResponse(service.data(row))
