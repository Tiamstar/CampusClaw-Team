from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from core.management.commands import scan_forum_reminders as command


class ScheduledTaskTests(SimpleTestCase):
    def test_forum_failure_does_not_skip_other_tasks_in_loop(self):
        stderr = StringIO()
        with (
            patch.object(command, 'scan_reminders', side_effect=RuntimeError('private detail')),
            patch.object(command, 'expire_attempts', return_value=1) as expire,
            patch.object(command, 'scan_review_tasks', return_value=0) as review,
            patch.object(command, 'scan_diagnostics', return_value=0) as diagnose,
            patch.object(command, 'GraphCandidate') as recover,
            patch.object(command.time, 'sleep', side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                call_command('scan_forum_reminders', '--loop', stdout=StringIO(), stderr=stderr)

        expire.assert_called_once_with()
        review.assert_called_once_with()
        diagnose.assert_called_once_with()
        recover.objects.filter.assert_called_once()
        self.assertEqual(stderr.getvalue().strip(), 'Forum reminder scan failed: RuntimeError')

    def test_one_shot_reports_failure_to_caller(self):
        with patch.object(command, 'scan_reminders', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                call_command('scan_forum_reminders', stdout=StringIO())
