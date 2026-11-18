from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from collections.abc import Mapping
from functools import wraps
from asgiref.sync import async_to_sync
from django.db import transaction
from django.db.models import Count, Q, Exists, OuterRef, Case, When, Value, IntegerField
from django.contrib.postgres.search import TrigramSimilarity
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view as drf_api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import (ForumPost, ForumReply, ForumDraft, ForumSettings, ForumTodo, KnowledgePoint, Membership)
from .views import member, fail
from .audit import record_audit
from .forum_service import settings_for, generate_draft, close_todos, sources_current, citation_data
from .forum_service import DRAFT_ERRORS, DraftGenerationError, draft_failure_code, stored_failure_code


def api_view(methods):
    def decorate(view):
        @drf_api_view(methods)
        @wraps(view)
        def checked(request,*args,**kwargs):
            if request.method!='GET' and not isinstance(request.data,Mapping):
                return fail('请求必须是 JSON 对象')
            return view(request,*args,**kwargs)
        return checked
    return decorate


def access(user, course_id, teacher=False):
    result = member(user, course_id, 'teacher' if teacher else None)
    if result is None:
        raise PermissionDenied('无权访问该课程讨论')
    return result


def audit(request, post, action):
    record_audit(actor_id=request.user.id, course_id=post.course_id, action='forum.'+action,
                 object_ref=str(post.id), status='ok', request_id=request.request_id)


def text(data, key, maximum, required=True):
    value = data.get(key, '')
    if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()):
        raise ValidationError({'error': f'{key} 不能为空且最多 {maximum} 字'})
    return value.strip()


def page(request, size=20):
    try:
        number = int(request.GET.get('page','1'))
        if number<1 or number>100000:
            raise ValueError()
        return (number-1)*size, number
    except ValueError:
        raise ValidationError({'error':'页码无效'})


def post_data(post, user, teacher):
    anonymous = post.anonymous and not teacher
    data = {'id':post.id, 'title':post.title,'body':post.body, 'anonymous':post.anonymous,
            'author':{'name':'匿名同学' if anonymous else post.author.display_name,
                      **({} if anonymous else {'id':post.author_id})},
            'is_mine':post.author_id==user.id, 'pinned':post.pinned,'featured':post.featured,
            'resolved_reply_id':post.resolved_reply_id,'resolved_at':post.resolved_at,'revision':post.revision,
            'teacher_answered':post.teacher_answered if hasattr(post,'teacher_answered') else post.replies.filter(teacher_answer=True).exists(),
            'created_at':post.created_at,
            'points':[{'id':p.id,'name':p.name} for p in post.points.all()],
            'mentions':[{'id':u.id,'name':u.display_name} for u in post.mentions.all()],
            'reply_count':post.reply_count if hasattr(post,'reply_count') else post.replies.count()}
    return data


def reply_data(reply):
    return {'id':reply.id, 'body':reply.body, 'author':{'id':reply.author_id,'name':reply.author.display_name},
            'teacher_answer':reply.teacher_answer,'created_at':reply.created_at,
            'draft_id':reply.draft_id, 'citations':citation_data(reply.draft) if reply.draft_id else [],
            'model':reply.draft.model if reply.draft_id else '',
            'skill_version':reply.draft.skill_version if reply.draft_id else '',
            'confirmed_by':reply.draft.confirmed_by_id if reply.draft_id else None}


@api_view(['GET','PUT'])
def config(request, course_id):
    membership = access(request.user,course_id)
    current = settings_for(course_id)
    if request.method=='PUT':
        access(request.user,course_id,True)
        enabled = request.data.get('draft_enabled')
        hours = request.data.get('wait_hours')
        zone = request.data.get('timezone')
        if type(enabled) is not bool or type(hours) is not int or not 1<=hours<=720 or not isinstance(zone,str):
            return fail('等待阈值须为 1–720 小时，配置格式无效')
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            return fail('时区无效')
        with transaction.atomic():
            current,_ = ForumSettings.objects.select_for_update().get_or_create(course_id=course_id)
            if request.data.get('expected_revision')!=current.revision:
                return fail('配置已更新，请刷新',409)
            current.draft_enabled,current.wait_hours,current.timezone=enabled,hours,zone
            current.revision+=1
            current.save()
        record_audit(actor_id=request.user.id, course_id=course_id, action='forum.config',object_ref=str(current.id),
                     status='ok',request_id=request.request_id)
    return Response({'draft_enabled':current.draft_enabled,'wait_hours':current.wait_hours,
                     'timezone':current.timezone,'revision':current.revision,'is_teacher':membership.role=='teacher'})


