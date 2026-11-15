import time
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from core.skill_monitor import evaluate
from core.models import SkillMonitorHeartbeat


class Command(BaseCommand):
    help='Sample teaching-skill queues and evaluate internal operational alerts.'

    def add_arguments(self,parser):
        parser.add_argument('--loop',action='store_true')
        parser.add_argument('--health',action='store_true')

    def handle(self,*args,**options):
        if options['health']:
            if not SkillMonitorHeartbeat.objects.filter(name='skills',evaluated_at__gte=timezone.now()-timedelta(seconds=120)).exists(): raise RuntimeError('skill monitor stale')
            return
        while True:
            try:
                evaluate()
            except Exception as exc:
                if not options['loop']: raise
                self.stderr.write('Skill monitor failed: '+type(exc).__name__)
            finally:close_old_connections()
            if not options['loop']:break
            time.sleep(30)
