from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0029_original_exam_filename')]
    operations = [
        migrations.AddField(model_name='forumpost',name='resolved_reply',field=models.ForeignKey(null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,related_name='resolved_posts',to='core.forumreply')),
        migrations.AddField(model_name='forumpost',name='resolved_at',field=models.DateTimeField(null=True,blank=True)),
        migrations.AddField(model_name='forumpost',name='revision',field=models.PositiveIntegerField(default=0)),
    ]