@api_view(['GET','POST'])
def points(request,course_id):
    access(request.user,course_id)
    if request.method=='POST':
        access(request.user,course_id,True)
        from .models import Course
        from .graph_service import save_version
        name=text(request.data,'name',100)
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course_id)
            item,created=KnowledgePoint.objects.get_or_create(course_id=course_id,name=name)
            if not item.active:return fail('该知识点已停用，请在图谱显式恢复',409)
            if created:save_version(course_id,request.user,'教师在论坛新增知识点')
        return Response({'id':item.id,'name':item.name},status=201)
    return Response(list(KnowledgePoint.objects.filter(course_id=course_id,active=True).order_by('name').values('id','name')))


@api_view(['GET','POST'])
def posts(request,course_id):
    membership=access(request.user,course_id)
    teacher=membership.role=='teacher'
    if request.method=='GET':
        offset,number=page(request)
        rows=ForumPost.objects.filter(course_id=course_id).select_related('author').prefetch_related('points','mentions').annotate(reply_count=Count('replies'),teacher_answered=Exists(ForumReply.objects.filter(post_id=OuterRef('pk'),teacher_answer=True)))
        query=request.GET.get('q','').strip()[:200]
        if query:
            rows=rows.annotate(reply_match=Exists(ForumReply.objects.filter(post_id=OuterRef('pk'),body__icontains=query))).filter(Q(title__icontains=query)|Q(body__icontains=query)|Q(reply_match=True))
        author_role=request.GET.get('author_role','')
        if author_role not in ('','teacher','student'):return fail('发布者角色无效')
        if author_role:
            rows=rows.filter(author_id__in=Membership.objects.filter(course_id=course_id,role=author_role).values('user_id'))
        status=request.GET.get('status','')
        if status not in ('','open','resolved','answered'):return fail('讨论状态无效')
        if status=='open':rows=rows.filter(resolved_reply__isnull=True)
        elif status=='resolved':rows=rows.filter(resolved_reply__isnull=False)
        elif status=='answered':rows=rows.filter(teacher_answered=True)
        if request.GET.get('point'):
            try:
                rows=rows.filter(points__id=int(request.GET['point']))
            except ValueError:
                return fail('知识点无效')
        if query:
            rows=rows.annotate(search_rank=Case(When(title__iexact=query,then=Value(4)),When(title__icontains=query,then=Value(3)),When(body__icontains=query,then=Value(2)),default=Value(1),output_field=IntegerField()))
            rows=rows.order_by('-search_rank','-pinned','-created_at','-id')
        else:rows=rows.order_by('-pinned','-created_at','-id')
        batch=list(rows[offset:offset+21])
        return Response({'items':[post_data(p,request.user,teacher) for p in batch[:20]], 'next_page':number+1 if len(batch)>20 else None})
    if set(request.data)-{'title','body','anonymous','point_ids','mention_ids'}:
        return fail('包含不支持的发帖字段')
    title,body=text(request.data,'title',200),text(request.data,'body',20000)
    anonymous=request.data.get('anonymous',False)
    point_ids,mentions=request.data.get('point_ids',[]),request.data.get('mention_ids',[])
    if type(anonymous) is not bool or any(not isinstance(v,list) or len(v)>20 or any(type(i) is not int for i in v) for v in [point_ids,mentions]):
        return fail('匿名、知识点或教师选择无效')
    if KnowledgePoint.objects.filter(course_id=course_id,active=True,id__in=point_ids).count()!=len(set(point_ids)) or Membership.objects.filter(course_id=course_id,role='teacher',user_id__in=mentions).count()!=len(set(mentions)):
        return fail('知识点或提及教师不属于本课程')
    with transaction.atomic():
        post=ForumPost.objects.create(course_id=course_id,author=request.user,title=title,body=body,anonymous=anonymous)
        post.points.set(point_ids)
        post.mentions.set(mentions)
        for teacher_id in set(mentions):
            ForumTodo.objects.get_or_create(post=post,teacher_id=teacher_id,reason='mention')
        audit(request,post,'create')
    return Response(post_data(post,request.user,teacher),status=201)


