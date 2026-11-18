from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0030_forum_resolution'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name='WrongAnswerReview',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('item_id', models.CharField(max_length=120)),
            ('grade_revision', models.PositiveIntegerField()),
            ('revision', models.PositiveIntegerField(default=0)),
            ('status', models.CharField(choices=[('reviewing', '继续复习'), ('mastered', '已掌握')], default='reviewing', max_length=20)),
            ('note', models.CharField(blank=True, max_length=500)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wrong_answer_reviews', to=settings.AUTH_USER_MODEL)),
            ('version', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wrong_answer_reviews', to='core.submissionversion')),
        ],
        options={
            'constraints': [models.UniqueConstraint(fields=('version', 'student', 'grade_revision', 'item_id'), name='unique_wrong_answer_review')],
            'indexes': [models.Index(fields=['student', 'status', 'updated_at'], name='wrong_review_student_status')],
        },
    )]
