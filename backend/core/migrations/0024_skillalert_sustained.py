from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0023_acceptancefixtureset')]
    operations = [
        migrations.AddField(model_name='skillalert', name='pending_since', field=models.DateTimeField(null=True)),
        migrations.AddField(model_name='skillalert', name='observation', field=models.CharField(max_length=16, default='unknown')),
        migrations.AddField(model_name='skillalert', name='policy_key', field=models.CharField(max_length=160, blank=True)),
    ]
