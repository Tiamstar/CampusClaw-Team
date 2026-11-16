import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'setup_production.py'
spec = importlib.util.spec_from_file_location('production_config', SCRIPT)
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


class ProductionConfigTests(unittest.TestCase):
    def test_existing_configuration_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env.production'
            path.write_text('existing-private-config', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                production.create_config(path, 'campus.example.com', 'ops@example.com')
            self.assertEqual(path.read_text(), 'existing-private-config')

    def test_new_credentials_never_reuse_local_values(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f'.env.production-{i}' for i in range(2)]
            for path in paths:
                production.create_config(path, 'campus.example.com', 'ops@example.com')
            configs = [dict(line.split('=', 1) for line in p.read_text().splitlines() if line and not line.startswith('#')) for p in paths]
            for key in ['DJANGO_SECRET_KEY', 'POSTGRES_PASSWORD', 'MCP_CAMPUS_TOKEN', 'SANDBOX_TOKEN']:
                self.assertGreaterEqual(len(configs[0][key]), 50)
                self.assertNotEqual(configs[0][key], configs[1][key])
            self.assertEqual(configs[0]['PUBLIC_HOST'], 'campus.example.com')

    def test_hostname_and_email_injection_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env.production'
            for host in ['https://example.com', 'x.test:443', 'x.test/route', '*.test', 'x.test\nINJECT=1', '127.0.0.1', 'bad..test', '-bad.test']:
                with self.subTest(host=host), self.assertRaises(ValueError):
                    production.create_config(path, host, 'ops@example.com')
            for email in ['x@example.com\nINJECT=1', 'a@x.test }', '${ENV}@x.test', 'x@-bad.test']:
                with self.subTest(email=email), self.assertRaises(ValueError):
                    production.create_config(path, 'campus.example.com', email)
            self.assertFalse(path.exists())
