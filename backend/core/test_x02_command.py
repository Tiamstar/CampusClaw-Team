from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from .models import User, Course, ForumPost


class X02CommandGuards(TestCase):
    def invoke(self, **options):
        call_command('verify_x02',teacher='missing@example.invalid',student='missing2@example.invalid',
                     output='/tmp/x02-unused.json',stdout=StringIO(),**options)

    def test_explicit_live_fixture_flags_required(self):
        with self.assertRaisesMessage(CommandError,'Requires'):self.invoke()
        self.assertFalse(User.objects.exists())

    def test_external_or_credentialed_or_non_origin_url_rejected(self):
        for url in ['https://example.com','http://localhost@evil.test','http://localhost/path',
                    'http://localhost/?key=secret','http://localhost/#fragment']:
            with self.subTest(url=url),self.assertRaisesMessage(CommandError,'loopback'):
                self.invoke(real=True,retain_fixtures=True,base_url=url)
        self.assertFalse(Course.objects.exists())

    def test_mock_cannot_be_live_evidence(self):
        with patch.dict('os.environ',{'MODEL_PROVIDER':'mock'}),self.assertRaisesMessage(CommandError,'Real provider'):
            self.invoke(real=True,retain_fixtures=True)
        self.assertFalse(ForumPost.objects.exists())

    def test_old_evidence_kept_before_any_fixture_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'evidence.json';path.write_text('failed evidence')
            with patch.dict('os.environ',{'MODEL_PROVIDER':'openai'}),self.assertRaisesMessage(CommandError,'already exists'):
                call_command('verify_x02',teacher='missing@example.invalid',student='missing2@example.invalid',
                             output=str(path),real=True,retain_fixtures=True,stdout=StringIO())
            self.assertEqual(path.read_text(),'failed evidence')
        self.assertFalse(User.objects.exists())
