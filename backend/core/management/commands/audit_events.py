import json
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.models import AuditEvent


class Command(BaseCommand):
    help = "Read audit metadata by actor, skill and time window from an operator shell."

    def add_arguments(self, parser):
        parser.add_argument('--actor', type=int)
        parser.add_argument('--skill')
        parser.add_argument('--minutes', type=int, default=60)
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 1000 or not 1 <= options['minutes'] <= 10080:
            raise CommandError('limit must be 1..1000 and minutes must be 1..10080')
        rows = AuditEvent.objects.filter(created_at__gte=timezone.now() - timedelta(minutes=options['minutes']))
        if options['actor'] is not None:
            rows = rows.filter(actor_id=options['actor'])
        if options['skill'] is not None:
            rows = rows.filter(skill_id=options['skill'])
        for row in rows.order_by('-id').values()[:options['limit']]:
            self.stdout.write(json.dumps(row, default=str, ensure_ascii=False))
