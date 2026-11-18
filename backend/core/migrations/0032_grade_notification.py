from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0031_wrong_answer_review'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name='GradeNotification',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('event_key', models.CharField(max_length=100)),
            ('grade_revision', models.PositiveIntegerField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('read_at', models.DateTimeField(null=True)),
            ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.course')),
            ('assignment_version', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='core.submissionversion')),
            ('quiz_attempt', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='core.quizattempt')),
        ],
        options={
            'indexes': [models.Index(fields=['recipient', '-created_at', '-id'], name='grade_notification_inbox')],
            'constraints': [models.UniqueConstraint(fields=('recipient', 'event_key'), name='unique_grade_notification_event'),
                models.CheckConstraint(condition=(models.Q(assignment_version__isnull=False, quiz_attempt__isnull=True) |
                    models.Q(assignment_version__isnull=True, quiz_attempt__isnull=False)), name='grade_notification_one_target')],
        },
    )]
