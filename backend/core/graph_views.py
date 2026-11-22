from asgiref.sync import async_to_sync
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from .forum_views import api_view, access, text, page
from .views import fail
from .models import (Course, Membership, KnowledgePoint, Material, Question, ForumPost,
                     GraphConfig, GraphCandidate, GraphEdge, GraphResource, GraphVersion)
from .graph_service import (config_for, source_rows, current_sources, validate_proposal,
                            assert_acyclic, generate, graph_snapshot, save_version)
from .gradebook_views import audit
from .learning_views import authorized_learning


def revision(course_id):
    return GraphVersion.objects.filter(course_id=course_id).order_by('-number').values_list('number',flat=True).first() or 0


def expected(data,number):
    return type(data.get('expected_revision')) is int and data['expected_revision']==number


@api_view(['GET','PUT'])
def config(request,course_id):
    access(request.user,course_id,True)
    current=config_for(course_id)
    if request.method=='PUT':
        if type(request.data.get('extraction_enabled')) is not bool:return fail('启停选项无效')
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course_id)
            current=config_for(course_id)
            if not expected(request.data,current.revision):return fail('图谱设置已变化',409)
            current.extraction_enabled=request.data['extraction_enabled'];current.revision+=1;current.save()
            audit(request,course_id,'graph.config',current.id)
    return Response({'extraction_enabled':current.extraction_enabled,'revision':current.revision})


def candidate_data(item):
    return {'id':item.id,'status':item.status,'sources':current_sources(item.course_id,item.sources),
            'proposal':item.proposal,'reviewed_proposal':item.reviewed_proposal,'model':item.model,
            'skill':item.skill,'error':item.error,'created_at':item.created_at,'reviewed_at':item.reviewed_at,
            'reviewer_id':item.reviewer_id,'review_reason':item.review_reason}


