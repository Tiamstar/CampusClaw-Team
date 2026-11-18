from django.db import models


class ReviewPlan(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    owner = models.ForeignKey('core.User', on_delete=models.PROTECT)
    status = models.CharField(max_length=24, default='queued')
    basis = models.JSONField(default=dict)
    steps = models.JSONField(default=list)
    selected_ids = models.JSONField(default=list)
    schedule = models.JSONField(default=dict)
    model = models.CharField(max_length=160, blank=True)
    skill = models.CharField(max_length=80, default='review-path@1.0.0')
    error = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    confirmed_at = models.DateTimeField(null=True)
    cancelled_at = models.DateTimeField(null=True)


class ReviewReminder(models.Model):
    plan = models.ForeignKey(ReviewPlan, on_delete=models.CASCADE, related_name='reminders')
    schedule_revision = models.PositiveIntegerField()
    point_id = models.PositiveBigIntegerField()
    offset_days = models.PositiveSmallIntegerField()
    due_at = models.DateTimeField(db_index=True)
    state = models.CharField(max_length=16, default='scheduled')
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['plan','schedule_revision','point_id','offset_days'], name='unique_review_reminder')]
