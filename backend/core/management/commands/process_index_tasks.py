import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection
from django.utils import timezone
from core.index_service import scan_index_tasks
from core.models import MaterialIndexTask


class Command(BaseCommand):
    help = 'Claim durable material indexing tasks; --loop polls every 2 seconds.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true')
        parser.add_argument('--health', action='store_true')

    def handle(self, *args, **options):
        if options['health']:
            connection.ensure_connection()
            # A live container with expired running work needs recovery, not a green badge.
            if MaterialIndexTask.objects.filter(status='running', lease_until__lt=timezone.now()).exists():
                raise RuntimeError('index task lease expired')
            return
        while True:
            try:
                count = scan_index_tasks()
                if count or not options['loop']:
                    self.stdout.write(f'Processed {count} index tasks')
            except Exception as exc:
                if not options['loop']:
                    raise
                self.stderr.write('Index scan failed: ' + type(exc).__name__)
            finally:
                close_old_connections()
            if not options['loop']:
                break
            time.sleep(2)
