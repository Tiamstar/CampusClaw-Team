from datetime import timedelta, timezone as dt_timezone
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from .forum_views import api_view, access, page
from .views import fail
from .models import Course, Membership, DiagnosticSettings, DiagnosticReport, DiagnosticVersion
from .diagnostic_service import settings_for, basis_for_report, current_basis, still_authorized, validate_claims, version_values
from .gradebook_views import audit


def teacher_report(request, report_id):
    report=get_object_or_404(DiagnosticReport,pk=report_id)
    member=access(request.user,report.course_id)
    if member.role!='teacher' or report.creator_id!=request.user.id: raise PermissionDenied('仅能管理本人发起的诊断')
    return report


def visible_report(request, report_id):
    report=get_object_or_404(DiagnosticReport,pk=report_id)
    member=access(request.user,report.course_id)
    if member.role=='teacher':
        if report.creator_id!=request.user.id: raise PermissionDenied('仅能查看本人发起的诊断')
    elif report.student_id!=request.user.id or report.status!='published' or stale(report):
        raise PermissionDenied('报告尚未向本人发布')
    return report


def data(report, teacher=False):
    changed=stale(report)
    version=report.versions.filter(number=report.current_version).first() if report.current_version and not changed else None
    return {'id':report.id,'course_id':report.course_id,'student_id':report.student_id,
        'student_name':report.student.display_name,'status':report.status,'phase':report.phase,
        'revision':report.revision,'current_version':report.current_version,'published_version':report.published_version,
        'model':report.model,'skill':report.skill,'error':report.error,'stale':changed,
        'window':report.basis.get('learning',{}).get('window'),
        'version':({'number':version.number,'content':version.content,'content_hash':version.content_hash,
                    'html_url':f'/api/diagnostic-versions/{version.id}/html/','pdf_url':f'/api/diagnostic-versions/{version.id}/pdf/'} if version and (teacher or report.status=='published') else None)}


def stale(report):
    try:return current_basis(report)['fingerprint']!=report.basis['fingerprint']
    except ValueError:return True


@api_view(['GET','PUT'])
def settings(request,course_id):
    access(request.user,course_id,True)
    current=settings_for(course_id)
    if request.method=='GET':return Response({'enabled':current.enabled,'revision':current.revision})
    if type(request.data.get('enabled')) is not bool:return fail('启停选项无效')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id);current=settings_for(course_id)
        access(request.user,course_id,True)
        if type(request.data.get('expected_revision')) is not int or request.data['expected_revision']!=current.revision:return fail('诊断设置已变化',409)
        current.enabled=request.data['enabled'];current.revision+=1;current.save();audit(request,course_id,'diagnostic.settings',current.id)
    return Response({'enabled':current.enabled,'revision':current.revision})


