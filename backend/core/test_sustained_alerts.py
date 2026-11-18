from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from .models import User, Course, SkillAlert, SkillAlertEvent
from .skill_monitor import evaluate, dashboard, alert_policy
from .coursework_service import SKILLS


@override_settings(SKILL_ALERT_FOR_SECONDS=120, SKILL_ALERT_RECOVERY_SECONDS=120, SKILL_ALERT_MAX_GAP_SECONDS=90)
class SustainedAlertTests(TestCase):
    def setUp(self):
        self.now=timezone.now()
        user=User.objects.create_user('sustained@example.invalid',None)
        self.course=Course.objects.create(name='Synthetic alert course',created_by=user)
        self.alert=SkillAlert.objects.create(course=self.course,skill_id=SKILLS['guidance'],rule='queue_age_seconds',
            threshold=60,changed_at=self.now,evaluated_at=self.now)
        self.row={'skill_id':SKILLS['guidance'],'queued':1,'running':0,'oldest_queue_seconds':100,
                  'failure_rate':None,'finished_tasks':0,'cancelled_tasks':0,'p95_ms':None,'latency_samples':0}

    def scan(self,seconds,**changes):
        self.row.update(changes)
        with patch('core.skill_monitor.summary',return_value=[dict(self.row)]):evaluate(self.now+timedelta(seconds=seconds))
        self.alert.refresh_from_db()

    def test_sustained_trigger_recovery_and_duplicate_scan(self):
        for second in [0,0,30,60,90,119]:self.scan(second)
        self.assertFalse(self.alert.firing);self.assertEqual(SkillAlertEvent.objects.count(),0)
        self.scan(120);self.scan(120)
        self.assertTrue(self.alert.firing);self.assertEqual(SkillAlertEvent.objects.filter(firing=True).count(),1)
        self.scan(150,queued=0,oldest_queue_seconds=0)
        self.scan(180);self.scan(210);self.scan(240);self.scan(269)
        self.assertTrue(self.alert.firing)
        self.scan(270);self.scan(270)
        self.assertFalse(self.alert.firing);self.assertEqual(SkillAlertEvent.objects.filter(firing=False).count(),1)

    def test_short_spike_and_monitor_gap_reset_continuity(self):
        self.scan(0);self.scan(30,queued=0,oldest_queue_seconds=0)
        self.assertIsNone(self.alert.pending_since)
        self.scan(60,queued=1,oldest_queue_seconds=100)
        self.scan(181)  # gap exceeds 90 seconds: cannot infer sustained observation.
        self.assertEqual(self.alert.pending_since,self.now+timedelta(seconds=181))
        for second in [211,241,271]:self.scan(second)
        self.assertFalse(self.alert.firing)
        self.scan(301);self.assertTrue(self.alert.firing)

    def test_insufficient_samples_never_resolve_firing_alert(self):
        self.alert.rule='model_p95_ms';self.alert.firing=True;self.alert.save()
        self.scan(0,queued=0,oldest_queue_seconds=0,p95_ms=10,latency_samples=5)
        self.assertIsNotNone(self.alert.pending_since)
        self.scan(30,p95_ms=None,latency_samples=0)
        for second in [60,90,120,150,180]:self.scan(second)
        self.assertTrue(self.alert.firing);self.assertEqual(self.alert.observation,'unknown')
        self.assertIsNone(self.alert.pending_since);self.assertFalse(SkillAlertEvent.objects.exists())
        self.scan(210,p95_ms=10,latency_samples=5)
        for second in [240,270,300,330]:self.scan(second)
        self.assertFalse(self.alert.firing)

    def test_policy_change_and_backward_clock_cannot_credit_elapsed_time(self):
        self.scan(0);self.scan(60)
        with override_settings(SKILL_ALERT_FOR_SECONDS=180):
            self.scan(90)
            self.assertEqual(self.alert.pending_since,self.now+timedelta(seconds=90))
            self.scan(30)
            self.assertEqual(self.alert.evaluated_at,self.now+timedelta(seconds=90))
            for second in [120,150,180,210,240]:self.scan(second)
            self.assertFalse(self.alert.firing)
            self.scan(270);self.assertTrue(self.alert.firing)

    def test_dashboard_readonly_exposes_pending_unknown_and_policy(self):
        self.scan(0)
        before=SkillAlert.objects.values().get(pk=self.alert.pk)
        data=dashboard(self.course.pk,1)
        self.assertEqual(data['alert_policy']['for_seconds'],120)
        self.assertIsNotNone(data['alerts'][0]['pending_since'])
        self.assertFalse(data['alerts'][0]['has_fired'])
        self.assertEqual(before,SkillAlert.objects.values().get(pk=self.alert.pk))

    def test_invalid_duration_policy_fails_instead_of_silently_disabling(self):
        for changes in [{'SKILL_ALERT_FOR_SECONDS':-1},{'SKILL_ALERT_MAX_GAP_SECONDS':10}]:
            with override_settings(**changes),self.assertRaises(ValueError):alert_policy()
