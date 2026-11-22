from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0024_skillalert_sustained')]
    operations = [migrations.CreateModel(
        name='QuestionImportBatch',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('key', models.CharField(max_length=64)),
            ('fingerprint', models.CharField(max_length=64)),
            ('imported_count', models.PositiveIntegerField()),
            ('question_ids', models.JSONField(default=list)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.course')),
            ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ],
        options={'constraints': [models.UniqueConstraint(fields=('course', 'actor', 'key'), name='unique_question_import_key')]},
    )]
