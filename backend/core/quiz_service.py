import hashlib
import json
import random
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from .models import Question,Quiz,QuizAttempt,QuizGradeRevision,QuizAnswerImage

KINDS={'single','multiple','boolean','blank','short'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def question_snapshot(q):
    return {'id':q.id,'revision':q.revision,'kind':q.kind,'body':q.body,'options':q.options,
            'answer':q.answer,'explanation':q.explanation,'score':str(q.score),
            'points':[{'id':p.id,'name':p.name} for p in q.points.all()]}


def paper(quiz):
    selected=[];used=set()
    for rule in quiz.rules:
        candidates=Question.objects.filter(course_id=quiz.course_id,active=True,kind=rule['kind']).exclude(id__in=used)
        if rule.get('point_id'):
            candidates=candidates.filter(points__id=rule['point_id'])
        pool=list(candidates.select_for_update().prefetch_related('points').order_by('id'))
        if len(pool)<rule['count']:
            raise ValueError('候选题数量不足，请补充题目或调整规则')
        chosen=random.SystemRandom().sample(pool,rule['count'])
        used.update(q.id for q in chosen);selected.extend(question_snapshot(q) for q in chosen)
    random.SystemRandom().shuffle(selected)
    return selected


def validate_answers(attempt,answers):
    if not isinstance(answers,dict) or len(answers)>len(attempt.snapshot):
        raise ValueError('答案必须是题目 ID 到作答的对象')
    questions={str(q['id']):q for q in attempt.snapshot}
    for key,value in answers.items():
        q=questions.get(key)
        if q is None:raise ValueError('答案包含本试卷外题目')
        if q['kind'] in {'single','boolean'}:
            allowed=['true','false'] if q['kind']=='boolean' else [str(i) for i in range(len(q['options']))]
            if value is not None and value not in allowed:raise ValueError('选项无效')
        elif q['kind']=='multiple':
            if not isinstance(value,list) or len(value)>len(q['options']) or any(type(i) is not str or i not in [str(j) for j in range(len(q['options']))] for i in value) or len(value)!=len(set(value)):
                raise ValueError('多选答案无效')
        elif q['kind']=='blank':
            if not isinstance(value,str) or len(value)>2000:raise ValueError('填空答案无效')
        else:
            if not isinstance(value,dict) or set(value)-{'text','image_ids'} or not isinstance(value.get('text',''),str) or len(value.get('text',''))>10000:
                raise ValueError('简答答案无效')
            images=value.get('image_ids',[])
            if not isinstance(images,list) or len(images)>3 or any(type(i) is not int for i in images) or QuizAnswerImage.objects.filter(attempt=attempt,question_id=q['id'],id__in=images,student_id=attempt.student_id).count()!=len(set(images)):
                raise ValueError('手写图片不属于当前答案')


def objective_grade(attempt):
    scores={}
    for q in attempt.snapshot:
        value=attempt.answers.get(str(q['id']))
        if q['kind']=='short':scores[str(q['id'])]=None;continue
        expected=q['answer']['values']
        if q['kind']=='multiple':correct=isinstance(value,list) and set(value)==set(expected)
        elif q['kind']=='blank':correct=isinstance(value,str) and value.strip() in expected
        else:correct=value in expected
        scores[str(q['id'])]=q['score'] if correct else '0.00'
    return scores


def record_grade(attempt,actor,reason):
    attempt.grade_revision+=1
    attempt.grading_status='finalized' if all(v is not None for v in attempt.scores.values()) else 'awaiting_review'
    attempt.save()
    QuizGradeRevision.objects.create(attempt=attempt,revision=attempt.grade_revision,scores=attempt.scores,
        feedback=attempt.feedback,status=attempt.grading_status,actor=actor,reason=reason)


def finalize(attempt,automatic=False):
    if attempt.status=='submitted':return
    now=timezone.now()
    attempt.status='submitted';attempt.submitted_at=now
    attempt.submission_basis='deadline_saved_answers' if automatic else 'manual_saved_answers'
    attempt.scores=objective_grade(attempt)
    record_grade(attempt,None,'按冻结规则评分，简答待教师复核')


def expire_attempts():
    count=0
    from django.db.models import Q
    for aid,quiz_id in QuizAttempt.objects.filter(Q(deadline__lte=timezone.now())|Q(quiz__status='closed'),status='in_progress').values_list('id','quiz_id').iterator():
        with transaction.atomic():
            quiz=Quiz.objects.select_for_update().get(pk=quiz_id)
            attempt=QuizAttempt.objects.select_for_update().get(pk=aid)
            if attempt.status=='in_progress' and (timezone.now()>=attempt.deadline or quiz.status=='closed'):
                finalize(attempt,True);count+=1
    return count


def attempt_data(attempt,teacher=False):
    released=teacher or (attempt.status=='submitted' and timezone.now()>=attempt.quiz.answers_at)
    paper_data=[q if released else {k:v for k,v in q.items() if k not in {'answer','explanation'}} for q in attempt.snapshot]
    data={'id':attempt.id,'quiz_id':attempt.quiz_id,'student_id':attempt.student_id,'number':attempt.number,
          'status':attempt.status,'paper':paper_data,'snapshot_hash':attempt.snapshot_hash,'answers':attempt.answers,
          'answer_revision':attempt.answer_revision,'saved_at':attempt.saved_at,'started_at':attempt.started_at,
          'deadline':attempt.deadline,'server_now':timezone.now(),'submitted_at':attempt.submitted_at,
          'submission_basis':attempt.submission_basis,'grading_status':attempt.grading_status}
    if teacher or (attempt.quiz.grades_published and attempt.grading_status=='finalized'):
        data.update(scores=attempt.scores,feedback=attempt.feedback,grade_revision=attempt.grade_revision,
            total=str(sum(Decimal(v) for v in attempt.scores.values() if v is not None)) if attempt.grading_status=='finalized' else None)
    if teacher:
        data['grade_history']=list(attempt.grade_history.order_by('-revision').values('revision','scores','feedback','status','reason','actor_id','created_at'))
    return data


def quiz_statistics(quiz):
    rows=list(quiz.attempts.filter(status='submitted',grading_status='finalized').order_by('student_id','submitted_at','id'))
    selected={}
    for a in rows:
        total=sum(Decimal(v) for v in a.scores.values())
        if a.student_id not in selected or total>=selected[a.student_id][0]:selected[a.student_id]=(total,a)
    groups={}
    for total,a in selected.values():groups.setdefault(a.snapshot_hash,[]).append((total,a))
    result=[]
    for snapshot_hash,values in groups.items():
        values.sort(key=lambda row:(-row[0],row[1].student_id))
        n=len(values);g=int(Decimal('.27')*n)
        valid=n>=8 and g>=2 and 2*g<=n and len({total for total,_ in values})>1
        questions=[]
        for q in values[0][1].snapshot:
            ratios=[Decimal(a.scores[str(q['id'])])/Decimal(q['score']) for _,a in values]
            questions.append({'question_id':q['id'],'revision':q['revision'],'sample_size':n,
                'full_correct_rate':str(Decimal(sum(r==1 for r in ratios))/n),
                'mean_score_rate':str(sum(ratios)/n),
                'discrimination':str(sum(ratios[:g])/g-sum(ratios[-g:])/g) if valid else None})
        result.append({'snapshot_hash':snapshot_hash,'sample_size':n,'group_size':g,'questions':questions})
    return {'groups':result,'policy':'highest_finalized_then_latest; same snapshot; ties by student_id',
            'pending_attempts':quiz.attempts.filter(status='submitted').exclude(grading_status='finalized').count()}
