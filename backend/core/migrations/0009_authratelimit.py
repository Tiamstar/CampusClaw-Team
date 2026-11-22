from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0008_homework_review')]
    operations = [migrations.CreateModel(name='AuthRateLimit', fields=[
        ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
        ('count', models.PositiveIntegerField(default=0)),
        ('expires_at', models.DateTimeField(db_index=True)),
    ])]
