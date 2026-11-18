from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from .models import User, Course


class X01CommandGuards(TestCase):
    def invoke(self, **options):
        return call_command('verify_x01', teacher='missing@example.invalid',
                            student='missing-student@example.invalid',
                            output='/tmp/x01-guard-unused.json',stdout=StringIO(),**options)

    def test_no_implicit_real_calls_or_fixtures(self):
        with self.assertRaisesMessage(CommandError,'Requires'):
            self.invoke()
        self.assertEqual(User.objects.count(),0)
        self.assertEqual(Course.objects.count(),0)

    def test_remote_or_credentialed_origins_rejected_before_writes(self):
        for origin in ['https://example.com','http://localhost@evil.test','http://localhost/private',
                       'http://localhost/?redirect=evil','http://localhost/#fragment']:
            with self.subTest(origin=origin), self.assertRaisesMessage(CommandError,'loopback'):
                self.invoke(real=True,retain_fixtures=True,base_url=origin)
        self.assertEqual(User.objects.count(),0)

    def test_mock_is_not_reported_as_real(self):
        with patch.dict('os.environ',{'MODEL_PROVIDER':'mock'}), self.assertRaisesMessage(CommandError,'Real provider'):
            self.invoke(real=True,retain_fixtures=True)
        self.assertEqual(User.objects.count(),0)

    def test_existing_evidence_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'evidence.json';path.write_text('keep failure evidence')
            with patch.dict('os.environ',{'MODEL_PROVIDER':'openai'}), self.assertRaisesMessage(CommandError,'already exists'):
                call_command('verify_x01',teacher='missing@example.invalid',student='missing-student@example.invalid',
                             output=str(path),real=True,retain_fixtures=True,stdout=StringIO())
            self.assertEqual(path.read_text(),'keep failure evidence')
        self.assertEqual(User.objects.count(),0)
