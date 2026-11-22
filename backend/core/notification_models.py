from django.db import models


class GradeNotification(models.Model):
    recipient = models.ForeignKey('core.User', on_delete=models.CASCADE)
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    assignment_version = models.ForeignKey('core.SubmissionVersion', null=True, on_delete=models.CASCADE)
    quiz_attempt = models.ForeignKey('core.QuizAttempt', null=True, on_delete=models.CASCADE)
    event_key = models.CharField(max_length=100)
    grade_revision = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['recipient', 'event_key'], name='unique_grade_notification_event'),
            models.CheckConstraint(condition=(models.Q(assignment_version__isnull=False, quiz_attempt__isnull=True) |
                                              models.Q(assignment_version__isnull=True, quiz_attempt__isnull=False)),
                                   name='grade_notification_one_target'),
        ]
        indexes = [models.Index(fields=['recipient', '-created_at', '-id'], name='grade_notification_inbox')]
