from django.db import models


class Question(models.Model):
    course = models.ForeignKey('core.Course',on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    body = models.TextField()
    options = models.JSONField(default=list)
    answer = models.JSONField(default=dict)
    explanation = models.TextField(blank=True)
    points = models.ManyToManyField('core.KnowledgePoint',blank=True)
    score = models.DecimalField(max_digits=7,decimal_places=2)
    revision = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)


class Quiz(models.Model):
    course = models.ForeignKey('core.Course',on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=16,default='draft')
    rules = models.JSONField(default=list)
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
