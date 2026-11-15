from django.db import models


class GraphConfig(models.Model):
    course = models.OneToOneField('core.Course', on_delete=models.CASCADE)
    extraction_enabled = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=0)


class GraphCandidate(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    creator = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='+')
    status = models.CharField(max_length=24, default='running')
    sources = models.JSONField(default=list)
    proposal = models.JSONField(default=dict)
    reviewed_proposal = models.JSONField(default=dict)
    settings_revision = models.PositiveIntegerField()
    model = models.CharField(max_length=160, blank=True)
    skill = models.CharField(max_length=80, default='knowledge-extraction@1.0.0')
    error = models.CharField(max_length=500, blank=True)
    reviewer = models.ForeignKey('core.User', null=True, on_delete=models.PROTECT, related_name='+')
    review_reason = models.CharField(max_length=500, blank=True)
    reviewed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class GraphEdge(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    prerequisite = models.ForeignKey('core.KnowledgePoint', on_delete=models.PROTECT, related_name='outgoing_edges')
    target = models.ForeignKey('core.KnowledgePoint', on_delete=models.PROTECT, related_name='incoming_edges')
    candidate = models.ForeignKey(GraphCandidate, on_delete=models.PROTECT)
    sources = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'prerequisite', 'target'], name='unique_graph_edge')]


class GraphResource(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    point = models.ForeignKey('core.KnowledgePoint', on_delete=models.PROTECT)
    material = models.ForeignKey('core.Material', on_delete=models.PROTECT)
    candidate = models.ForeignKey(GraphCandidate, null=True, on_delete=models.PROTECT)
    sources = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['point', 'material'], name='unique_graph_material_point')]


class GraphVersion(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    number = models.PositiveIntegerField()
    actor = models.ForeignKey('core.User', on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'number'], name='unique_course_graph_version')]
