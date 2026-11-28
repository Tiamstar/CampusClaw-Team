import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from core.diagnostic_service import scan_diagnostics
from core.forum_service import scan_reminders
from core.models import GraphCandidate
from core.quiz_service import expire_attempts
from core.review_service import scan_review_tasks


def recover_graph_extractions():
    return GraphCandidate.objects.filter(
        status='running', created_at__lt=timezone.now() - timedelta(minutes=5),
    ).update(status='failed', error='抽取中断，请重试')


class Command(BaseCommand):
    help = 'Run scheduled teaching tasks. --loop repeats every 60 seconds.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true')

    def handle(self, *args, **options):
        tasks = (
            ('Forum reminder', scan_reminders, 'Created {} forum reminders'),
            ('Quiz deadline', expire_attempts, 'Submitted {} expired quiz attempts'),
            ('Review plan', scan_review_tasks, 'Processed {} review tasks'),
            ('Diagnostic report', scan_diagnostics, 'Processed {} diagnostic reports'),
            ('Graph recovery', recover_graph_extractions, 'Recovered {} interrupted graph extractions'),
        )
        while True:
            for name, scan, message in tasks:
                try:
                    self.stdout.write(message.format(scan()))
                except Exception as exc:
                    if not options['loop']:
                        raise
                    self.stderr.write(f'{name} scan failed: {type(exc).__name__}')
                finally:
                    close_old_connections()
            if not options['loop']:
                return
            time.sleep(60)
