import uuid
from django.db import models


class ToolConfirmation(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('User',on_delete=models.CASCADE)
    thread=models.ForeignKey('AgentThread',on_delete=models.CASCADE,related_name='tool_confirmations')
    course_id=models.BigIntegerField(null=True)
    tool_name=models.CharField(max_length=160)
    arguments=models.JSONField()
    fingerprint=models.CharField(max_length=64)
    config_revision=models.PositiveIntegerField(null=True)
    status=models.CharField(max_length=16,default='pending')
    result=models.JSONField(default=dict)
    error=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    expires_at=models.DateTimeField()
    started_at=models.DateTimeField(null=True)
    finished_at=models.DateTimeField(null=True)

    class Meta:
        indexes=[models.Index(fields=['thread','-created_at'],name='tool_confirm_thread')]
