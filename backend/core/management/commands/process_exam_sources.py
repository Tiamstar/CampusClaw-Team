import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections,connection
from django.utils import timezone
from core.exam_service import scan_sources
from core.models import ExamSource


class Command(BaseCommand):
    help='Process durable owner-private exam recognition drafts.'

    def add_arguments(self,parser):
        parser.add_argument('--loop',action='store_true')
        parser.add_argument('--health',action='store_true')

    def handle(self,*args,**options):
        if options['health']:
            connection.ensure_connection()
            if ExamSource.objects.filter(status='running',lease_until__lte=timezone.now()).exists():raise RuntimeError('Exam source lease expired')
            return
        while True:
            try:
                count=scan_sources()
                if count or not options['loop']:self.stdout.write(f'Processed {count} exam sources')
            except Exception:
                if not options['loop']:raise
                self.stderr.write('Exam source worker unavailable; retrying')
            finally:close_old_connections()
            if not options['loop']:break
            time.sleep(2)