@api_view(['GET','POST'])
def reports(request,course_id):
    member=access(request.user,course_id)
    if member.role!='teacher':
        if request.method=='POST':return fail('仅教师可发起诊断',403)
        rows=DiagnosticReport.objects.filter(course_id=course_id,student=request.user,status='published').order_by('-id')
    else:
        if request.method=='GET':
            offset,number=page(request); rows=list(DiagnosticReport.objects.filter(course_id=course_id,creator=request.user).select_related('student').order_by('-id')[offset:offset+21])
            return Response({'items':[data(r,True) for r in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
        if not settings_for(course_id).enabled:return fail('诊断技能已停用',409)
        allowed={'student_id','start','end'}
        if set(request.data)-allowed:return fail('诊断参数无效')
        try:
            sid=request.data.get('student_id');end=parse_datetime(request.data.get('end','')) if request.data.get('end') else timezone.now();start=parse_datetime(request.data.get('start','')) if request.data.get('start') else end-timedelta(days=90)
            if type(sid) is not int or not start or not end or timezone.is_naive(start) or timezone.is_naive(end) or not timedelta(0)<end-start<=timedelta(days=366):raise ValueError('学生和分析时间窗口无效')
            start,end=start.astimezone(dt_timezone.utc),end.astimezone(dt_timezone.utc)
            if not Membership.objects.filter(course_id=course_id,user_id=sid,role='student').exists():raise ValueError('目标不是本课程学生')
            with transaction.atomic():
                Course.objects.select_for_update().get(pk=course_id)
                if DiagnosticReport.objects.filter(course_id=course_id,creator=request.user,student_id=sid,status__in=['queued','running']).exists():return fail('该学生已有诊断任务执行中',409)
                access(request.user,course_id,True)
                cfg=settings_for(course_id)
                if not cfg.enabled:return fail('诊断技能已停用',409)
                basis=basis_for_report(course_id,sid,start,end)
                report=DiagnosticReport.objects.create(course_id=course_id,creator=request.user,student_id=sid,basis=basis,settings_revision=cfg.revision)
                audit(request,course_id,'diagnostic.queue',report.id)
        except (ValueError,TypeError,OverflowError) as exc:return fail(str(exc) or '诊断参数无效')
        return Response(data(report,True),status=201)
    offset,number=page(request); rows=list(rows.select_related('student').order_by('-id')[offset:offset+21])
    return Response({'items':[data(r,False) for r in rows[:20]],'next_page':number+1 if len(rows)>20 else None})


@api_view(['GET'])
def detail(request,report_id):
    report=visible_report(request,report_id)
    return Response(data(report,access(request.user,report.course_id).role=='teacher'))


@api_view(['GET'])
def versions(request,report_id):
    report=teacher_report(request,report_id)
    offset,number=page(request)
    rows=list(report.versions.defer('pdf','html','content').order_by('-number')[offset:offset+21])
    changed=stale(report)
    return Response({'items':[{'number':v.number,'content_hash':v.content_hash,'reason':v.reason,'created_at':v.created_at,
        'html_url':None if changed else f'/api/diagnostic-versions/{v.id}/html/',
        'pdf_url':None if changed else f'/api/diagnostic-versions/{v.id}/pdf/'} for v in rows[:20]],
        'next_page':number+1 if len(rows)>20 else None,'stale':changed})


@api_view(['POST'])
def action(request,report_id):
    initial=teacher_report(request,report_id);command=request.data.get('action')
    if command not in {'review','publish','cancel','withdraw'}:return fail('诊断操作无效')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=initial.course_id);report=DiagnosticReport.objects.select_for_update().get(pk=report_id)
        access(request.user,report.course_id,True)
        if report.creator_id!=request.user.id:raise PermissionDenied('无权操作此报告')
        if type(request.data.get('expected_revision')) is not int or request.data['expected_revision']!=report.revision:return fail('报告已变化，请刷新',409)
        if command=='withdraw':
            if report.status!='published':return fail('报告尚未发布',409)
            report.status='draft';report.phase='awaiting_review';report.published_version=None;report.published_at=None;report.revision+=1;report.save()
        elif command=='cancel':
            if report.status not in {'queued','running','draft'}:return fail('报告状态不允许取消',409)
            report.status='cancelled';report.phase='cancelled';report.revision+=1;report.save()
        else:
            if report.status!='draft' or report.current_version<1:return fail('报告尚未生成草稿',409)
            if stale(report):return fail('评分、图谱或配置已变化，请重新生成',409)
            if not still_authorized(report):return fail('诊断技能或教师权限已变化',409)
            version=report.versions.get(number=report.current_version)
            try:validate_claims({'claims':version.content['claims']},report.basis)
            except ValueError as exc:return fail(str(exc),409)
            if command=='review':
                checks=request.data.get('checked_point_ids')
                expected={c['point_id'] for c in version.content['claims']}
                if not isinstance(checks,list) or any(type(v) is not int for v in checks) or set(checks)!=expected or len(checks)!=len(expected):return fail('请逐条确认全部结论与引用',400)
            reason=request.data.get('reason','')
            if not isinstance(reason,str) or not reason.strip() or len(reason)>500:return fail('请填写教师复核理由')
            if command=='publish' and (report.phase!='reviewed' or report.reviewer_id!=request.user.id):return fail('请先逐条复核草稿，再发布',409)
            report.reviewer=request.user;report.review_reason=reason.strip();report.revision+=1
            if command=='review':report.phase='reviewed'
            else:report.status='published';report.phase='published';report.published_version=report.current_version;report.published_at=timezone.now()
            report.save()
        audit(request,report.course_id,'diagnostic.'+command,report.id)
    return Response(data(report,True))


@api_view(['POST'])
def revise(request,report_id):
    initial=teacher_report(request,report_id)
    if initial.status!='draft' or stale(initial):return fail('仅能修订依据有效的草稿',409)
    reason=request.data.get('reason','')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>500:return fail('请填写修订理由')
    try:
        claims=validate_claims({'claims':request.data.get('claims')},initial.basis)
        values=version_values(initial,claims,initial.current_version+1,request.user,reason.strip())
    except ValueError as exc:return fail(str(exc))
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=initial.course_id)
        report=DiagnosticReport.objects.select_for_update().get(pk=report_id)
        access(request.user,report.course_id,True)
        if type(request.data.get('expected_revision')) is not int or request.data['expected_revision']!=report.revision or initial.revision!=report.revision or report.status!='draft':return fail('报告已变化，请刷新',409)
        if stale(report) or not still_authorized(report):return fail('报告依据或配置已变化',409)
        DiagnosticVersion.objects.create(report=report,**values)
        report.current_version+=1;report.revision+=1;report.phase='awaiting_review';report.reviewer=None;report.review_reason='';report.save()
        audit(request,report.course_id,'diagnostic.revise',report.id)
    return Response(data(report,True))


@api_view(['GET'])
def version_file(request,version_id,kind):
    version=get_object_or_404(DiagnosticVersion,pk=version_id);report=version.report
    visible_report(request,report.id)
    if stale(report):return fail('报告依据已变化，旧导出暂停访问',409)
    if kind not in {'html','pdf'}:return fail('报告格式无效',404)
    teacher=access(request.user,report.course_id).role=='teacher'
    if not teacher and version.number!=report.published_version:raise PermissionDenied('版本不可见')
    response=HttpResponse(version.html,content_type='text/html; charset=utf-8') if kind=='html' else HttpResponse(bytes(version.pdf),content_type='application/pdf',headers={'Content-Disposition':f'inline; filename="diagnostic-{report.id}-v{version.number}.pdf"'})
    response['Cache-Control']='no-store'
    response['X-Content-Type-Options']='nosniff'
    response['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'; sandbox"
    response['X-Report-Version']=str(version.number);response['X-Report-Content-Hash']=version.content_hash
    return response