@api_view(['GET'])
def similar(request,course_id):
    access(request.user,course_id)
    query=request.GET.get('q','').strip()[:200]
    if len(query)<2:
        return Response({'status':'empty','items':[]})
    try:
        rows=list(ForumPost.objects.filter(course_id=course_id).annotate(score=TrigramSimilarity('title',query)).filter(
            Q(score__gte=.15)|Q(title__icontains=query)).order_by('-score','-id').values('id','title')[:5])
        return Response({'status':'ready' if rows else 'empty','items':rows})
    except Exception:
        return Response({'status':'unavailable','items':[],'message':'相似帖检索暂不可用，仍可发布新问题'})


@api_view(['GET','PATCH'])
def post_detail(request,post_id):
    post=get_object_or_404(ForumPost.objects.select_related('author').prefetch_related('points','mentions'),pk=post_id)
    membership=access(request.user,post.course_id)
    if request.method=='PATCH':
        data=request.data
        if 'resolved_reply_id' in data:
            if set(data)-{'resolved_reply_id','expected_revision'}:return fail('解决状态字段无效')
            if post.author_id!=request.user.id and membership.role!='teacher':raise PermissionDenied('仅提问者或任课教师可标记解决')
            reply_id=data['resolved_reply_id']
            if reply_id is not None and (type(reply_id) is not int or reply_id<=0):return fail('解决回复无效')
            with transaction.atomic():
                post=ForumPost.objects.select_for_update().get(pk=post_id)
                if type(data.get('expected_revision')) is not int or data['expected_revision']!=post.revision:return fail('讨论已更新，请刷新后重试',409)
                if reply_id is not None and not ForumReply.objects.filter(pk=reply_id,post_id=post_id).exists():return fail('解决回复不属于此讨论')
                post.resolved_reply_id=reply_id
                post.resolved_at=timezone.now() if reply_id else None
                post.revision+=1
                post.save(update_fields=['resolved_reply','resolved_at','revision'])
                audit(request,post,'resolve' if reply_id else 'reopen')
        else:
            access(request.user,post.course_id,True)
            if not data or set(data)-{'pinned','featured'} or any(type(v) is not bool for v in data.values()):return fail('治理选项无效')
            with transaction.atomic():
                post=ForumPost.objects.select_for_update().get(pk=post_id)
                for key,value in data.items():setattr(post,key,value)
                post.revision+=1
                post.save(update_fields=[*data,'revision'])
                audit(request,post,'moderate')
    return Response(post_data(post,request.user,membership.role=='teacher'))


@api_view(['GET','POST'])
def replies(request,post_id):
    post=get_object_or_404(ForumPost,pk=post_id)
    membership=access(request.user,post.course_id)
    if request.method=='GET':
        offset,number=page(request,50)
        rows=list(post.replies.select_related('author','draft__post').order_by('created_at','id')[offset:offset+51])
        return Response({'items':[reply_data(r) for r in rows[:50]],'next_page':number+1 if len(rows)>50 else None})
    body=text(request.data,'body',20000)
    with transaction.atomic():
        ForumPost.objects.select_for_update().get(pk=post.id)
        reply=ForumReply.objects.create(post=post,author=request.user,body=body,teacher_answer=membership.role=='teacher')
        if reply.teacher_answer:
            close_todos(post.id)
        audit(request,post,'reply')
    return Response(reply_data(reply),status=201)


def draft_data(draft):
    return {'id':draft.id,'status':draft.status,'body':draft.body,'citations':citation_data(draft),'error':draft.error,
            'error_code':stored_failure_code(draft),
            'model':draft.model,'skill_version':draft.skill_version,'request_id':draft.request_id,'created_at':draft.created_at,
            'published_at':draft.published_at,'confirmed_by':draft.confirmed_by_id}


