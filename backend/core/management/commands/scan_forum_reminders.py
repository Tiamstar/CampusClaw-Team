import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from core.forum_service import scan_reminders
from core.quiz_service import expire_attempts
from core.models import GraphCandidate
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Create deduplicated unanswered-forum todos; --loop runs every 60 seconds.'

    def add_arguments(self,parser):
        parser.add_argument('--loop',action='store_true')

    def handle(self,*args,**options):
        while True:
            try:
                self.stdout.write(f'Created {scan_reminders()} forum reminders')
                self.stdout.write(f'Submitted {expire_attempts()} expired quiz attempts')
                GraphCandidate.objects.filter(status='running',created_at__lt=timezone.now()-timedelta(minutes=5)).update(status='failed',error='抽取中断，请重试')
            except Exception as exc:
                if not options['loop']:
                    raise
                self.stderr.write('Forum reminder scan failed: '+type(exc).__name__)
            finally:
                close_old_connections()
            if not options['loop']:
                break
            time.sleep(60)
