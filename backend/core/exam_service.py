"""Owner-private exam recognition drafts; no model writes to the published bank."""
import asyncio
import base64
import hashlib
import json
import re
import uuid
import zipfile
import signal
from contextlib import aclosing, contextmanager
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image, ImageOps
from docx import Document
from lxml import etree
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from .models import Course, Membership, ExamSource, QuestionAsset, QuestionGroup, Question, ExamPaperEntry, ExamPaperRevision


class PaperConflict(ValueError):
    pass


def live_paper(source):
    """Read-only reconstruction from bank rows, including their optimistic revisions."""
    groups = {}
    for entry in source.entries.select_related('question__group').order_by('position'):
        q = entry.question
        g = q.group
        if g.id not in groups:
            groups[g.id] = {'group_id': g.id, 'group_revision': g.revision, 'title': g.title,
                            'material': g.material, 'source_units': g.source_units, 'questions': []}
        groups[g.id]['questions'].append({'question_id': q.id, 'question_revision': q.revision,
            'kind': q.kind, 'body': q.body, 'options': q.options, 'answer': q.answer,
            'explanation': q.explanation, 'source_units': q.source_units})
    return {'groups': list(groups.values())}


def remember_paper(source, user, draft):
    ExamPaperRevision.objects.create(source=source, revision=source.revision, actor=user,
                                     content={'name': source.name, 'draft': draft})


def touch_paper(source, user, added_question=None):
    """Bank edits and paper edits share one revision boundary and ordered membership."""
    source=ExamSource.objects.select_for_update().get(pk=source.pk)
    if source.status!='committed':return
    questions=[e.question for e in source.entries.select_related('question')]
    if added_question is not None:
        added_question.source=source;added_question.source_units=added_question.group.source_units
        added_question.save(update_fields=['source','source_units'])
        questions.append(added_question)
    group_order=list(dict.fromkeys(q.group_id for q in questions))
    questions.sort(key=lambda q:(group_order.index(q.group_id),q.position,q.id))
    source.entries.all().delete()
    for position,q in enumerate(questions):ExamPaperEntry.objects.create(source=source,question=q,position=position)
    source.mapping=[{'group_id':q.group_id,'question_id':q.id,'source_units':q.source_units} for q in questions]
    source.revision+=1;source.save(update_fields=['mapping','revision'])
    remember_paper(source,user,live_paper(source))
from .agent_runtime import model_stream
from .model_telemetry import model_context

MAX_FILE = 20 * 1024 * 1024
MAX_UNITS = 12
ASSET = re.compile(r'\{\{asset:(\d+)\}\}')
KINDS = {'single', 'multiple', 'boolean', 'blank', 'short'}


@contextmanager
def source_deadline():
    def expired(*_):
        raise TimeoutError('Exam source deadline')
    previous=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,360)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous)


def owned_questions(user, course_id):
    return Question.objects.filter(course_id=course_id).filter(Q(owner=user) | Q(owner__isnull=True, course__created_by=user))


def teacher(user, course_id):
    if not Membership.objects.filter(course_id=course_id, user=user, role='teacher', user__is_active=True).exists():
        raise PermissionDenied('仅本课程教师可访问题库')


def own_source(user, source):
    teacher(user, source.course_id)
    if source.owner_id != user.id:
        raise PermissionDenied('仅所有者可管理此试卷')


def asset_ids(*texts):
    return sorted({int(m) for text in texts for m in ASSET.findall(text)})


def check_assets(user, course_id, texts, *, pages=False):
    ids = asset_ids(*texts)
    rows = QuestionAsset.objects.filter(id__in=ids, course_id=course_id, owner=user)
    if not pages:
        rows = rows.filter(is_page=False)
    if rows.count() != len(ids):
        raise ValueError('配图不存在、不属于所有者，或仍引用原卷整页；请裁剪或另传题目配图')
    # Only controlled assets, never arbitrary external image URLs or HTML images.
    if any(re.search(r'!\[[^\]]*\]\s*\(|<\s*img\b', text, re.I) for text in texts):
        raise ValueError('请通过配图上传插入图片，不能使用外部图片链接')
    return ids


