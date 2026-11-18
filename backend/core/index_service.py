"""Durable lecture indexing. No external work while holding database locks."""
import hashlib
import asyncio
import time
import math
import mimetypes
import re
import signal
import tempfile
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from .audit import record_audit
from .models import (Course, Material, Membership, MaterialIndexTask, KnowledgeEntry,
                     KnowledgeChunk, ChunkEmbedding)

ACTIVE = ('queued', 'running')
LEASE_SECONDS = 180
RUN_SECONDS = 150


class IndexFailure(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class IndexConflict(ValueError):
    pass


def source_signature(material):
    f = material.attachment
    return {'file_id': f.pk, 'name': f.file.name, 'size': f.size, 'course_id': material.course_id}


def validate_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('请求标识须为 1–100 位字母、数字、下划线或连字符')
    return value


def teacher_can_run(task):
    return Membership.objects.filter(course_id=task.course_id, user_id=task.requested_by_id,
                                     role='teacher', user__is_active=True).exists()


def task_data(task):
    return {name: getattr(task, name) for name in (
        'id', 'material_id', 'course_id', 'status', 'phase', 'revision', 'error_code', 'error',
        'retry_of_id', 'events', 'result', 'created_at', 'started_at', 'finished_at')}


def enqueue(material, user, request_key=None, payload_hash=None, request_id='', retry_of=None):
    key = validate_key(request_key) if request_key is not None else uuid.uuid4().hex
    source = source_signature(material)
    payload_hash = payload_hash or hashlib.sha256(f'{material.pk}:{source}'.encode()).hexdigest()
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=material.course_id)
        if not Membership.objects.filter(course_id=material.course_id, user=user, role='teacher', user__is_active=True).exists():
            raise PermissionError('仅当前任课教师可建立索引')
        old = MaterialIndexTask.objects.filter(course_id=material.course_id, requested_by=user, request_key=key).first()
        if old:
            if old.payload_hash != payload_hash or old.material_id != material.pk or old.retry_of_id != (retry_of.pk if retry_of else None):
                raise IndexConflict('请求标识已用于其他内容，请使用新的请求标识')
            return old
        if MaterialIndexTask.objects.filter(material=material, status__in=ACTIVE).exists():
            raise IndexConflict('该资料已有排队或运行任务，请先查看或取消')
        task = MaterialIndexTask.objects.create(course_id=material.course_id, material=material, requested_by=user,
            request_key=key, payload_hash=payload_hash, source=source, retry_of=retry_of,
            request_id=request_id, events=[{'phase': 'queued', 'at': timezone.now().isoformat()}])
        # The old index stays stored but is unavailable until a complete replacement is committed.
        KnowledgeEntry.objects.update_or_create(material=material, defaults={'status': 'pending', 'error_message': ''})
        record_audit(actor_id=user.pk, course_id=material.course_id, action='index.enqueue',
                     object_ref=str(task.pk), status='queued', request_id=request_id)
        return task


