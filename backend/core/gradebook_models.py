from django.db import models


class GradePolicy(models.Model):
    course = models.OneToOneField('core.Course', on_delete=models.CASCADE)
    revision = models.PositiveIntegerField(default=1)
    items = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)


class GradeSnapshot(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    policy_revision = models.PositiveIntegerField()
    items = models.JSONField(default=list)
    rows = models.JSONField(default=list)
    fingerprint = models.CharField(max_length=64)
    created_by = models.ForeignKey('core.User', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'fingerprint'], name='unique_grade_snapshot')]
