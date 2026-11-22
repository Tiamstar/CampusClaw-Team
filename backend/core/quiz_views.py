import re
import asyncio
import hashlib
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from asgiref.sync import async_to_sync
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from PIL import Image
from rest_framework.response import Response
from .forum_views import api_view,access,text,page
from .views import fail
from .assignment_views import score_value
from .models import (Question,Quiz,QuizAttempt,QuizSaveReceipt,QuizAnswerImage,QuizSuggestion,KnowledgePoint,QuestionImportBatch,Course,QuestionGroup)
from .quiz_service import (KINDS,question_snapshot,paper,fingerprint,validate_answers,finalize,record_grade,
                           attempt_data,quiz_statistics)
from .audit import record_audit
from .question_import import parse_file, template_bytes
from .exam_service import owned_questions, check_assets, touch_paper


def audit(request,course_id,action,obj):
    record_audit(actor_id=request.user.id,course_id=course_id,action='quiz.'+action,object_ref=str(obj),
                 status='ok',request_id=request.request_id)


def expected(data,revision):
    return type(data.get('expected_revision')) is int and data['expected_revision']==revision


def validate_question(data,course_id,bank=False):
    kind=data.get('kind');body=text(data,'body',20000)
    if kind not in KINDS:raise ValueError('题型无效')
    score=None if bank and data.get('score') in (None,'') else score_value(data.get('score'),Decimal('99999.99'))
    if score is not None and score<=0:raise ValueError('题目分值须大于零')
    options=data.get('options',[]);answer=data.get('answer',{'values':[]} if bank else {})
    if not isinstance(options,list) or len(options)>10 or any(not isinstance(v,str) or not v.strip() or len(v)>2000 for v in options):raise ValueError('选项无效')
    if kind in {'single','multiple'} and len(options)<2:raise ValueError('选择题至少两个选项')
    if not isinstance(answer,dict) or set(answer)!={'values'} or not isinstance(answer['values'],list):raise ValueError('答案规则无效')
    values=answer['values']
    if any(not isinstance(v,str) or len(v)>10000 for v in values) or len(values)>50:raise ValueError('答案规则无效')
    if kind in {'single','boolean'} and not (bank and not values) and len(values)!=1:raise ValueError('单选或判断须有一个正确答案')
    if kind in {'single','multiple'} and ((not values and not bank) or len(set(values))!=len(values) or any(v not in [str(i) for i in range(len(options))] for v in values)):raise ValueError('正确选项无效')
    if kind=='boolean' and values and values[0] not in {'true','false'}:raise ValueError('判断答案无效')
    if kind=='blank' and ((not values and not bank) or any(not v.strip() for v in values)):raise ValueError('填空须设置等价答案')
    if kind=='blank':values=[v.strip() for v in values]
    if kind=='short' and not bank and not any(v.strip() for v in values):raise ValueError('简答须提供评分参考')
    points=data.get('point_ids',[])
    if not isinstance(points,list) or len(points)>20 or any(type(i) is not int for i in points) or KnowledgePoint.objects.filter(course_id=course_id,active=True,id__in=points).count()!=len(set(points)):raise ValueError('知识点无效、停用或属于他班')
    return {'kind':kind,'body':body,'score':score,'options':options,'answer':{'values':values},
            'explanation':text(data,'explanation',10000,False)},points


