import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from core.forum_service import scan_reminders


class Command(BaseCommand):
    help = 'Create deduplicated unanswered-forum todos; --loop runs every 60 seconds.'

    def add_arguments(self,parser):
        parser.add_argument('--loop',action='store_true')

    def handle(self,*args,**options):
        while True:
            try:
                self.stdout.write(f'Created {scan_reminders()} forum reminders')
            except Exception as exc:
                if not options['loop']:
                    raise
                self.stderr.write('Forum reminder scan failed: '+type(exc).__name__)
            finally:
                close_old_connections()
            if not options['loop']:
                break
            time.sleep(60)
