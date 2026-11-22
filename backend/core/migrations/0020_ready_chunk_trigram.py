from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('core', '0019_teaching_skills_monitor_updated')]
    operations = [AddIndexConcurrently(
        model_name='knowledgechunk',
        index=GinIndex(fields=['chunk_text'], opclasses=['gin_trgm_ops'],
                       condition=models.Q(status='ready'), name='ready_chunk_text_trgm')),
        # Refresh all joined relations: stale tiny-table estimates can hide the new index.
        migrations.RunSQL('ANALYZE core_material; ANALYZE core_knowledgeentry; ANALYZE core_knowledgechunk;',
                          reverse_sql=migrations.RunSQL.noop)]