@api_view(['GET','POST'])
def questions(request,course_id):
    access(request.user,course_id,True)
    if request.method=='GET':
        offset,number=page(request)
        qs=owned_questions(request.user,course_id)
        query=request.GET.get('q','').strip()[:200]
        if query:qs=qs.filter(body__icontains=query)
        kind=request.GET.get('kind','')
        answer_state=request.GET.get('answer_state','')
        active=request.GET.get('active','')
        if kind and kind not in KINDS:return fail('题型筛选无效')
        if answer_state not in {'','present','missing'}:return fail('答案状态筛选无效')
        if active not in {'','true','false'}:return fail('启用状态筛选无效')
        if kind:qs=qs.filter(kind=kind)
        if answer_state=='missing':qs=qs.filter(answer__values=[])
        if answer_state=='present':qs=qs.exclude(answer__values=[])
        if active:qs=qs.filter(active=active=='true')
        for key in ('group_id','point_id'):
            value=request.GET.get(key,'')
            if value:
                if len(value)>10 or not value.isascii() or not value.isdecimal() or not 0<int(value)<=2147483647:return fail('筛选标识无效')
                qs=qs.filter(**{('group_id' if key=='group_id' else 'points__id'):int(value)})
        rows=list(qs.select_related('group').prefetch_related('points').order_by('-id')[offset:offset+21])
        return Response({'items':[{**question_snapshot(q),'active':q.active} for q in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
    try:
        values,points=validate_question(request.data,course_id,bank=True)
        check_assets(request.user,course_id,[values['body'],values['explanation'],*values['options'],*values['answer']['values']])
    except (ValueError,TypeError) as e:return fail(str(e))
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        group=None
        if request.data.get('group_id') is not None:
            if type(request.data['group_id']) is not int:return fail('题组标识无效')
            group=get_object_or_404(QuestionGroup,pk=request.data['group_id'],course_id=course_id,owner=request.user)
        q=Question.objects.create(course_id=course_id,owner=request.user,group=group,position=group.questions.count() if group else 0,**values);q.points.set(points);audit(request,course_id,'question.create',q.id)
        if group and group.source_id:touch_paper(group.source,request.user,added_question=q)
    return Response(question_snapshot(q),status=201)


def prepare_question_import(request, course_id):
    upload=request.FILES.get('file')
    if upload is None:return None,fail('请选择题库文件')
    from .question_import import MAX_FILE
    if upload.size>MAX_FILE:return None,fail('文件不能超过5 MiB')
    raw=upload.read(MAX_FILE+1)
    try:rows=parse_file(upload.name,raw)
    except ValueError as exc:return None,fail(str(exc))
    digest=hashlib.sha256(raw).hexdigest()
    names={p.name:p for p in KnowledgePoint.objects.filter(course_id=course_id,active=True)}
    prepared=[];errors=[]
    for row in rows:
        values={k:v for k,v in row.items() if k not in {'row','point_names'}}
        try:
            point_names=row['point_names']
            if len(set(point_names))!=len(point_names):raise ValueError('知识点名称重复')
            missing=[name for name in point_names if name not in names]
            if missing:raise ValueError('知识点不存在或未启用：'+'、'.join(missing[:5]))
            values['point_ids']=[names[name].id for name in point_names]
            validated,points=validate_question(values,course_id)
            prepared.append({'row':row['row'],'values':validated,'points':points})
        except (ValueError,TypeError) as exc:
            errors.append({'row':row['row'],'message':str(exc)})
    return {'rows':prepared,'errors':errors,'digest':digest,'filename':upload.name},None


@api_view(['POST'])
def question_import_preview(request,course_id):
    access(request.user,course_id,True)
    result,error=prepare_question_import(request,course_id)
    if error:return error
    return Response({'filename':result['filename'],'total':len(result['rows'])+len(result['errors']),
        'valid_count':len(result['rows']),'errors':result['errors'],
        'questions':[{'row':item['row'],'kind':item['values']['kind'],'body':item['values']['body'],
            'options':item['values']['options'],'answer':item['values']['answer'],'score':str(item['values']['score']),
            'explanation':item['values']['explanation'],'points':[p.name for p in KnowledgePoint.objects.filter(id__in=item['points']).order_by('id')]}
            for item in result['rows']],
        'can_import':not result['errors'] and bool(result['rows'])})


@api_view(['POST'])
def question_import_commit(request,course_id):
    access(request.user,course_id,True)
    key=request.data.get('request_key')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',key):return fail('导入标识无效，请重新预览')
    upload=request.FILES.get('file')
    from .question_import import MAX_FILE
    if upload is None:return fail('请选择题库文件')
    if upload.size>MAX_FILE:return fail('文件不能超过5 MiB')
    digest=hashlib.sha256(upload.read(MAX_FILE+1)).hexdigest()
    upload.seek(0)
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        access(request.user,course_id,True)
        old=QuestionImportBatch.objects.filter(course_id=course_id,actor=request.user,key=key).first()
        if old:
            if old.fingerprint!=digest:return fail('导入标识已用于其他文件，请重新预览',409)
            return Response({'imported_count':old.imported_count,'question_ids':old.question_ids,'replayed':True})
        result,error=prepare_question_import(request,course_id)
        if error:return error
        if result['errors'] or not result['rows']:return fail('导入前校验失败；题库未写入',422)
        ids=[]
        for item in result['rows']:
            question=Question.objects.create(course_id=course_id,owner=request.user,**item['values'])
            question.points.set(item['points'])
            ids.append(question.id)
        QuestionImportBatch.objects.create(course_id=course_id,actor=request.user,key=key,
            fingerprint=result['digest'],imported_count=len(ids),question_ids=ids)
        audit(request,course_id,'question.import',len(ids))
    return Response({'imported_count':len(ids),'question_ids':ids,'replayed':False},status=201)


@api_view(['GET'])
def question_import_template(request,file_format):
    if file_format not in {'xlsx','docx'}:return fail('模板格式无效',404)
    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if file_format=='xlsx' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    response=FileResponse(BytesIO(template_bytes(file_format)),content_type=content_type,
        as_attachment=True,filename=f'CampusClaw-question-bank-template.{file_format}')
    response['Cache-Control']='private, no-store'
    return response


@api_view(['PUT'])
def question_detail(request,question_id):
    original=get_object_or_404(Question,pk=question_id);access(request.user,original.course_id,True)
    if not owned_questions(request.user,original.course_id).filter(pk=question_id).exists():return fail('仅所有者可管理此题目',403)
    try:
        values,points=validate_question(request.data,original.course_id,bank=True)
        check_assets(request.user,original.course_id,[values['body'],values['explanation'],*values['options'],*values['answer']['values']])
    except (ValueError,TypeError) as e:return fail(str(e))
    if type(request.data.get('active',True)) is not bool:return fail('启用标记无效')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=original.course_id)
        q=Question.objects.select_for_update().get(pk=question_id)
        if not expected(request.data,q.revision):return fail('题目已更新，请刷新',409)
        for key,value in values.items():setattr(q,key,value)
        q.active=request.data.get('active',True);q.revision+=1;q.save();q.points.set(points)
        if q.source_id and q.paper_entries.exists():touch_paper(q.source,request.user)
        audit(request,q.course_id,'question.edit',q.id)
    return Response(question_snapshot(q))


def quiz_data(quiz,teacher):
    data={'id':quiz.id,'title':quiz.title,'status':quiz.status,'opens_at':quiz.opens_at,'closes_at':quiz.closes_at,
          'time_limit_minutes':quiz.time_limit_minutes,'max_attempts':quiz.max_attempts,'answers_at':quiz.answers_at,
          'grades_published':quiz.grades_published,'policy':quiz.policy,'revision':quiz.revision}
    if teacher:data.update(rules=quiz.rules,question_ids=quiz.question_ids,question_scores=quiz.question_scores)
    return data


@api_view(['GET','POST'])
def quizzes(request,course_id):
    m=access(request.user,course_id);teacher=m.role=='teacher'
    if request.method=='GET':
        qs=Quiz.objects.filter(course_id=course_id)
        if not teacher:qs=qs.exclude(status='draft')
        return Response([quiz_data(q,teacher) for q in qs.order_by('-id')])
    access(request.user,course_id,True)
    try:
        title=text(request.data,'title',200)
        opens=parse_datetime(str(request.data.get('opens_at','')));closes=parse_datetime(str(request.data.get('closes_at','')))
        answers=parse_datetime(str(request.data.get('answers_at','')))
        if any(d is None or timezone.is_naive(d) for d in [opens,closes,answers]) or opens>=closes or answers<closes:raise ValueError('时间须带时区，答案公布不得早于测验关闭')
        minutes=request.data.get('time_limit_minutes',30);attempts=request.data.get('max_attempts',1)
        if type(minutes) is not int or not 1<=minutes<=240 or type(attempts) is not int or not 1<=attempts<=10:raise ValueError('限时或次数无效')
        ids=request.data.get('question_ids',[])
        if not isinstance(ids,list) or len(ids)>100 or any(type(i) is not int for i in ids) or len(ids)!=len(set(ids)):raise ValueError('固定选题须为最多100个不重复题目ID')
        rules=request.data.get('rules',[])
        if not isinstance(rules,list) or (not ids and not rules) or (ids and rules) or len(rules)>20:raise ValueError('请选择固定选题或随机规则之一')
        if ids and owned_questions(request.user,course_id).filter(id__in=ids,active=True).count()!=len(ids):raise ValueError('题目不存在、停用或不属于所有者')
        scores=request.data.get('question_scores',{})
        if ids:
            if not isinstance(scores,dict) or set(scores)!={str(i) for i in ids}:raise ValueError('请在组卷时为每道题设置分值')
            scores={k:str(score_value(v,Decimal('99999.99'))) for k,v in scores.items()}
            if any(Decimal(v)<=0 for v in scores.values()):raise ValueError('组卷分值须大于零')
        elif scores:raise ValueError('随机组卷沿用旧题默认分值，不接受固定题目分值')
        for rule in rules:
            if not isinstance(rule,dict) or set(rule)-{'kind','count','point_id'} or rule.get('kind') not in KINDS or type(rule.get('count')) is not int or not 1<=rule['count']<=50:raise ValueError('组卷规则无效')
            if rule.get('point_id') is not None and (type(rule['point_id']) is not int or not KnowledgePoint.objects.filter(pk=rule['point_id'],course_id=course_id).exists()):raise ValueError('规则知识点无效')
        if sum(r['count'] for r in rules)>100:raise ValueError('每份试卷最多 100 题')
    except (ValueError,TypeError) as e:return fail(str(e))
    q=Quiz.objects.create(course_id=course_id,title=title,opens_at=opens,closes_at=closes,answers_at=answers,
        time_limit_minutes=minutes,max_attempts=attempts,rules=rules,question_ids=ids,question_scores=scores,owner=request.user)
    audit(request,course_id,'create',q.id)
    return Response(quiz_data(q,True),status=201)


@api_view(['POST'])
def publish_quiz(request,quiz_id):
    initial=get_object_or_404(Quiz,pk=quiz_id);access(request.user,initial.course_id,True)
    with transaction.atomic():
        quiz=Quiz.objects.select_for_update().get(pk=quiz_id)
        access(request.user,quiz.course_id,True)
        action=request.data.get('action','publish')
        if action=='publish':
            if quiz.status!='draft':return fail('测验已发布或关闭',409)
            if timezone.now()>=quiz.closes_at:return fail('测验关闭时间已过')
            try:paper(quiz)
            except ValueError as e:return fail(str(e))
            quiz.status='published'
        elif action in {'grades_publish','grades_withdraw'}:
            if action=='grades_publish' and (quiz.status=='draft' or quiz.attempts.filter(status='in_progress').exists() or quiz.attempts.filter(status='submitted').exclude(grading_status='finalized').exists()):
                return fail('仍有进行中或待复核答卷，无法发布完整成绩',409)
            published=action=='grades_publish'
            if quiz.grades_published==published:return Response(quiz_data(quiz,True))
            quiz.grades_published=published
        elif action=='close':quiz.status='closed'
        else:return fail('操作无效')
        quiz.revision+=1;quiz.save();audit(request,quiz.course_id,action,quiz.id)
        if action=='grades_publish':
            from .notification_service import notify_quiz_grades
            notify_quiz_grades(quiz)
    return Response(quiz_data(quiz,True))


@api_view(['GET','POST'])
def attempts(request,quiz_id):
    quiz=get_object_or_404(Quiz,pk=quiz_id);m=access(request.user,quiz.course_id)
    teacher=m.role=='teacher'
    if request.method=='GET':
        qs=quiz.attempts.select_related('quiz','student')
        if not teacher:qs=qs.filter(student=request.user)
        offset,number=page(request)
        rows=list(qs.order_by('-id')[offset:offset+21])
        return Response({'items':[{**attempt_data(a,teacher),'student_name':a.student.display_name} for a in rows[:20]],'next_page':number+1 if len(rows)>20 else None})
    if teacher:return fail('仅学生可开考',403)
    with transaction.atomic():
        quiz=Quiz.objects.select_for_update().get(pk=quiz_id)
        active=quiz.attempts.select_for_update().filter(student=request.user,status='in_progress').first()
        if active:
            if timezone.now()>=active.deadline or quiz.status=='closed':finalize(active,True)
            else:return Response(attempt_data(active))
        now=timezone.now()
        if quiz.status!='published' or now<quiz.opens_at or now>=quiz.closes_at:return fail('不在测验开放窗口内',409)
        number=quiz.attempts.filter(student=request.user).count()+1
        if number>quiz.max_attempts:return fail('测验次数已用尽',409)
        try:snapshot=paper(quiz)
        except ValueError as e:return fail(str(e),409)
        a=QuizAttempt.objects.create(quiz=quiz,student=request.user,number=number,snapshot=snapshot,
            snapshot_hash=fingerprint(sorted(snapshot,key=lambda q:q['id'])),deadline=min(quiz.closes_at,now+timedelta(minutes=quiz.time_limit_minutes)))
        audit(request,quiz.course_id,'start',a.id)
    return Response(attempt_data(a),status=201)


def accessible_attempt(request,attempt_id,teacher_only=False):
    a=get_object_or_404(QuizAttempt.objects.select_related('quiz','student'),pk=attempt_id)
    m=access(request.user,a.quiz.course_id,teacher_only)
    if m.role!='teacher' and a.student_id!=request.user.id:
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('无权查看他人答卷')
    return a,m.role=='teacher'


@api_view(['GET'])
def attempt_detail(request,attempt_id):
    a,teacher=accessible_attempt(request,attempt_id)
    return Response(attempt_data(a,teacher))


@api_view(['PUT'])
def save_answers(request,attempt_id):
    initial,teacher=accessible_attempt(request,attempt_id)
    if teacher:return fail('教师不能修改学生答案',403)
    key=request.headers.get('Idempotency-Key',request.data.get('key',''))
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',key):return fail('保存请求须有有效幂等标识')
    answers=request.data.get('answers');revision=request.data.get('expected_revision')
    digest=fingerprint({'answers':answers,'expected_revision':revision})
    with transaction.atomic():
        quiz=Quiz.objects.select_for_update().get(pk=initial.quiz_id)
        a=QuizAttempt.objects.select_for_update(of=('self',)).select_related('quiz').get(pk=attempt_id)
        receipt=QuizSaveReceipt.objects.filter(attempt=a,key=key).first()
        if receipt:
            if receipt.fingerprint!=digest:return fail('保存标识对应内容已变化',409)
            return Response({'answer_revision':receipt.revision,'saved_at':receipt.saved_at,'replayed':True})
        if a.status!='in_progress' or timezone.now()>=a.deadline or a.quiz.status=='closed':return fail('答卷已提交或到期，未保存内容不会进入交卷',409)
        if type(revision) is not int or revision!=a.answer_revision:return fail('答案版本冲突，请刷新并核对未保存内容',409)
        try:validate_answers(a,answers)
        except ValueError as e:return fail(str(e))
        a.answers=answers;a.answer_revision+=1;a.saved_at=timezone.now();a.save(update_fields=['answers','answer_revision','saved_at'])
        QuizSaveReceipt.objects.create(attempt=a,key=key,fingerprint=digest,revision=a.answer_revision,saved_at=a.saved_at)
    return Response({'answer_revision':a.answer_revision,'saved_at':a.saved_at,'replayed':False})


@api_view(['POST'])
def submit(request,attempt_id):
    initial,teacher=accessible_attempt(request,attempt_id)
    if teacher:return fail('教师不能代学生交卷',403)
    with transaction.atomic():
        quiz=Quiz.objects.select_for_update().get(pk=initial.quiz_id)
        a=QuizAttempt.objects.select_for_update(of=('self',)).select_related('quiz').get(pk=attempt_id)
        finalize(a,timezone.now()>=a.deadline or a.quiz.status=='closed')
        audit(request,a.quiz.course_id,'submit',a.id)
    return Response(attempt_data(a))


@api_view(['POST'])
def review(request,attempt_id):
    initial,_=accessible_attempt(request,attempt_id,True)
    scores=request.data.get('scores');feedback=request.data.get('feedback',{});reason=text(request.data,'reason',500)
    if not isinstance(scores,dict) or not isinstance(feedback,dict):return fail('评分格式无效')
    questions={str(q['id']):q for q in initial.snapshot}
    if set(scores)!=set(questions) or set(feedback)-set(questions) or any(not isinstance(v,str) or len(v)>5000 for v in feedback.values()):return fail('评分题目或评语无效')
    try:values={key:str(score_value(value,Decimal(questions[key]['score']))) for key,value in scores.items()}
    except ValueError as e:return fail(str(e))
    with transaction.atomic():
        quiz=Quiz.objects.select_for_update().get(pk=initial.quiz_id)
        a=QuizAttempt.objects.select_for_update(of=('self',)).select_related('quiz').get(pk=attempt_id)
        if a.status!='submitted' or not expected(request.data,a.grade_revision):return fail('答卷状态或评分版本已变化',409)
        a.scores,a.feedback=values,feedback;record_grade(a,request.user,reason)
        quiz.grades_published=False;quiz.save(update_fields=['grades_published'])
        audit(request,a.quiz.course_id,'review',a.id)
    return Response(attempt_data(a,True))


@api_view(['GET'])
def statistics(request,quiz_id):
    quiz=get_object_or_404(Quiz,pk=quiz_id);access(request.user,quiz.course_id,True)
    return Response(quiz_statistics(quiz))


@api_view(['POST'])
def upload_image(request,attempt_id,question_id):
    initial,teacher=accessible_attempt(request,attempt_id)
    if teacher:return fail('仅学生可上传自己的答案',403)
    q=next((q for q in initial.snapshot if q['id']==question_id and q['kind']=='short'),None)
    if q is None:return fail('仅本试卷简答题可上传手写图片')
    upload=request.FILES.get('file')
    if not upload or not 0<upload.size<=5*1024*1024:return fail('图片须为 5 MB 内的 PNG/JPEG/WEBP')
    try:
        with Image.open(upload) as image:
            if image.format not in {'PNG','JPEG','WEBP'} or image.width*image.height>20000000:raise ValueError()
            image.verify()
        upload.seek(0)
    except Exception:return fail('图片内容无效或尺寸过大')
    with transaction.atomic():
        quiz=Quiz.objects.select_for_update().get(pk=initial.quiz_id)
        a=QuizAttempt.objects.select_for_update(of=('self',)).select_related('quiz').get(pk=attempt_id)
        if a.status!='in_progress' or timezone.now()>=a.deadline or a.quiz.status=='closed':return fail('作答已结束',409)
        if QuizAnswerImage.objects.filter(attempt=a,question_id=question_id).count()>=10:return fail('本题上传次数已达上限')
        item=QuizAnswerImage(attempt=a,student=request.user,question_id=question_id,name=upload.name[:200],size=upload.size)
        item.file.save('answer.'+{'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}.get(upload.content_type,'png'),upload,save=True)
    return Response({'id':item.id,'name':item.name,'url':f'/api/quiz-images/{item.id}/'},status=201)


@api_view(['GET'])
def answer_image(request,image_id):
    item=get_object_or_404(QuizAnswerImage,pk=image_id)
    accessible_attempt(request,item.attempt_id)
    response=FileResponse(item.file.open('rb'),as_attachment=True,filename=item.name)
    response['Cache-Control']='no-store';response['X-Content-Type-Options']='nosniff'
    return response


@api_view(['GET','POST'])
def suggestion(request,attempt_id):
    a,_=accessible_attempt(request,attempt_id,True)
    if request.method=='GET':return Response(list(QuizSuggestion.objects.filter(attempt=a).order_by('-id').values('id','status','body','model','created_at')[:20]))
    if a.status!='submitted':return fail('请先交卷')
    from .quiz_ai import suggestion_stream, suggestion_result
    from django.http import StreamingHttpResponse
    with transaction.atomic():
        locked=QuizAttempt.objects.select_for_update(of=('self',)).select_related('quiz').get(pk=a.id)
        access(request.user,locked.quiz.course_id,True)
        if locked.status!='submitted':return fail('请先交卷',409)
        a=locked
        QuizSuggestion.objects.filter(attempt=a,status='running',created_at__lt=timezone.now()-timedelta(minutes=5)).update(status='failed',body='上次生成已中断，请重试。')
        if QuizSuggestion.objects.filter(attempt=a,status='running').exists():return fail('本答卷已有 AI 评阅正在生成，请稍后刷新',409)
        item=QuizSuggestion.objects.create(attempt=a)
        revision=locked.grade_revision
    audit(request,a.quiz.course_id,'suggest.start',item.id)
    stream=suggestion_stream(item,a,request.user,revision)
    if request.data.get('stream') is True:
        response=StreamingHttpResponse(stream,content_type='text/event-stream; charset=utf-8')
        response['Cache-Control']='no-store';response['X-Accel-Buffering']='no'
        return response
    async def consume():
        async for _ in stream:pass
    async_to_sync(consume)()
    item.refresh_from_db()
    return Response(suggestion_result(item),status=201)


@api_view(['GET'])
def comparison(request, attempt_id):
    anchor, _ = accessible_attempt(request, attempt_id, True)
    offset, number = page(request, 20)
    try:
        question_id = int(request.GET.get('question_id', anchor.snapshot[0]['id']))
    except (ValueError, TypeError, IndexError):
        return fail('题目标识无效')
    question = next((q for q in anchor.snapshot if q['id'] == question_id), None)
    if question is None:
        return fail('题目不在该冻结试卷中')
    # A question ID alone cannot prove that body, reference and score are identical.
    rows = list(QuizAttempt.objects.filter(quiz_id=anchor.quiz_id, snapshot_hash=anchor.snapshot_hash,
        status='submitted').select_related('student').order_by('submitted_at', 'pk')[offset:offset+21])
    key = str(question_id)
    return Response({'quiz_title': anchor.quiz.title, 'question': question,
        'questions': [{'id': q['id'], 'kind': q['kind'], 'score': q['score']} for q in anchor.snapshot],
        'items': [{'attempt_id': a.id, 'student_name': a.student.display_name, 'number': a.number,
            'answer': a.answers.get(key), 'score': a.scores.get(key), 'feedback': a.feedback.get(key, ''),
            'grade_revision': a.grade_revision, 'grading_status': a.grading_status} for a in rows[:20]],
        'next_page': number+1 if len(rows)>20 else None})


@api_view(['POST'])
def review_question(request, attempt_id, question_id):
    initial, _ = accessible_attempt(request, attempt_id, True)
    question = next((q for q in initial.snapshot if q['id'] == question_id), None)
    if question is None:
        return fail('题目不在该冻结试卷中')
    reason = text(request.data, 'reason', 500)
    feedback = request.data.get('feedback', '')
    if not isinstance(feedback, str) or len(feedback)>5000:
        return fail('评语最多5000字')
    try:
        value = str(score_value(request.data.get('score'), Decimal(question['score'])))
    except ValueError as e:
        return fail(str(e))
    with transaction.atomic():
        quiz = Quiz.objects.select_for_update().get(pk=initial.quiz_id)
        access(request.user, quiz.course_id, True)
        a = QuizAttempt.objects.select_for_update().get(pk=attempt_id)
        if a.status != 'submitted' or not expected(request.data, a.grade_revision):
            return fail('答卷状态或评分版本已变化，请核对最新评分后重试', 409)
        key = str(question_id)
        a.scores = {**a.scores, key: value}
        a.feedback = {**a.feedback, key: feedback}
        record_grade(a, request.user, reason)
        quiz.grades_published = False
        quiz.save(update_fields=['grades_published'])
        audit(request, quiz.course_id, 'review_question', a.id)
    return Response({'score': value, 'feedback': feedback, 'grade_revision': a.grade_revision,
        'grading_status': a.grading_status})
