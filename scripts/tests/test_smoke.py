import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'smoke.py'
spec = importlib.util.spec_from_file_location('smoke', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeTests(unittest.TestCase):
    def test_explicit_retention_and_local_origin_required(self):
        for base in ['https://example.com', 'http://localhost@evil.test', 'http://localhost/path', 'http://localhost/?q=x', 'http://localhost:bad', 'http://localhost:0']:
            with self.subTest(base=base), self.assertRaises(ValueError):
                smoke.validate_options(base, 'campusclaw-team', True)
        with self.assertRaises(ValueError):smoke.validate_options('http://127.0.0.1', 'campusclaw-team', False)
        with self.assertRaises(ValueError):smoke.validate_options('http://127.0.0.1', 'x --context remote', True)

    def test_credentials_passed_only_on_stdin(self):
        code = 'synthetic-secret-marker'
        with patch.object(smoke.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[1,2,3]\n', '')) as run:
            self.assertEqual(smoke.backend('container-id', code), [1, 2, 3])
        self.assertNotIn(code, str(run.call_args.args))
        self.assertEqual(run.call_args.kwargs['input'], code)

    def test_confirmation_negative_paths_and_single_execution(self):
        calls = []
        def call(path, method, data, token, expected=200):
            calls.append((path, data, token, expected))
            if path.endswith('tool-test/'):
                return {'status':'pending','result':{'confirmation_required':True,'confirmation_id':'synthetic-id'}}
            return {'status':'succeeded','result':{'content':[{'text':'5050'}]},'error':''}
        result = smoke.confirmed_tool(call, 7, 'mcp_formula', {'topic':'derivative'}, 'owner', 'outsider')
        self.assertIn('5050', str(result))
        self.assertEqual([c[3] for c in calls], [200,404,400,200,409])
        self.assertEqual(calls[3][1], {'action':'confirm'})
        self.assertEqual(calls[1][2], 'outsider')

    def test_unconfirmed_or_failed_tool_cannot_pass(self):
        for response in [{'status':'ok','result':{'text':'old bypass'}}, {'status':'error'},
                         {'status':'pending','result':{}}]:
            with self.subTest(response=response), self.assertRaises(AssertionError):
                smoke.confirmed_tool(lambda *a,**k:response, 1, 'mcp', {}, 'owner', 'other')
        def failed(path, *args):
            if path.endswith('tool-test/'):
                return {'status':'pending','result':{'confirmation_required':True,'confirmation_id':'id'}}
            return {'status':'failed','result':{},'error':'safe failure'}
        with self.assertRaises(AssertionError):smoke.confirmed_tool(failed, 1, 'mcp', {}, 'owner', 'other')

    def test_existing_evidence_or_real_provider_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'evidence.json'
            args = ['smoke.py','--retain-fixtures','--output',str(output)]
            output.write_text('keep failed evidence')
            with patch('sys.argv', args), patch.object(smoke, 'backend_container') as container:
                with self.assertRaises(FileExistsError):smoke.main()
                container.assert_not_called()
            self.assertEqual(output.read_text(), 'keep failed evidence')
            other = Path(folder)/'new.json'
            with patch('sys.argv', args[:-1]+[str(other)]), patch.object(smoke,'backend_container',return_value='id'), \
                 patch.object(smoke,'backend',return_value='real-provider') as backend:
                with self.assertRaisesRegex(RuntimeError,'mock provider'):smoke.main()
                self.assertEqual(backend.call_count, 1)
            self.assertIn('"passed": false', other.read_text())
