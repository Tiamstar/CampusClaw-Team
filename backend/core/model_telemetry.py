"""Provider-reported usage only. Never store prompts, response text, URLs or secrets."""
import asyncio
import os
import time
from contextlib import contextmanager, aclosing
from contextvars import ContextVar
from asgiref.sync import sync_to_async
from django.utils import timezone
from .models import ModelCall
from .audit import record_audit

call_context = ContextVar('model_call_context', default={})
usage_sink = ContextVar('model_usage_sink', default=None)


@contextmanager
def model_context(**metadata):
    allowed = {'course_id', 'actor_id', 'task_id', 'request_id', 'skill_id', 'config_revision'}
    token = call_context.set({**call_context.get(), **{k:v for k,v in metadata.items() if k in allowed}})
    try: yield
    finally: call_context.reset(token)


class Usage:
    def __init__(self):
        self.values = {}; self.invalid = False

    def count(self, key, value):
        if value is None: return
        if type(value) is not int or not 0 <= value <= 10**12:
            self.invalid = True; return
        # Stream snapshots are cumulative. Repeated snapshots are not additional tokens.
        old = self.values.get(key)
        if old is not None and value < old: self.invalid = True; return
        self.values[key] = value

    def observe(self, frame, provider):
        if not isinstance(frame, dict): return
        if provider == 'anthropic':
            usage = frame.get('message', {}).get('usage') if frame.get('type') == 'message_start' else frame.get('usage')
            if not isinstance(usage, dict): return
            for key in ['input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens']:
                self.count(key, usage.get(key))
        else:
            usage = frame.get('usage')
            if not isinstance(usage, dict): return
            for name, key in [('prompt_tokens','input_tokens'),('completion_tokens','output_tokens'),('total_tokens','total_tokens')]:
                self.count(key, usage.get(name))
            details = usage.get('prompt_tokens_details')
            if isinstance(details, dict): self.count('cache_read_input_tokens', details.get('cached_tokens'))

    def result(self, provider, completed):
        values = self.values
        inputs, outputs, total = values.get('input_tokens'), values.get('output_tokens'), values.get('total_tokens')
        read, write = values.get('cache_read_input_tokens'), values.get('cache_creation_input_tokens')
        if provider == 'anthropic' and inputs is not None:
            # Anthropic base input excludes cache reads/writes; OpenAI prompt_tokens includes cache hits.
            inputs += (read or 0)+(write or 0)
        if inputs is not None and outputs is not None:
            if total is not None and total != inputs+outputs: self.invalid = True
            total = inputs+outputs
        if read is not None and inputs is not None and read > inputs: self.invalid = True
        state = 'invalid' if self.invalid else 'mock' if provider == 'mock' else 'complete' if completed and inputs is not None and outputs is not None else 'partial' if values else 'missing'
        if self.invalid: inputs=outputs=total=read=write=None
        return {'input_tokens': inputs, 'output_tokens': outputs, 'total_tokens': total,
                'cache_read_tokens': read, 'cache_write_tokens': write, 'usage_state': state}


def observe_usage(frame, provider):
    sink = usage_sink.get()
    if sink is not None: sink.observe(frame, provider)


def close_call(call_id, status, code, elapsed, usage):
    row = ModelCall.objects.get(pk=call_id)
    # Interrupted-call recovery or duplicate closure may not overwrite an existing terminal record.
    updated = ModelCall.objects.filter(pk=call_id, status='running').update(
        status=status, error_code=code, duration_ms=elapsed, finished_at=timezone.now(), **usage)
    if updated:
        record_audit(actor_id=row.actor_id, course_id=row.course_id, action='model.call', object_ref=str(row.pk),
            status=status, request_id=row.request_id, skill_id=row.skill_id, duration_ms=elapsed,
            tokens=usage['total_tokens'] if usage['usage_state']=='complete' else None)


async def measured_stream(implementation, messages, attachments=(), tools=()):
    provider = os.getenv('MODEL_PROVIDER', 'mock').lower()
    model = os.getenv('MODEL_NAME', '')
    if provider == 'mock' or not model: provider = 'mock'; model = model or 'mock-local'
    meta = call_context.get()
    row = await sync_to_async(ModelCall.objects.create)(provider=provider[:40], model=model[:200], **meta)
    usage = Usage(); started=time.monotonic(); status='failed'; code='generation_failed'
    try:
        async with aclosing(implementation(messages, attachments, tools)) as stream:
            while True:
                token = usage_sink.set(usage)
                try:
                    try: item = await anext(stream)
                    except StopAsyncIteration: break
                finally: usage_sink.reset(token)
                yield item
        status='succeeded';code=''
    except asyncio.CancelledError:
        status='cancelled';code='cancelled';raise
    except GeneratorExit:
        status='cancelled';code='consumer_closed';raise
    except TimeoutError:
        code='timeout';raise
    finally:
        values = usage.result(provider, status=='succeeded')
        # No full exception strings are stored; completion is durable before the caller receives it.
        await sync_to_async(close_call)(row.pk,status,code,min(int((time.monotonic()-started)*1000),2147483647),values)
