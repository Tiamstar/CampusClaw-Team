from django.db import models


class ExamSource(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.PROTECT)
    owner = models.ForeignKey('core.User', on_delete=models.PROTECT)
    file = models.FileField(upload_to='exam-sources/%Y/%m/%d/')
    name = models.CharField(max_length=200)
    original_name = models.CharField(max_length=200, blank=True)
    digest = models.CharField(max_length=64)
    request_key = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default='queued', db_index=True)
    units = models.JSONField(default=list)
    draft = models.JSONField(default=dict)
    mapping = models.JSONField(default=list)
    revision = models.PositiveIntegerField(default=1)
    error = models.CharField(max_length=200, blank=True)
    model = models.CharField(max_length=200, blank=True)
    lease_token = models.CharField(max_length=64, blank=True)
    lease_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course','owner','request_key'], name='unique_exam_upload_key')]


class QuestionAsset(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.PROTECT)
    owner = models.ForeignKey('core.User', on_delete=models.PROTECT)
    source = models.ForeignKey(ExamSource, null=True, on_delete=models.PROTECT)
    file = models.FileField(upload_to='question-assets/%Y/%m/%d/')
    digest = models.CharField(max_length=64)
    label = models.CharField(max_length=200, blank=True)
    is_page = models.BooleanField(default=False)


class QuestionGroup(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.PROTECT)
    owner = models.ForeignKey('core.User', on_delete=models.PROTECT)
    title = models.CharField(max_length=200)
    material = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)
    source = models.ForeignKey(ExamSource, null=True, on_delete=models.PROTECT)
    source_units = models.JSONField(default=list)


class Question(models.Model):
    course = models.ForeignKey('core.Course',on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    body = models.TextField()
    options = models.JSONField(default=list)
    answer = models.JSONField(default=dict)
    explanation = models.TextField(blank=True)
    points = models.ManyToManyField('core.KnowledgePoint',blank=True)
    score = models.DecimalField(max_digits=7,decimal_places=2,null=True,blank=True)
    revision = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)
    owner = models.ForeignKey('core.User', null=True, on_delete=models.PROTECT)
    group = models.ForeignKey(QuestionGroup, null=True, on_delete=models.PROTECT, related_name='questions')
    position = models.PositiveIntegerField(default=0)
    source = models.ForeignKey(ExamSource, null=True, on_delete=models.PROTECT)
    source_units = models.JSONField(default=list)


class ExamPaperEntry(models.Model):
    """Ordered live bank membership; draft JSON is not the referential authority."""
    source = models.ForeignKey(ExamSource, on_delete=models.PROTECT, related_name='entries')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='paper_entries')
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['source', 'question'], name='unique_paper_question'),
                       models.UniqueConstraint(fields=['source', 'position'], name='unique_paper_position')]


class ExamPaperRevision(models.Model):
    source = models.ForeignKey(ExamSource, on_delete=models.PROTECT, related_name='edit_history')
    revision = models.PositiveIntegerField()
    schema_version = models.PositiveSmallIntegerField(default=1)
    content = models.JSONField(default=dict)
    actor = models.ForeignKey('core.User', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'revision'], name='unique_paper_edit_revision')]


class Quiz(models.Model):
    course = models.ForeignKey('core.Course',on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=16,default='draft')
    rules = models.JSONField(default=list)
    question_ids = models.JSONField(default=list)
    question_scores = models.JSONField(default=dict)
    owner = models.ForeignKey('core.User', null=True, on_delete=models.PROTECT)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    time_limit_minutes = models.PositiveIntegerField(default=30)
    max_attempts = models.PositiveIntegerField(default=1)
    answers_at = models.DateTimeField()
    grades_published = models.BooleanField(default=False)
    policy = models.CharField(max_length=16,default='highest')
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)


class QuizAttempt(models.Model):
    quiz = models.ForeignKey(Quiz,on_delete=models.PROTECT,related_name='attempts')
    student = models.ForeignKey('core.User',on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=16,default='in_progress')
    snapshot = models.JSONField(default=list)
    snapshot_hash = models.CharField(max_length=64)
    answers = models.JSONField(default=dict)
    answer_revision = models.PositiveIntegerField(default=0)
    saved_at = models.DateTimeField(null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True)
    submission_basis = models.CharField(max_length=32,blank=True)
    grading_status = models.CharField(max_length=20,default='pending')
    scores = models.JSONField(default=dict)
    feedback = models.JSONField(default=dict)
    grade_revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['quiz','student','number'],name='unique_quiz_attempt')]


class QuizSaveReceipt(models.Model):
    attempt = models.ForeignKey(QuizAttempt,on_delete=models.CASCADE)
    key = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64)
    revision = models.PositiveIntegerField()
    saved_at = models.DateTimeField()

    class Meta:
        constraints=[models.UniqueConstraint(fields=['attempt','key'],name='unique_quiz_save_key')]


class QuizGradeRevision(models.Model):
    attempt = models.ForeignKey(QuizAttempt,on_delete=models.CASCADE,related_name='grade_history')
    revision = models.PositiveIntegerField()
    scores = models.JSONField(default=dict)
    feedback = models.JSONField(default=dict)
    status = models.CharField(max_length=20)
    actor = models.ForeignKey('core.User',null=True,on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['attempt','revision'],name='unique_quiz_grade_revision')]


class QuizAnswerImage(models.Model):
    attempt = models.ForeignKey(QuizAttempt,on_delete=models.CASCADE)
    student = models.ForeignKey('core.User',on_delete=models.PROTECT)
    question_id = models.PositiveBigIntegerField()
    file = models.FileField(upload_to='quiz-images/%Y/%m/%d/')
    name = models.CharField(max_length=200)
    size = models.PositiveIntegerField()


class QuizSuggestion(models.Model):
    attempt = models.ForeignKey(QuizAttempt,on_delete=models.CASCADE)
    status = models.CharField(max_length=20,default='running')
    body = models.TextField(blank=True)
    model = models.CharField(max_length=200,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class QuestionImportBatch(models.Model):
    course = models.ForeignKey('core.Course', on_delete=models.CASCADE)
    actor = models.ForeignKey('core.User', on_delete=models.PROTECT)
    key = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64)
    imported_count = models.PositiveIntegerField()
    question_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'actor', 'key'], name='unique_question_import_key')]
