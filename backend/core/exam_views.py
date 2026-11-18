import hashlib
import re
from pathlib import Path
from io import BytesIO
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from .forum_views import api_view, access, page
from .views import fail
from .models import Course, ExamSource, QuestionAsset, QuestionGroup, Question, QuizAttempt
from .exam_service import (teacher, own_source, owned_questions, MAX_FILE, clean_draft, save_image,
    check_assets, asset_ids, commit_source, live_paper, update_paper, PaperConflict, remember_paper, touch_paper)
from .quiz_views import expected, audit


def source_data(source, *, detail=True):
    data={'id':source.id,'name':source.name,'original_name':source.original_name or source.name,'status':source.status,'revision':source.revision,'error':source.error,
          'model':source.model,'created_at':source.created_at,'mapping':source.mapping,
          'archived_at':source.archived_at,'schema_version':1,
          'download_url':f'/api/exam-sources/{source.id}/file/'}
    if detail:
        data.update(units=source.units,draft=live_paper(source) if source.status=='committed' else source.draft)
        data['bank_versions']={str(e.question_id):e.question.revision for e in source.entries.select_related('question')}
        data['group_versions']={str(g['group_id']):g['group_revision'] for g in data['draft'].get('groups',[]) if 'group_id' in g}
        data['history'] = list(source.edit_history.order_by('-revision').values('revision','created_at')[:20])
    return data