def prepare_index(material, strategy='auto', max_chars=800, overlap=80, separators=None, phase=None):
    from .agent_runtime import extract_text, split_chunks, embed_texts
    deadline = time.monotonic() + RUN_SECONDS - 1
    if phase:
        phase('extract')
    with material.attachment.file.open('rb') as source:
        raw = source.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise IndexFailure('file_limit', '文件超过 50 MiB 索引上限')
    suffix = Path(material.attachment.original_name).suffix.lower()
    if suffix not in {'.txt', '.md', '.csv', '.pdf', '.docx'}:
        raise IndexFailure('unsupported', '此格式可下载，但不支持文本索引；请上传 TXT、MD、CSV、PDF 或 DOCX')
    try:
        with tempfile.TemporaryDirectory(prefix='campus-index-') as directory:
            path = Path(directory) / ('source' + suffix)
            path.write_bytes(raw)
            body, parser = extract_text(path, mimetypes.guess_type(material.attachment.original_name)[0] or '')
    except TimeoutError:
        raise
    except Exception as exc:
        raise IndexFailure('parse_failed', '无法解析文件，请检查文件是否损坏或加密') from exc
    if not body.strip():
        raise IndexFailure('empty', '文件没有可索引文本；扫描图片请先提供可搜索文本')
    if len(body) > 2_000_000:
        raise IndexFailure('text_limit', '提取文本超过 200 万字符，请拆分文件')
    pieces = split_chunks(body, strategy, max_chars, overlap, separators)
    if not pieces or len(pieces) > 1000:
        raise IndexFailure('chunk_limit', '切片为空或超过 1000 片，请拆分文件')
    if phase:
        phase('embed')
    vectors = []
    model = ''
    for start in range(0, len(pieces), 64):
        if phase:
            phase('embed', record=False)
        async def bounded_embedding(texts):
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                return await embed_texts(texts)
        batch, batch_model = async_to_sync(bounded_embedding)([p[0] for p in pieces[start:start + 64]])
        if model and model != batch_model:
            raise IndexFailure('embedding_invalid', '嵌入模型在任务内发生变化，请重试')
        model = batch_model
        if len(batch) != len(pieces[start:start + 64]) or any(
            not isinstance(v, list) or len(v) != 2048 or any(type(n) not in (int, float) or not math.isfinite(n) for n in v)
            for v in batch
        ):
            raise IndexFailure('embedding_invalid', '嵌入结果数量、维度或数值无效，请检查服务配置')
        vectors.extend(batch)
    return {'body': body, 'parser': parser, 'hash': hashlib.sha256(raw).hexdigest(),
            'strategy': strategy, 'pieces': pieces, 'vectors': vectors, 'model': model}


def persist_index(entry, prepared):
    """Caller owns a transaction and the relevant entry/course lock."""
    entry.chunks.all().delete()
    for i, ((text, start, end), vector) in enumerate(zip(prepared['pieces'], prepared['vectors'])):
        chunk = KnowledgeChunk.objects.create(entry=entry, chunk_index=i, chunk_text=text,
            start_offset=start, end_offset=end, status='ready')
        ChunkEmbedding.objects.create(chunk=chunk, embedding=vector, model=prepared['model'], dimensions=len(vector))
    entry.body_text, entry.parser, entry.content_hash = prepared['body'], prepared['parser'], prepared['hash']
    entry.chunk_strategy, entry.status = prepared['strategy'], 'ready'
    entry.error_message, entry.indexed_at = '', timezone.now()
    entry.save()


def transition(task, status, *, error_code='', error=''):
    task.status, task.phase = status, status
    task.error_code, task.error = error_code, error
    task.revision += 1
    task.finished_at = timezone.now()
    task.events = [*task.events, {'phase': status, 'at': task.finished_at.isoformat()}]
    task.save()
    if status != 'succeeded':
        KnowledgeEntry.objects.filter(material_id=task.material_id, material__course_id=task.course_id).update(status='failed', error_message=error)
    record_audit(actor_id=task.requested_by_id, course_id=task.course_id, action='index.' + status,
                 object_ref=str(task.pk), status=error_code or status, request_id=task.request_id)


def claim(task_id):
    # Every mutation takes Course -> task -> entry. No network under these locks.
    course_id = MaterialIndexTask.objects.filter(pk=task_id).values_list('course_id', flat=True).first()
    if not course_id:
        return None
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course_id)
        task = MaterialIndexTask.objects.select_for_update().select_related('material__attachment').get(pk=task_id)
        if task.status != 'queued':
            return None
        if not teacher_can_run(task) or source_signature(task.material) != task.source:
            transition(task, 'failed', error_code='permission_or_source', error='发起教师权限或资料归属已变化，请任课教师重新提交')
            return None
        task.status, task.phase = 'running', 'read_source'
        task.started_at = timezone.now()
        task.lease_until = task.started_at + timedelta(seconds=LEASE_SECONDS)
        task.lease_token = uuid.uuid4()
        task.revision += 1
        task.events = [*task.events, {'phase': 'read_source', 'at': task.started_at.isoformat()}]
        task.save()
        return task