@api_view(['GET','POST'])
def candidates(request,course_id):
    access(request.user,course_id,True)
    if request.method=='GET':
        offset,number=page(request)
        rows=list(GraphCandidate.objects.filter(course_id=course_id).order_by('-id')[offset:offset+21])
        return Response({'items':[candidate_data(i) for i in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
    ids=request.data.get('material_ids')
    if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(type(i) is not int for i in ids) or Material.objects.filter(course_id=course_id,id__in=ids).count()!=len(set(ids)):
        return fail('请选择本课程 1–10 份资料')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        settings=config_for(course_id)
        if not settings.extraction_enabled:return fail('知识点抽取技能已停用',409)
        if GraphCandidate.objects.filter(course_id=course_id,status='running').exists():return fail('已有抽取任务进行中',409)
        try:sources=source_rows(course_id,ids)
        except ValueError as e:return fail(str(e))
        item=GraphCandidate.objects.create(course_id=course_id,creator=request.user,sources=sources,settings_revision=settings.revision)
    proposal={};model='';error=''
    if not sources:status='no_evidence';error='所选资料没有就绪片段，请先完成索引'
    else:
        try:
            proposal,model=async_to_sync(generate)(sources)
            status='awaiting_review' if proposal['nodes'] else 'no_evidence'
            if status=='no_evidence':error='资料没有充分支持可提取的知识点'
        except Exception:status='failed';error='抽取失败或模型格式无效，请重试；正式图谱未修改'
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        item=GraphCandidate.objects.select_for_update().get(pk=item.id)
        settings=config_for(course_id)
        if item.status=='running':
            if not Membership.objects.filter(course_id=course_id,user=request.user,role='teacher').exists():
                status='failed';error='执行期间教师权限已撤销'
            elif settings.revision!=item.settings_revision or not settings.extraction_enabled:
                status='failed';error='设置已变化，迟到结果不进入审核'
            elif sources and not all(s['current'] for s in current_sources(course_id,sources)):
                status='failed';error='资料已变化，请重新抽取'
            item.proposal=proposal;item.model=model;item.status=status;item.error=error;item.save()
        audit(request,course_id,'graph.extract',item.id)
    # Recheck before returning private proposal/source text.
    access(request.user,course_id,True)
    return Response(candidate_data(item),status=201)


@api_view(['POST'])
def review(request,candidate_id):
    initial=get_object_or_404(GraphCandidate,pk=candidate_id);access(request.user,initial.course_id,True)
    action=request.data.get('action');reason=text(request.data,'reason',500)
    if action not in {'approve','reject','cancel'}:return fail('审核操作无效')
    try:
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=initial.course_id)
            item=GraphCandidate.objects.select_for_update().get(pk=candidate_id)
            if action=='cancel':
                if item.status!='running':return fail('仅进行中的任务可取消',409)
                item.status='cancelled'
            elif action=='reject':
                if item.status!='awaiting_review':return fail('候选已处理或不可审核',409)
                item.status='rejected'
            else:
                if item.status!='awaiting_review':return fail('候选已处理或不可审核',409)
                if not expected(request.data,revision(item.course_id)):return fail('图谱版本变化，请刷新核对',409)
                if not item.sources or not all(s['current'] for s in current_sources(item.course_id,item.sources)):
                    return fail('引用资料已失效，请重新抽取',409)
                proposal=validate_proposal(request.data.get('proposal'),item.sources)
                if not proposal['nodes']:return fail('至少批准一个有依据的节点')
                nodes={};sources={s['chunk_id']:s for s in item.sources}
                for n in proposal['nodes']:
                    point,_=KnowledgePoint.objects.get_or_create(course_id=item.course_id,name=n['name'])
                    if not point.active:raise ValueError('同名知识点已停用，请先显式恢复或修订名称')
                    nodes[n['key']]=point
                pairs=set(GraphEdge.objects.filter(course_id=item.course_id).values_list('prerequisite_id','target_id'))
                pairs.update((nodes[e['from']].id,nodes[e['to']].id) for e in proposal['edges'])
                assert_acyclic(set(KnowledgePoint.objects.filter(course_id=item.course_id).values_list('id',flat=True)),pairs)
                for n in proposal['nodes']:
                    selected=[sources[i] for i in n['source_ids']]
                    for mid in {s['material_id'] for s in selected}:
                        GraphResource.objects.get_or_create(course_id=item.course_id,point=nodes[n['key']],material_id=mid,
                            defaults={'candidate':item,'sources':[s for s in selected if s['material_id']==mid]})
                for e in proposal['edges']:
                    GraphEdge.objects.get_or_create(course_id=item.course_id,prerequisite=nodes[e['from']],target=nodes[e['to']],
                        defaults={'candidate':item,'sources':[sources[i] for i in e['source_ids']]})
                item.status='approved';item.reviewed_proposal=proposal
                save_version(item.course_id,request.user,reason)
            item.reviewer=request.user;item.review_reason=reason;item.reviewed_at=timezone.now();item.save()
            audit(request,item.course_id,'graph.'+action,item.id)
    except (ValueError,IntegrityError) as e:return fail(str(e) if isinstance(e,ValueError) else '知识点发生冲突，请刷新',409)
    return Response(candidate_data(item))


@api_view(['GET'])
def graph(request,course_id):
    teacher=access(request.user,course_id).role=='teacher'
    try:learning=authorized_learning(request.user,course_id,request.GET)
    except ValueError as e:return fail(str(e))
    snapshot=graph_snapshot(course_id)
    values=learning['class_points'] if teacher and not request.GET.get('student_id') else (learning['students'][0]['points'] if learning['students'] else [])
    metrics={p['id']:p for p in values}
    for n in snapshot['nodes']:
        n['metric']=metrics.get(n['id'],{'mastery':None,'band':'unknown','sample_size':0})
    for e in snapshot['edges']:
        e['sources']=current_sources(course_id,e['sources'])
    for r in snapshot['resources']:
        r['sources']=current_sources(course_id,r['sources'])
    return Response({**snapshot,'revision':revision(course_id),'learning_version':learning['data_version'],
                     'window':learning['window'],'include_unpublished':learning['include_unpublished']})


@api_view(['PUT'])
def point_edit(request,point_id):
    initial=get_object_or_404(KnowledgePoint,pk=point_id);access(request.user,initial.course_id,True)
    name=text(request.data,'name',100);reason=text(request.data,'reason',500)
    if type(request.data.get('active')) is not bool:return fail('启用状态无效')
    try:
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=initial.course_id)
            point=KnowledgePoint.objects.select_for_update().get(pk=point_id)
            if not expected(request.data,revision(point.course_id)):return fail('图谱版本已变化',409)
            point.name=name;point.active=request.data['active'];point.revision+=1;point.save()
            save_version(point.course_id,request.user,reason);audit(request,point.course_id,'graph.point.edit',point.id)
    except IntegrityError:return fail('本课程已有同名知识点',409)
    return Response({'id':point.id,'name':point.name,'active':point.active,'revision':point.revision})


@api_view(['POST'])
def link(request,course_id):
    access(request.user,course_id,True)
    pid,mid=request.data.get('point_id'),request.data.get('material_id');reason=text(request.data,'reason',500)
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        if not expected(request.data,revision(course_id)):return fail('图谱版本已变化',409)
        if type(pid) is not int or type(mid) is not int or not KnowledgePoint.objects.filter(pk=pid,course_id=course_id,active=True).exists() or not Material.objects.filter(pk=mid,course_id=course_id).exists():
            return fail('知识点或资料不可挂接')
        item,created=GraphResource.objects.get_or_create(course_id=course_id,point_id=pid,material_id=mid)
        if created:save_version(course_id,request.user,reason)
        audit(request,course_id,'graph.resource',item.id)
    return Response({'id':item.id},status=201 if created else 200)


@api_view(['GET'])
def resources(request,point_id):
    point=get_object_or_404(KnowledgePoint,pk=point_id);teacher=access(request.user,point.course_id).role=='teacher'
    offset,number=page(request)
    links=list(GraphResource.objects.filter(point=point,course_id=point.course_id).select_related('material').order_by('id')[offset:offset+21])
    materials=[{'id':r.material_id,'title':r.material.title,'preview_url':f'/api/materials/{r.material_id}/preview/',
                'download_url':f'/api/files/{r.material.attachment_id}/download/','sources':current_sources(point.course_id,r.sources)} for r in links[:20]]
    posts=list(ForumPost.objects.filter(course_id=point.course_id,points=point).order_by('-id').values('id','title')[:20])
    # Students never see bank answers or unopened question bodies via graph resources.
    questions=list(Question.objects.filter(course_id=point.course_id,points=point).order_by('-id').values('id','body','active','revision')[:20]) if teacher else []
    wrong=[]
    if not teacher:
        learning=authorized_learning(request.user,point.course_id,{})
        own=learning['students'][0]['points'] if learning['students'] else []
        from decimal import Decimal
        evidence=next((p['evidence'] for p in own if p['id']==point.id),[])
        wrong=[e for e in evidence if Decimal(e['score'])<Decimal(e['maximum'])]
    return Response({'point':{'id':point.id,'name':point.name,'active':point.active},'materials':materials,
                     'posts':posts,'questions':questions,'my_incomplete_answers':wrong,'next_page':number+1 if len(links)>20 else None})


@api_view(['GET'])
def versions(request,course_id):
    access(request.user,course_id,True);offset,number=page(request)
    rows=list(GraphVersion.objects.filter(course_id=course_id).order_by('-number')[offset:offset+21])
    return Response({'items':[{'number':v.number,'actor_id':v.actor_id,'reason':v.reason,'created_at':v.created_at,'snapshot':v.snapshot} for v in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
