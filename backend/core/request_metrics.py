"""Measure final response consumption, including sync/async stream completion and close."""
import asyncio
import logging
import threading
import time
from asgiref.sync import sync_to_async
from django.apps import apps
from django.db import DatabaseError, close_old_connections, connection
from django.utils import timezone
from .models import Course, RequestMetric

logger = logging.getLogger('campus.audit')


def course_for_request(request):
    """Only URL resolver identifiers and server-side relations; never inspect submitted data."""
    match = request.resolver_match
    if not match: return None
    ids = match.kwargs
    if 'course_id' in ids:
        return Course.objects.filter(pk=ids['course_id']).values_list('pk', flat=True).first()
    route = match.route
    mappings = {
        'thread_id': ('AgentThread', 'course_id'), 'assignment_id': ('Assignment', 'course_id'),
        'material_id': ('Material', 'course_id'), 'file_id': ('StoredFile', 'course_id'),
        'quiz_id': ('Quiz', 'course_id'), 'attempt_id': ('QuizAttempt', 'quiz__course_id'),
        'question_id': ('Question', 'course_id'), 'image_id': ('QuizAnswerImage', 'attempt__quiz__course_id'),
        'post_id': ('ForumPost', 'course_id'), 'draft_id': ('ForumDraft', 'post__course_id'),
        'snapshot_id': ('GradeSnapshot', 'course_id'), 'candidate_id': ('GraphCandidate', 'course_id'),
        'point_id': ('KnowledgePoint', 'course_id'), 'plan_id': ('ReviewPlan', 'course_id'),
        'reminder_id': ('ReviewReminder', 'plan__course_id'), 'report_id': ('DiagnosticReport', 'course_id'),
        'artifact_id': ('AgentArtifact', 'course_id'), 'run_id': ('AgentRun', 'thread__course_id'),
    }
    if 'task_id' in ids:
        model = 'MaterialIndexTask' if 'index-tasks/' in route else 'CourseworkTask'
        return apps.get_model('core', model).objects.filter(pk=ids['task_id']).values_list('course_id', flat=True).first()
    if 'version_id' in ids:
        model, field = ('DiagnosticVersion', 'report__course_id') if 'diagnostic-versions/' in route else ('SubmissionVersion', 'submission__assignment__course_id')
        return apps.get_model('core', model).objects.filter(pk=ids['version_id']).values_list(field, flat=True).first()
    for key, (model, field) in mappings.items():
        if key in ids:
            return apps.get_model('core', model).objects.filter(pk=ids[key]).values_list(field, flat=True).first()
    return None


def measure_response(request, response, started, started_at):
    match = request.resolver_match
    # Unknown URLs never become unbounded-cardinality metric labels.
    route = match.route if match else 'unmatched'
    try: course_id = course_for_request(request)
    except DatabaseError:
        course_id = None
        logger.warning('HTTP metric course attribution unavailable')
    lock = threading.Lock()
    recorded = False

    def finish(outcome):
        nonlocal recorded
        with lock:
            if recorded: return
            recorded = True
        try:
            RequestMetric.objects.create(request_id=request.request_id, course_id=course_id,
                route=route, method=request.method if request.method in {'GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','TRACE','CONNECT'} else 'OTHER', status_code=response.status_code, streaming=response.streaming,
                outcome=outcome, duration_ms=max(0, round((time.monotonic()-started)*1000)),
                started_at=started_at, finished_at=timezone.now())
        except DatabaseError:
            # Instrumentation must not fail the user's completed response or log its payload.
            logger.warning('HTTP metric persistence failed request_id=%s', request.request_id)
        finally:
            # A stream may finish on a sync-to-async worker after Django's normal
            # request thread has gone away. Do not retain its expired DB connection.
            # An enclosing caller/test transaction still owns its connection.
            if not connection.in_atomic_block: close_old_connections()

    if not response.streaming:
        finish('completed')
        return
    original = response.streaming_content
    source_iterator = response._iterator
    if response.is_async:
        async def stream():
            outcome = 'closed'
            try:
                async for chunk in original: yield chunk
                outcome = 'completed'
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except BaseException:
                outcome = 'error'
                raise
            finally:
                try:
                    if hasattr(original, 'aclose'): await original.aclose()
                    if source_iterator is not original and hasattr(source_iterator, 'aclose'): await source_iterator.aclose()
                finally: await sync_to_async(finish, thread_sensitive=True)(outcome)
    else:
        def stream():
            outcome = 'closed'
            try:
                yield from original
                outcome = 'completed'
            except GeneratorExit:
                raise
            except BaseException:
                outcome = 'error'
                raise
            finally:
                try:
                    if hasattr(original, 'close'): original.close()
                finally: finish(outcome)
    response.streaming_content = stream()
    # Django calls response.close even when a stream was never started. This fallback
    # also covers consumers that close the response without closing its iterator.
    original_close = response.close
    def close():
        try: original_close()
        finally: finish('closed')
    response.close = close
