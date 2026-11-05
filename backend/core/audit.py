"""Metadata-only audit trail. Request bodies, headers and model text stay out."""
import json
import logging
import time
import uuid

from django.db import DatabaseError
from django.utils import timezone

from .models import AuditEvent

logger = logging.getLogger("campus.audit")


def record_audit(*, actor_id, action, object_ref, status, request_id="", course_id=None,
                 skill_id="", duration_ms=0):
    values = dict(actor_id=actor_id, course_id=course_id, action=action[:100],
                  object_ref=object_ref[:200], status=str(status)[:16],
                  request_id=request_id or uuid.uuid4().hex, skill_id=skill_id[:160],
                  duration_ms=duration_ms, tokens=None)
    try:
        AuditEvent.objects.create(**values)
    except DatabaseError:
        logger.error(json.dumps({"ts": timezone.now().isoformat(), "audit_persisted": False, **values}))
    else:
        logger.info(json.dumps({"ts": timezone.now().isoformat(), "audit_persisted": True, **values}))


class RequestAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        if request.path.startswith("/api/"):
            match = request.resolver_match
            route = match.route if match else "unmatched"
            object_ids = {key: value for key, value in (match.kwargs.items() if match else [])
                          if key.endswith("_id") and isinstance(value, int)}
            user = getattr(request, "user", None)
            record_audit(actor_id=user.pk if user and user.is_authenticated else None,
                         course_id=object_ids.get("course_id"), action=f"{request.method} {route}",
                         object_ref=json.dumps(object_ids, sort_keys=True), status=response.status_code,
                         request_id=request.request_id, duration_ms=round((time.monotonic() - started) * 1000))
            response["Cache-Control"] = "no-store"
        return response
