from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0022_request_latency')]
    operations = [migrations.CreateModel(
        name='AcceptanceFixtureSet',
        fields=[
            ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
            ('version', models.PositiveIntegerField()),
            ('manifest', models.JSONField(default=dict)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ],
    )]
