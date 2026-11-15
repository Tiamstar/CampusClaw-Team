import uuid
from django.db import models


class ModelCall(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey('core.Course', null=True, on_delete=models.CASCADE)
    actor_id = models.BigIntegerField(null=True)
    task_id = models.BigIntegerField(null=True)
    request_id = models.CharField(max_length=64, blank=True)
    skill_id = models.CharField(max_length=160, default='unclassified')
    config_revision = models.PositiveIntegerField(null=True)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=200)
    status = models.CharField(max_length=20, default='running')
    error_code = models.CharField(max_length=40, blank=True)
    input_tokens = models.BigIntegerField(null=True)
    output_tokens = models.BigIntegerField(null=True)
    total_tokens = models.BigIntegerField(null=True)
    cache_read_tokens = models.BigIntegerField(null=True)
    cache_write_tokens = models.BigIntegerField(null=True)
    usage_state = models.CharField(max_length=20, default='missing')
    duration_ms = models.PositiveIntegerField(null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=['course', 'skill_id', 'started_at'], name='model_call_course_skill')]


class SkillMetricSample(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    skill_id = models.CharField(max_length=160)
    bucket = models.DateTimeField()
    queued = models.PositiveIntegerField(default=0)
    running = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'skill_id', 'bucket'], name='unique_skill_queue_sample')]


class SkillAlert(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    skill_id = models.CharField(max_length=160)
    rule = models.CharField(max_length=40)
    firing = models.BooleanField(default=False)
    value = models.FloatField(default=0)
    threshold = models.FloatField()
    sample_size = models.PositiveIntegerField(default=0)
    changed_at = models.DateTimeField()
    evaluated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'skill_id', 'rule'], name='unique_skill_alert')]


class SkillAlertEvent(models.Model):
    alert = models.ForeignKey(SkillAlert, on_delete=models.CASCADE, related_name='events')
    firing = models.BooleanField()
    value = models.FloatField()
    sample_size = models.PositiveIntegerField()
    created_at = models.DateTimeField()


class SkillMonitorHeartbeat(models.Model):
    name = models.CharField(max_length=40, primary_key=True, default='skills')
    evaluated_at = models.DateTimeField()