@api_view(['GET','POST'])
def drafts(request,post_id):
    post=get_object_or_404(ForumPost,pk=post_id)
    access(request.user,post.course_id,True)
    if request.method=='GET':
        offset,number=page(request)
        rows=list(ForumDraft.objects.filter(post=post).select_related('post').order_by('-id')[offset:offset+21])
        return Response({'items':[draft_data(d) for d in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
    with transaction.atomic():
        config,_=ForumSettings.objects.select_for_update().get_or_create(course_id=post.course_id)
        if not config.draft_enabled:
            return fail('答疑草稿技能已停用',409)
        ForumPost.objects.select_for_update().get(pk=post.id)
        if ForumDraft.objects.filter(post=post,status='running').exists():
            return fail('已有草稿正在生成，请稍后刷新',409)
        draft=ForumDraft.objects.create(post=post,requested_by=request.user,settings_revision=config.revision,request_id=request.request_id)
    try:
        body,citations,model=async_to_sync(generate_draft)(post)
        with transaction.atomic():
            config=ForumSettings.objects.select_for_update().get(pk=config.pk)
            if member(request.user,post.course_id,'teacher') is None:
                raise DraftGenerationError('permission_lost')
            draft=ForumDraft.objects.select_for_update().get(pk=draft.pk)
            if not config.draft_enabled or config.revision!=draft.settings_revision or draft.status!='running':
                raise DraftGenerationError('state_changed')
            draft.body,draft.citations,draft.model=body,citations,model
            draft.status='awaiting_review' if citations else 'no_evidence'
            draft.save()
    except Exception as exc:
        code=draft_failure_code(exc)
        changed=ForumDraft.objects.filter(pk=draft.pk,status='running').update(status='failed',error=DRAFT_ERRORS[code])
        if changed:
            record_audit(actor_id=request.user.id,course_id=post.course_id,action='forum.draft.failure',
                         object_ref=str(draft.pk),status=code,request_id=request.request_id)
        draft.refresh_from_db()
    audit(request,post,'draft.'+draft.status)
    access(request.user,post.course_id,True)
    return Response(draft_data(draft),status=201)


@api_view(['POST'])
def publish_draft(request,draft_id):
    initial=get_object_or_404(ForumDraft.objects.select_related('post'),pk=draft_id)
    access(request.user,initial.post.course_id,True)
    body=text(request.data,'body',20000)
    if request.data.get('confirm') is not True:
        return fail('请明确确认已核对草稿和引用')
    with transaction.atomic():
        config,_=ForumSettings.objects.select_for_update().get_or_create(course_id=initial.post.course_id)
        ForumPost.objects.select_for_update().get(pk=initial.post_id)
        draft=ForumDraft.objects.select_for_update().select_related('post').get(pk=draft_id)
        if draft.status=='published':
            reply=ForumReply.objects.get(draft=draft)
            if reply.body!=body:
                return fail('草稿已经发布，内容不一致',409)
            return Response(reply_data(reply))
        if not config.draft_enabled or draft.status!='awaiting_review' or not draft.citations:
            return fail('技能停用或草稿不可发布，请人工回复',409)
        if not sources_current(draft):
            return fail('引用资料已变化，请重新生成并审核',409)
        draft.status,draft.confirmed_by,draft.published_at='published',request.user,timezone.now()
        draft.save()
        reply=ForumReply.objects.create(post=draft.post,author=request.user,body=body,teacher_answer=True,draft=draft)
        close_todos(draft.post_id)
        audit(request,draft.post,'publish')
    return Response(reply_data(reply),status=201)


@api_view(['GET'])
def todos(request,course_id):
    access(request.user,course_id,True)
    offset,number=page(request)
    rows=list(ForumTodo.objects.filter(post__course_id=course_id,teacher=request.user).select_related('post').order_by('closed_at','-created_at','-id')[offset:offset+21])
    return Response({'items':[{'id':t.id,'post_id':t.post_id,'title':t.post.title,'reason':t.reason,
                    'created_at':t.created_at,'closed_at':t.closed_at} for t in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
