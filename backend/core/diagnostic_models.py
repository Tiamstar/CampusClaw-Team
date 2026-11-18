from django.db import models


class DiagnosticSettings(models.Model):
    course = models.OneToOneField('core.Course', on_delete=models.CASCADE)
    enabled = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=0)


class DiagnosticReport(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    creator = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='diagnostics_created')
    student = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='diagnostics_received')
    status = models.CharField(max_length=24, default='queued')
    phase = models.CharField(max_length=32, default='queued')
    basis = models.JSONField(default=dict)
    settings_revision = models.PositiveIntegerField(default=0)
    revision = models.PositiveIntegerField(default=0)
    current_version = models.PositiveIntegerField(default=0)
    published_version = models.PositiveIntegerField(null=True)
    model = models.CharField(max_length=160, blank=True)
    skill = models.CharField(max_length=80, default='learning-diagnosis@1.0.0')
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    published_at = models.DateTimeField(null=True)
    reviewer = models.ForeignKey('core.User', null=True, on_delete=models.PROTECT, related_name='diagnostics_reviewed')
    review_reason = models.CharField(max_length=500, blank=True)


class DiagnosticVersion(models.Model):
    report = models.ForeignKey(DiagnosticReport, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField()
    content = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    html = models.TextField()
    pdf = models.BinaryField()
    pdf_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey('core.User', null=True, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['report','number'], name='unique_diagnostic_version')]
