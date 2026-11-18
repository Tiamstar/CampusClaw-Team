from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.throttling import BaseThrottle

from .models import AuthRateLimit


class AuthThrottle(BaseThrottle):
    scope = 'login'
    retry_after = 1

    def allow_request(self, request, view):
        now = timezone.now()
        ip = request.META.get('REMOTE_ADDR', '')
        # Enable only behind the bundled proxy, which overwrites this header.
        if settings.AUTH_TRUST_PROXY_IP:
            ip = request.META.get('HTTP_X_REAL_IP', ip)
        email = str(request.data.get('email', '')).strip().lower()
        AuthRateLimit.objects.filter(expires_at__lte=now).delete()
        for dimension, identity in [('ip', ip), ('email', email)]:
            limit, seconds = settings.AUTH_RATE_LIMITS[self.scope][dimension]
            key = salted_hmac('auth-rate-limit', f'{self.scope}:{dimension}:{identity}', algorithm='sha256').hexdigest()
            with transaction.atomic():
                bucket, _ = AuthRateLimit.objects.select_for_update().get_or_create(
                    key=key, defaults={'expires_at': now + timedelta(seconds=seconds)})
                if bucket.expires_at <= now:
                    bucket.count, bucket.expires_at = 0, now + timedelta(seconds=seconds)
                if bucket.count >= limit:
                    self.retry_after = max(1, (bucket.expires_at - now).total_seconds())
                    return False
                bucket.count += 1
                bucket.save(update_fields=['count', 'expires_at'])
        return True

    def wait(self):
        return self.retry_after


class CodeThrottle(AuthThrottle):
    scope = 'code'
