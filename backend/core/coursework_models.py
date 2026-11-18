from django.db import models


class CourseworkSettings(models.Model):
    course = models.OneToOneField('core.Course', on_delete=models.CASCADE)
    grading_enabled = models.BooleanField(default=True)
    explanation_enabled = models.BooleanField(default=True)
    guidance_enabled = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=0)


class CourseworkTask(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    version = models.ForeignKey('core.SubmissionVersion', null=True, on_delete=models.CASCADE, related_name='ai_tasks')
    creator = models.ForeignKey('core.User', on_delete=models.PROTECT)
    kind = models.CharField(max_length=20)
    skill_id = models.CharField(max_length=80)
    settings_revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=100)
    basis = models.JSONField()
    basis_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default='queued')
    phase = models.CharField(max_length=40, default='queued')
    revision = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    retry_of = models.ForeignKey('self', null=True, on_delete=models.PROTECT)
    result = models.JSONField(default=dict)
    model = models.CharField(max_length=200, blank=True)
    error = models.CharField(max_length=500, blank=True)
    events = models.JSONField(default=list)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['course', 'creator', 'request_key'], name='unique_coursework_request'),
            models.UniqueConstraint(fields=['version', 'creator', 'kind'], condition=models.Q(status__in=['queued', 'running']), name='unique_active_coursework'),
            models.UniqueConstraint(fields=['course', 'creator'], condition=models.Q(kind='guidance', status__in=['queued', 'running']), name='unique_active_guidance'),
        ]
        indexes = [models.Index(fields=['status', 'id'], name='coursework_queue'),
                   models.Index(fields=['course', 'finished_at'], name='coursework_course_end')]


class WrongAnswerReview(models.Model):
    STATUS_CHOICES = [('reviewing', '继续复习'), ('mastered', '已掌握')]
    version = models.ForeignKey('core.SubmissionVersion', on_delete=models.CASCADE, related_name='wrong_answer_reviews')
    student = models.ForeignKey('core.User', on_delete=models.CASCADE, related_name='wrong_answer_reviews')
    item_id = models.CharField(max_length=120)
    grade_revision = models.PositiveIntegerField()
    revision = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='reviewing')
    note = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['version', 'student', 'grade_revision', 'item_id'], name='unique_wrong_answer_review')]
        indexes = [models.Index(fields=['student', 'status', 'updated_at'], name='wrong_review_student_status')]
