import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection
from django.utils import timezone
from core.coursework_service import scan
from core.models import CourseworkTask


class Command(BaseCommand):
    help = 'Process durable homework grading drafts and wrong-answer explanations.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true')
        parser.add_argument('--health', action='store_true')

    def handle(self, *args, **options):
        if options['health']:
            connection.ensure_connection()
            if CourseworkTask.objects.filter(status='running', lease_until__lte=timezone.now()).exists(): raise RuntimeError('coursework lease expired')
            return
        while True:
            try:
                count = scan()
                if count or not options['loop']: self.stdout.write(f'Processed {count} coursework tasks')
            except Exception as exc:
                if not options['loop']: raise
                self.stderr.write('Coursework scan failed: '+type(exc).__name__)
            finally: close_old_connections()
            if not options['loop']: break
            time.sleep(2)