def save_image(source, raw, label, *, is_page=False):
    with Image.open(BytesIO(raw)) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError('图片超过 2000 万像素')
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((2000, 2600))
        result = BytesIO()
        image.save(result, 'PNG')
    data = result.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    old = QuestionAsset.objects.filter(source=source, owner_id=source.owner_id, digest=digest, is_page=is_page).first()
    if old:
        return old
    row = QuestionAsset(course_id=source.course_id, owner_id=source.owner_id, source=source,
                        digest=digest, label=label[:200], is_page=is_page)
    row.file.save(f'{uuid.uuid4().hex}.png', ContentFile(data), save=True)
    return row


def extract_source(source):
    suffix = Path(source.file.name).suffix.lower()
    with source.file.open('rb') as stream:
        raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError('文件超过 20 MiB')
    units = []
    if suffix in {'.png', '.jpg', '.jpeg', '.webp'}:
        image = save_image(source, raw, '原始图片（仅教师）', is_page=True)
        units = [{'id': 1, 'label': '图片 1', 'text': '', 'asset_ids': [image.id]}]
    elif suffix == '.txt':
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('TXT 请保存为 UTF-8 编码') from None
        if not text.strip() or len(text) > 100000:
            raise ValueError('文本为空或超过 10 万字')
        units = [{'id': i // 10000 + 1, 'label': f'文本段 {i // 10000 + 1}', 'text': text[i:i+10000], 'asset_ids': []}
                 for i in range(0, len(text), 10000)]
    elif suffix == '.pdf':
        with fitz.open(stream=raw, filetype='pdf') as doc:
            if doc.needs_pass or not 1 <= len(doc) <= MAX_UNITS:
                raise ValueError('PDF 须未加密且为 1–12 页；请先拆分长试卷')
            for i, page in enumerate(doc):
                if page.rect.width <= 0 or page.rect.height <= 0:
                    raise ValueError('PDF 页面尺寸无效')
                scale = min(1.6, 2000 / page.rect.width, 2600 / page.rect.height)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = save_image(source, pixmap.tobytes('png'), f'原卷第 {i+1} 页（仅教师）', is_page=True)
                text = page.get_text()
                if len(text) > 20000:
                    raise ValueError('单页文字超过 2 万字，请拆分资料')
                units.append({'id': i+1, 'label': f'第 {i+1} 页', 'text': text, 'asset_ids': [image.id]})
    elif suffix == '.docx':
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(i.file_size for i in entries) > 60*1024*1024:
                raise ValueError('DOCX 解压超过 60 MiB 或条目过多')
            if any('vbaProject' in i.filename or 'embeddings/' in i.filename for i in entries):
                raise ValueError('DOCX 含宏或嵌入对象，请另存为普通试卷文档')
            for item in entries:
                if item.filename.endswith('.rels') and b'TargetMode="External"' in archive.read(item):
                    raise ValueError('DOCX 含外部关系，请移除外链后上传')
        document = Document(BytesIO(raw))
        text_parts, pictures = [], []
        image_count = 0
        for index, block in enumerate(document.element.body, 1):
            text = '\n'.join(block.xpath('.//w:t/text()'))
            for drawing in block.xpath('.//a:blip'):
                relation = drawing.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                part = document.part.related_parts.get(relation)
                if part is None:
                    raise ValueError('DOCX 图片关系缺失')
                image_count += 1
                if image_count > 30:
                    raise ValueError('DOCX 最多 30 张内嵌图片')
                image = save_image(source, part.blob, f'文档块 {index} 图片 {image_count}')
                pictures.append(image.id)
                text += f'\n{{{{asset:{image.id}}}}}'
            for formula in block.xpath('.//m:oMath'):
                text += '\n[Word 原生公式，需校对转换]\n'+etree.tostring(formula,encoding='unicode')
            if text.strip():
                text_parts.append(f'[文档块 {index}]\n{text}')
        joined = '\n\n'.join(text_parts)
        if not joined.strip() or len(joined) > 100000:
            raise ValueError('DOCX 内容为空或超过 10 万字')
        # Block labels preserve source positions; no invented Word page numbers.
        units = [{'id': 1, 'label': 'Word 文档（按文档块定位）', 'text': joined, 'asset_ids': pictures}]
    else:
        raise ValueError('支持 TXT、PNG/JPEG/WebP、DOCX、PDF；旧版 Word 请先转换')
    if len(units) > MAX_UNITS or sum(len(u['text']) for u in units) > 100000:
        raise ValueError('资料超过 12 个单元或 10 万字，请拆分后上传')
    if sum(len(u['asset_ids']) for u in units) > 30:
        raise ValueError('最多处理 30 张图片，请拆分后上传')
    return units


def clean_draft(data, units):
    if not isinstance(data, dict) or set(data) != {'groups'} or not isinstance(data['groups'], list) or not 1 <= len(data['groups']) <= 50:
        raise ValueError('草稿须包含 1–50 个题组')
    allowed_units = {u['id'] for u in units}
    count = 0
    result = []
    def bounded(value, maximum, label):
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError(label+'格式或长度无效')
        return value
    def locations(value):
        if not isinstance(value, list) or not value or len(value)>12 or any(type(i) is not int or i not in allowed_units for i in value):
            raise ValueError('请为每组和每题选择有效来源单元')
        return sorted(set(value))
    for group in data['groups']:
        if not isinstance(group, dict) or not isinstance(group.get('questions'), list) or not group['questions']:
            raise ValueError('题组至少包含一道题')
        out = {'title': bounded(group.get('title', ''), 200, '题组标题'),
               'material': bounded(group.get('material', ''), 30000, '共享材料'),
               'source_units': locations(group.get('source_units')), 'questions': []}
        for field in ('group_id', 'group_revision'):
            if field in group:
                if type(group[field]) is not int or group[field] <= 0:raise ValueError('题组版本标识无效')
                out[field] = group[field]
        for question in group['questions']:
            count += 1
            if count > 100 or not isinstance(question, dict) or question.get('kind') not in KINDS:
                raise ValueError('草稿最多 100 题，题型须为单选、多选、判断、单空或简答')
            options = question.get('options', [])
            answer = question.get('answer', {'values': []})
            if not isinstance(options, list) or len(options)>10 or any(not isinstance(v,str) or len(v)>2000 for v in options):
                raise ValueError('选项格式无效')
            if not isinstance(answer, dict) or set(answer)!={'values'} or not isinstance(answer['values'],list) or len(answer['values'])>50 or any(not isinstance(v,str) or len(v)>10000 for v in answer['values']):
                raise ValueError('答案格式无效')
            out['questions'].append({'kind': question['kind'], 'body': bounded(question.get('body',''),20000,'题干'),
                'options': options, 'answer': answer,
                'explanation': bounded(question.get('explanation',''),10000,'解析'),
                'source_units': locations(question.get('source_units'))})
            for field in ('question_id', 'question_revision'):
                if field in question:
                    if type(question[field]) is not int or question[field] <= 0:raise ValueError('题目版本标识无效')
                    out['questions'][-1][field] = question[field]
        result.append(out)
    return {'groups': result}


async def recognize(source, units):
    skill = (Path(__file__).parent/'teaching_skills'/'exam-bank'/'SKILL.md').read_text(encoding='utf-8')
    content = [{'type':'text','text': json.dumps({'units': units}, ensure_ascii=False)}]
    for aid in dict.fromkeys(i for u in units for i in u['asset_ids']):
        asset = await asyncio.to_thread(QuestionAsset.objects.get, pk=aid)
        def read_asset():
            with asset.file.open('rb') as f:
                return base64.b64encode(f.read()).decode('ascii')
        encoded = await asyncio.to_thread(read_asset)
        content.extend([{'type':'text','text':f'下图 asset_id={aid}；is_page={asset.is_page}'},
                        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+encoded}}])
    messages = [{'role':'system','content':skill}, {'role':'user','content':content}]
    output = ''
    model = ''
    with model_context(course_id=source.course_id,actor_id=source.owner_id,request_id=f'exam-{source.id}',skill_id='exam-bank@1.0.0'):
        async with asyncio.timeout(240):
            async with aclosing(model_stream(messages)) as stream:
                async for delta, model in stream:
                    if not isinstance(delta,str):
                        raise ValueError('识别只允许输出草稿，不能调用工具')
                    output += delta
                    if len(output)>180000:
                        raise ValueError('识别结果过长，请拆分试卷')
    if output.startswith('```'):
        output = re.sub(r'^```(?:json)?\s*|\s*```$', '', output.strip())
    try:
        data = json.loads(output)
    except (ValueError, TypeError):
        raise ValueError('模型未返回完整结构化草稿；可重试或人工整理') from None
    if not isinstance(data, dict):
        raise ValueError('模型草稿格式无效')
    crops = data.pop('crops', [])
    if not isinstance(crops,list) or len(crops)>50:
        raise ValueError('配图裁剪数量或格式无效')
    replacements = {}
    allowed = {i for u in units for i in u['asset_ids']}
    for crop in crops:
        if not isinstance(crop,dict) or type(crop.get('id')) is not int or crop['id'] in replacements or crop.get('asset_id') not in allowed:
            raise ValueError('配图裁剪来源无效')
        box = crop.get('box')
        if not isinstance(box,list) or len(box)!=4 or any(type(v) is not int or not 0<=v<=1000 for v in box) or box[0]>=box[2] or box[1]>=box[3]:
            raise ValueError('裁剪区域无效')
        def crop_image():
            asset = QuestionAsset.objects.get(pk=crop['asset_id'],source=source)
            with asset.file.open('rb') as f, Image.open(f) as image:
                coords = (box[0]*image.width//1000,box[1]*image.height//1000,box[2]*image.width//1000,box[3]*image.height//1000)
                if coords[0]>=coords[2] or coords[1]>=coords[3]:
                    raise ValueError('裁剪区域太小')
                out = BytesIO();image.crop(coords).save(out,'PNG')
            return save_image(source,out.getvalue(),'识别配图（请核对裁剪范围）')
        new_asset = await asyncio.to_thread(crop_image)
        replacements[crop['id']] = new_asset.id
    def replace(value):
        if isinstance(value,str):
            return re.sub(r'\{\{crop:(\d+)\}\}',lambda m:'{{asset:'+str(replacements[int(m[1])])+'}}',value)
        if isinstance(value,list):return [replace(v) for v in value]
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        return value
    try:
        draft=clean_draft(replace(data),units)
        # This agent's scope is question extraction. Never promote invented answer keys.
        # Teachers may add answers explicitly in the source editor or bank afterwards.
        for group in draft['groups']:
            for question in group['questions']:
                question['answer']={'values':[]}
                question['explanation']=''
        return draft, model
    except KeyError:
        raise ValueError('配图引用缺失；请重新识别或人工整理') from None


def scan_sources(source_id=None):
    # Expired runs never resume implicitly; late results cannot overwrite a newer edit.
    now = timezone.now()
    ExamSource.objects.filter(status='running',lease_until__lte=now).update(status='failed',error='识别任务中断或超时，请显式重试或人工整理',lease_token='')
    with transaction.atomic():
        rows=ExamSource.objects.select_for_update(skip_locked=True).filter(status='queued')
        if source_id is not None:rows=rows.filter(pk=source_id)
        source = rows.order_by('id').first()
        if source is None:return 0
        token = uuid.uuid4().hex
        source.status='running';source.lease_token=token;source.lease_until=now+timedelta(minutes=8);source.error=''
        source.save(update_fields=['status','lease_token','lease_until','error'])
    try:
        teacher(source.owner,source.course_id)
        with source_deadline():
            units = extract_source(source)
            ExamSource.objects.filter(pk=source.pk,status='running',lease_token=token).update(units=units)
            draft, model = asyncio.run(recognize(source,units))
        teacher(source.owner,source.course_id)
        ExamSource.objects.filter(pk=source.pk,status='running',lease_token=token,lease_until__gt=timezone.now()).update(
            status='ready',draft=draft,model=model,revision=source.revision+1,lease_token='')
    except Exception as exc:
        # Controlled messages only. Never persist model output, parser internals or credentials in errors.
        code = re.search(r'HTTP (\d{3})',str(exc))
        message = (str(exc) if type(exc) is ValueError else
                   f'模型服务暂时不可用（HTTP {code[1]}），可重试；原卷已保留' if code else
                   '识别超时，可拆分原卷后重试或人工整理' if isinstance(exc,TimeoutError) else
                   '模型连接未完成，可重试；原卷和已保存编辑均保留')
        ExamSource.objects.filter(pk=source.pk,status='running',lease_token=token).update(status='failed',error=message[:200],lease_token='')
    return 1


def commit_source(source, user):
    from .quiz_views import validate_question
    if source.status=='committed':return source.mapping
    if source.status not in {'ready','failed'}:
        raise ValueError('请先完成识别或转人工整理')
    draft = clean_draft(source.draft, source.units)
    prepared = []
    for group in draft['groups']:
        if not group['title'].strip():raise ValueError('请填写题组标题')
        check_assets(user,source.course_id,[group['material']])
        questions = []
        for question in group['questions']:
            values, points = validate_question({**question,'point_ids':[]},source.course_id,bank=True)
            check_assets(user,source.course_id,[values['body'],values['explanation'],*values['options'],*values['answer']['values']])
            questions.append((values,question['source_units']))
        prepared.append((group,questions))
    mapping = []
    for group, questions in prepared:
        row = QuestionGroup.objects.create(course_id=source.course_id,owner=user,source=source,
            title=group['title'],material=group['material'],source_units=group['source_units'])
        for position,(values,units) in enumerate(questions):
            question = Question.objects.create(course_id=source.course_id,owner=user,source=source,group=row,
                                               source_units=units,position=position,**values)
            mapping.append({'group_id':row.id,'question_id':question.id,'source_units':units})
            ExamPaperEntry.objects.create(source=source, question=question, position=len(mapping)-1)
    source.mapping=mapping;source.status='committed';source.revision+=1;source.save(update_fields=['mapping','status','revision'])
    remember_paper(source, user, live_paper(source))
    return mapping


def update_paper(source, user, data, versions, group_versions):
    """Caller locks course and source. Validate all changes before writing any bank row."""
    from .quiz_views import validate_question
    draft = clean_draft(data, source.units)
    existing = {e.question_id: e.question for e in source.entries.select_related('question')}
    if versions != {str(q.id): q.revision for q in existing.values()}:
        raise PaperConflict('题库内容已更新，请重新读取整卷后再保存')
    known_groups = {q.group_id for q in existing.values()}
    if group_versions != {str(g.id):g.revision for g in QuestionGroup.objects.filter(pk__in=known_groups)}:
        raise PaperConflict('题组材料已更新，请重新读取整卷后再保存')
    seen_q, seen_g, prepared = set(), set(), []
    for group in draft['groups']:
        if not group['title'].strip():raise ValueError('请填写题组标题')
        gid = group.get('group_id')
        row = None
        if gid is not None:
            if gid not in known_groups or gid in seen_g:raise ValueError('题组不属于这份试卷或重复')
            row = QuestionGroup.objects.select_for_update().get(pk=gid, source=source, owner=user)
            if row.revision != group.get('group_revision'):raise PaperConflict('题组已在其他页面修改，请重新读取整卷')
            seen_g.add(gid)
        check_assets(user, source.course_id, [group['material']])
        questions = []
        for q in group['questions']:
            qid = q.get('question_id')
            old = None
            if qid is not None:
                if qid not in existing or qid in seen_q:raise ValueError('题目不属于这份试卷或重复')
                old = existing[qid]
                if old.owner_id != user.id or old.source_id != source.id:raise ValueError('题目归属不一致')
                if old.revision != q.get('question_revision'):raise PaperConflict('题目已在题库修改，请重新读取整卷，避免覆盖')
                seen_q.add(qid)
            values, _ = validate_question({**q, 'point_ids': []}, source.course_id, bank=True)
            check_assets(user, source.course_id, [values['body'], values['explanation'], *values['options'], *values['answer']['values']])
            questions.append((q, old, values))
        prepared.append((group, row, questions))
    # Soft remove, preserving historical question IDs and immutable attempt snapshots.
    Question.objects.filter(pk__in=set(existing)-seen_q).update(active=False)
    QuestionGroup.objects.filter(pk__in=known_groups-seen_g).update(active=False)
    source.entries.all().delete()
    mapping = []
    for group, row, questions in prepared:
        if row is None:
            row = QuestionGroup(course_id=source.course_id, owner=user, source=source)
        else:
            row.revision += 1
        row.title=group['title'];row.material=group['material'];row.source_units=group['source_units'];row.save()
        for position, (q, old, values) in enumerate(questions):
            question = old or Question(course_id=source.course_id, owner=user, source=source)
            for key, value in values.items():setattr(question, key, value)
            if old:question.revision+=1
            question.group=row;question.position=position;question.source_units=q['source_units'];question.save()
            ExamPaperEntry.objects.create(source=source, question=question, position=len(mapping))
            mapping.append({'group_id':row.id,'question_id':question.id,'source_units':q['source_units']})
    source.mapping=mapping;source.revision+=1;source.save(update_fields=['mapping','revision'])
    remember_paper(source, user, live_paper(source))