@api_view(['GET','POST'])
def sources(request, course_id):
    teacher(request.user,course_id)
    if request.method=='GET':
        offset,number=page(request)
        query=ExamSource.objects.filter(course_id=course_id,owner=request.user)
        query=query.filter(archived_at__isnull=request.GET.get('archived')!='1')
        if request.GET.get('q','').strip():query=query.filter(name__icontains=request.GET['q'].strip()[:200])
        rows=list(query.order_by('-id')[offset:offset+21])
        return Response({'items':[source_data(row,detail=False) for row in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
    uploads=request.FILES.getlist('file');upload=uploads[0] if uploads else None;key=request.data.get('request_key')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',key):return fail('上传请求标识无效')
    if not upload or not 0<upload.size<=MAX_FILE:return fail('请选择 20 MiB 以内的试卷')
    if len(uploads)>12 or sum(f.size for f in uploads)>MAX_FILE:return fail('最多12张照片，文件合计不能超过20 MiB')
    if Path(upload.name).suffix.lower() not in {'.txt','.png','.jpg','.jpeg','.webp','.docx','.pdf'}:return fail('支持 TXT、图片、DOCX、PDF')
    filename=upload.name
    raw=upload.read(MAX_FILE+1)
    if len(raw)>MAX_FILE:return fail('文件不能超过 20 MiB')
    digest=hashlib.sha256(raw).hexdigest()
    if len(uploads)>1:
        if len(uploads)>12:return fail('一份照片试卷最多12页')
        try:
            import fitz
            from PIL import Image,ImageOps
            originals=[raw]+[f.read(MAX_FILE+1) for f in uploads[1:]]
            if sum(map(len,originals))>MAX_FILE:return fail('照片合计不能超过20 MiB')
            digest=hashlib.sha256(b''.join(hashlib.sha256(b).digest() for b in originals)).hexdigest()
            with fitz.open() as pdf:
                for photo,content in zip(uploads,originals):
                    if Path(photo.name).suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:return fail('批量上传只支持照片；PDF或Word请单独上传')
                    with Image.open(BytesIO(content)) as image:
                        if image.width*image.height>20_000_000:return fail('单张照片超过2000万像素')
                        image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((2000,2600));out=BytesIO();image.save(out,'PNG')
                        photo_page=pdf.new_page(width=image.width*.4,height=image.height*.4);photo_page.insert_image(photo_page.rect,stream=out.getvalue())
                raw=pdf.tobytes(deflate=True)
            if len(raw)>MAX_FILE:return fail('照片合成后超过20 MiB，请减少页数')
            filename='照片试卷-'+str(len(uploads))+'页.pdf'
        except Exception:return fail('照片文件无效，无法合成试卷')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        teacher(request.user,course_id)
        old=ExamSource.objects.filter(course_id=course_id,owner=request.user,request_key=key).first()
        if old:
            if old.digest!=digest:return fail('上传标识已用于另一文件',409)
            return Response(source_data(old))
        if ExamSource.objects.filter(course_id=course_id,owner=request.user,status__in=['queued','running']).count()>=3:
            return fail('已有 3 个待处理任务，请等待或取消后继续',429)
        source=ExamSource(course_id=course_id,owner=request.user,name=filename[:200],original_name=filename[:200],digest=digest,request_key=key)
        source.file.save(f'{digest}{Path(filename).suffix.lower()}',ContentFile(raw),save=True)
        audit(request,course_id,'exam.upload',source.id)
    return Response(source_data(source),status=201)


@api_view(['GET','PUT','POST'])
def source_detail(request, source_id):
    initial=get_object_or_404(ExamSource,pk=source_id);own_source(request.user,initial)
    if request.method=='GET':return Response(source_data(initial))
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=initial.course_id)
        source=ExamSource.objects.select_for_update().get(pk=source_id);own_source(request.user,source)
        action=request.data.get('action')
        if request.method=='POST' and action=='commit' and source.status=='committed':
            return Response(source_data(source))
        if not expected(request.data,source.revision):return fail('试卷草稿已更新，请刷新后核对',409)
        try:
            if source.archived_at and action!='restore':return fail('请先恢复已归档试卷再编辑',409)
            if action=='crop':
                aid=request.data.get('asset_id');box=request.data.get('box')
                if type(aid) is not int or not isinstance(box,list) or len(box)!=4 or any(type(v) is not int or not 0<=v<=1000 for v in box) or box[0]>=box[2] or box[1]>=box[3]:return fail('请在原卷图片上框选有效区域')
                asset=get_object_or_404(QuestionAsset,pk=aid,source=source,owner=request.user)
                from PIL import Image
                with asset.file.open('rb') as f, Image.open(f) as image:
                    bounds=(box[0]*image.width//1000,box[1]*image.height//1000,box[2]*image.width//1000,box[3]*image.height//1000)
                    if bounds[2]-bounds[0]<5 or bounds[3]-bounds[1]<5:return fail('裁剪区域太小，请重新框选')
                    output=BytesIO();image.crop(bounds).save(output,'PNG')
                cropped=save_image(source,output.getvalue(),'教师框选的题目配图')
                audit(request,source.course_id,'asset.crop',cropped.id)
                return Response({'id':cropped.id,'marker':f'{{{{asset:{cropped.id}}}}}'},status=201)
            elif request.method=='PUT':
                if source.status=='committed':
                    update_paper(source,request.user,request.data.get('draft'),request.data.get('bank_versions'),request.data.get('group_versions'))
                else:
                    if source.status not in {'ready','failed'}:return fail('请先完成识别或转人工整理',409)
                    source.draft=clean_draft(request.data.get('draft'),source.units)
                    source.revision+=1;source.save(update_fields=['draft','revision'])
                    remember_paper(source,request.user,source.draft)
            elif action=='commit':
                if request.data.get('confirmed') is not True:return fail('请先核对题干、材料、配图和来源并确认')
                commit_source(source,request.user)
            elif action=='retry':
                if source.status not in {'failed','ready'}:return fail('当前任务不能重试',409)
                source.status='queued';source.error='';source.revision+=1;source.save(update_fields=['status','error','revision'])
            elif action=='manual':
                if source.status=='committed':return fail('已入库，请在题库修改',409)
                source.lease_token='';source.status='ready';source.revision+=1;source.error=''
                if not source.units:source.units=[{'id':1,'label':'原文件（人工整理）','text':'','asset_ids':[]}]
                if not source.draft:source.draft={'groups':[{'title':source.name,'material':'','source_units':[source.units[0]['id']], 'questions':[
                    {'kind':'short','body':'','options':[],'answer':{'values':[]},'explanation':'','source_units':[source.units[0]['id']]}]}]}
                source.save(update_fields=['status','revision','lease_token','units','draft','error'])
            elif action=='rename':
                name=request.data.get('name')
                if not isinstance(name,str) or not 1<=len(name.strip())<=200:return fail('试卷名称须为1–200字')
                source.name=name.strip();source.revision+=1;source.save(update_fields=['name','revision'])
            elif action in {'archive','restore'}:
                if source.status in {'queued','running'}:return fail('请先等待识别结束或转人工整理再归档',409)
                source.archived_at=timezone.now() if action=='archive' else None
                source.revision+=1;source.save(update_fields=['archived_at','revision'])
            else:return fail('操作无效')
        except PaperConflict as exc:
            return fail(str(exc),409)
        except (ValueError,TypeError,ValidationError) as exc:
            return fail(str(exc),422)
        audit(request,source.course_id,'exam.'+(action or 'edit'),source.id)
    return Response(source_data(source))


@api_view(['GET'])
def source_file(request, source_id):
    source=get_object_or_404(ExamSource,pk=source_id);own_source(request.user,source)
    response=FileResponse(source.file.open('rb'),as_attachment=True,filename=source.original_name or source.name,content_type='application/octet-stream')
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    return response


@api_view(['POST'])
def upload_asset(request, course_id):
    teacher(request.user,course_id)
    upload=request.FILES.get('file')
    if not upload or not 0<upload.size<=5*1024*1024:return fail('配图须为 5 MiB 以内的 PNG/JPEG/WebP')
    if Path(upload.name).suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:return fail('配图支持 PNG/JPEG/WebP')
    # Use the same canonical encoder as source extraction, without creating an exam source.
    try:
        from PIL import Image,ImageOps
        import uuid
        raw=upload.read(5*1024*1024+1)
        with Image.open(BytesIO(raw)) as image:
            if image.width*image.height>20_000_000:raise ValueError('图片超过 2000 万像素')
            image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((2000,2600))
            result=BytesIO();image.save(result,'PNG')
        data=result.getvalue()
        asset=QuestionAsset(course_id=course_id,owner=request.user,digest=hashlib.sha256(data).hexdigest(),label=upload.name[:200])
        asset.file.save(uuid.uuid4().hex+'.png',ContentFile(data),save=True)
    except Exception:return fail('图片无效或超过像素限制')
    audit(request,course_id,'asset.upload',asset.id)
    return Response({'id':asset.id,'marker':f'{{{{asset:{asset.id}}}}}'},status=201)


@api_view(['GET'])
def asset_file(request, asset_id):
    asset=get_object_or_404(QuestionAsset,pk=asset_id)
    membership=access(request.user,asset.course_id)
    allowed=membership.role=='teacher' and asset.owner_id==request.user.id
    if not allowed and not asset.is_page:
        rows=QuizAttempt.objects.filter(student=request.user,quiz__course_id=asset.course_id).filter(
            Q(snapshot__contains=[{'public_asset_ids':[asset.id]}]) |
            Q(status='submitted',quiz__answers_at__lte=timezone.now(),snapshot__contains=[{'solution_asset_ids':[asset.id]}]))
        allowed=rows.exists()
    if not allowed:raise PermissionDenied('无权访问此题目配图')
    response=FileResponse(asset.file.open('rb'),content_type='image/png')
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    return response


def group_data(group):
    return {'id':group.id,'title':group.title,'material':group.material,'revision':group.revision,'active':group.active,
            'source_id':group.source_id,'source_units':group.source_units,
            'question_ids':list(group.questions.order_by('position','id').values_list('id',flat=True))}


@api_view(['GET','POST'])
def groups(request,course_id):
    teacher(request.user,course_id)
    if request.method=='GET':
        offset,number=page(request)
        rows=list(QuestionGroup.objects.filter(course_id=course_id,owner=request.user).order_by('-id')[offset:offset+21])
        return Response({'items':[group_data(g) for g in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
    return save_group(request,course_id)


def save_group(request,course_id,group=None):
    title=request.data.get('title');material=request.data.get('material','');active=request.data.get('active',True)
    if not isinstance(title,str) or not 1<=len(title.strip())<=200 or not isinstance(material,str) or len(material)>30000 or type(active) is not bool:return fail('标题、共享材料或启用状态无效')
    try:check_assets(request.user,course_id,[material])
    except ValueError as exc:return fail(str(exc))
    if group:
        if not expected(request.data,group.revision):return fail('题组版本冲突',409)
        order=request.data.get('question_ids')
        if order is not None:
            ids=list(group.questions.values_list('id',flat=True))
            if not isinstance(order,list) or any(type(i) is not int for i in order) or len(order)!=len(set(order)) or set(order)!=set(ids):return fail('排序须恰好包含题组全部小题')
            for position,qid in enumerate(order):group.questions.filter(pk=qid).update(position=position)
        group.title=title.strip();group.material=material;group.active=active;group.revision+=1;group.save()
        if group.source_id:touch_paper(group.source,request.user)
    else:group=QuestionGroup.objects.create(course_id=course_id,owner=request.user,title=title.strip(),material=material,active=active)
    audit(request,course_id,'group.edit',group.id)
    return Response(group_data(group),status=200 if group.revision>1 else 201)


@api_view(['PUT'])
def group_detail(request,group_id):
    original=get_object_or_404(QuestionGroup,pk=group_id);teacher(request.user,original.course_id)
    if original.owner_id!=request.user.id:raise PermissionDenied('仅所有者可管理题组')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=original.course_id)
        group=QuestionGroup.objects.select_for_update().get(pk=group_id)
        return save_group(request,group.course_id,group)