def step(task, phase, record=True):
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=task.course_id)
        current = MaterialIndexTask.objects.select_for_update().get(pk=task.pk)
        if (current.status != 'running' or current.lease_token != task.lease_token or current.lease_until <= timezone.now()
                or not teacher_can_run(current)):
            raise IndexFailure('interrupted', '任务已取消、超时或发起教师权限已撤销')
        if record:
            current.phase = phase
            current.revision += 1
            current.events = [*current.events, {'phase': phase, 'at': timezone.now().isoformat()}]
            current.save(update_fields=['phase', 'revision', 'events'])


@contextmanager
def execution_deadline():
    # Dedicated Docker worker runs on Linux in its main thread, bounding PDF parsing too.
    def expired(*_):
        raise TimeoutError('index execution deadline')
    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, RUN_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def safe_error(exc):
    if isinstance(exc, IndexFailure):
        return exc.code, str(exc)
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return 'timeout', '索引执行超时，请拆分资料或稍后重试'
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 403):
            return 'dependency_auth', '嵌入服务认证失败，请教师检查服务配置'
        if exc.response.status_code == 429:
            return 'dependency_rate_limit', '嵌入服务限流，请稍后重试'
    if isinstance(exc, OSError):
        return 'file_unavailable', '无法读取资料文件，请检查文件存储'
    return 'dependency_failed', '索引未完成，请教师检查嵌入服务配置后重试'


def process(task_id):
    task = claim(task_id)
    if task is None:
        return False
    try:
        with execution_deadline():
            prepared = prepare_index(task.material, phase=lambda phase, record=True: step(task, phase, record))
        error_code, error = '', ''
    except Exception as exc:
        prepared = None
        error_code, error = safe_error(exc)
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=task.course_id)
        current = MaterialIndexTask.objects.select_for_update().select_related('material__attachment').get(pk=task.pk)
        if current.status != 'running' or current.lease_token != task.lease_token:
            return False  # Cancelled or recovered: ignore late results, including failures.
        if current.lease_until <= timezone.now():
            prepared = None; error_code, error = 'timeout', '任务租约已失效，请重试'
        if not teacher_can_run(current) or source_signature(current.material) != current.source:
            prepared = None; error_code, error = 'permission_or_source', '发起教师权限或资料归属已变化，结果未生效'
        if prepared is None:
            transition(current, 'failed', error_code=error_code, error=error)
        else:
            # A failed transaction preserves the complete previous index.
            try:
                with transaction.atomic():
                    entry = KnowledgeEntry.objects.select_for_update().get(material=current.material)
                    persist_index(entry, prepared)
                    if current.lease_until <= timezone.now():
                        raise IndexFailure('timeout', '保存期间任务租约已过期，结果未生效，请重试')
                    if not teacher_can_run(current):
                        raise IndexFailure('permission_or_source', '保存期间发起教师权限已撤销，结果未生效')
            except Exception as exc:
                code, message = (exc.code, str(exc)) if isinstance(exc, IndexFailure) else ('persist_failed', '保存索引失败，原索引记录保留，请重试')
                transition(current, 'failed', error_code=code, error=message)
            else:
                current.result = {'chunks': len(prepared['pieces']), 'content_hash': prepared['hash'], 'model': prepared['model']}
                transition(current, 'succeeded')
    return True


def recover_expired():
    ids = list(MaterialIndexTask.objects.filter(status='running', lease_until__lte=timezone.now()).values_list('id', flat=True)[:100])
    for task_id in ids:
        course_id = MaterialIndexTask.objects.get(pk=task_id).course_id
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course_id)
            task = MaterialIndexTask.objects.select_for_update().get(pk=task_id)
            if task.status == 'running' and task.lease_until <= timezone.now():
                transition(task, 'failed', error_code='worker_interrupted', error='执行中断或超时，请任课教师重试')
    return len(ids)


def scan_index_tasks(limit=5):
    recover_expired()
    return sum(int(process(pk)) for pk in list(MaterialIndexTask.objects.filter(status='queued').order_by('id').values_list('id', flat=True)[:limit]))
