"""Opt-in, empty-database synthetic fixtures. No model/SMTP/worker calls."""
import json
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.acceptance_seed import build_dataset
from core.models import AcceptanceFixtureSet, Course, User


class Command(BaseCommand):
    help = 'Import one synthetic acceptance dataset into an EMPTY PostgreSQL database; reruns are read-only.'

    def add_arguments(self, parser):
        parser.add_argument('--allow-synthetic-fixtures', action='store_true')

    def handle(self, *args, **options):
        if not options['allow_synthetic_fixtures']:
            raise CommandError('Requires --allow-synthetic-fixtures; use a separate empty database')
        if connection.vendor != 'postgresql':
            raise CommandError('PostgreSQL is required for the acceptance dataset and import lock')
        with transaction.atomic():
            # Serialize imports even before the receipt exists. No public HTTP
            # endpoint invokes this command, and only one dataset is supported.
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [619032711])
            receipt = AcceptanceFixtureSet.objects.filter(key='course-acceptance-v1').first()
            if receipt:
                if receipt.version != 1:
                    raise CommandError('Unsupported fixture version; no records changed')
                manifest = receipt.manifest
                reused = True
            else:
                if User.objects.exists() or Course.objects.exists():
                    raise CommandError('Refusing non-empty teaching database; existing accounts and courses are untouched')
                password = os.environ.get('ACCEPTANCE_FIXTURE_PASSWORD', '')
                try:
                    if not password:
                        raise ValidationError('missing')
                    validate_password(password)
                except ValidationError:
                    raise CommandError('Set a strong ACCEPTANCE_FIXTURE_PASSWORD in the environment; it is never printed') from None
                manifest = build_dataset(password)
                AcceptanceFixtureSet.objects.create(key='course-acceptance-v1', version=1, manifest=manifest)
                reused = False
        self.stdout.write(json.dumps({'reused': reused, 'manifest': manifest}, ensure_ascii=False, indent=2))
