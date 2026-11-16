"""Recovery must reject changed/lost data and unsafe backup destinations."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'rehearse_recovery.py'
spec = importlib.util.spec_from_file_location('recovery', SCRIPT)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            'tables': {'core_quizattempt': {'rows': 2, 'sha256': 'answers-and-scores'}},
            'files': {'answers/a.txt': {'bytes': 4, 'sha256': 'answer-bytes'}},
            'missing_references': 0,
        }
        self.restored = {**copy.deepcopy(self.source), 'sequence_safe': True}

    def passes(self):
        return all(recovery.assert_equal(self.source, self.restored).values())

    def test_identical_database_and_media(self):
        self.assertTrue(self.passes())

    def test_changed_score_with_unchanged_row_count(self):
        self.restored['tables']['core_quizattempt']['sha256'] = 'changed-score'
        self.assertFalse(self.passes())

    def test_missing_table(self):
        self.restored['tables'].clear()
        self.assertFalse(self.passes())

    def test_same_size_corrupt_attachment(self):
        self.restored['files']['answers/a.txt']['sha256'] = 'corrupt-bytes'
        self.assertFalse(self.passes())

    def test_missing_or_extra_attachment(self):
        for files in ({}, {**self.restored['files'], 'extra.txt': {'bytes': 0, 'sha256': 'extra'}}):
            with self.subTest(files=files):
                self.restored['files'] = files
                self.assertFalse(self.passes())

    def test_preexisting_missing_source_attachment(self):
        self.source['missing_references'] = 1
        self.assertFalse(self.passes())

    def test_unsafe_restored_sequence(self):
        self.restored['sequence_safe'] = False
        self.assertFalse(self.passes())

    def test_backup_path_rejects_repository_and_overwrite(self):
        with self.assertRaises(ValueError):
            recovery.backup_directory(recovery.ROOT / 'private-backup')
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'backup'
            recovery.backup_directory(target)
            marker = target / 'keep.txt'
            marker.write_text('must survive')
            with self.assertRaises(FileExistsError):
                recovery.backup_directory(target)
            self.assertEqual(marker.read_text(), 'must survive')


class RecoverySourceSelectionTests(unittest.TestCase):
    def pair(self):
        env = ['POSTGRES_DB=fixture', 'POSTGRES_USER=fixture', 'POSTGRES_PASSWORD=synthetic-only']
        def info(service):
            return {'Name':'/production-'+service+'-1', 'State':{'Running':True},
                    'Config':{'Labels':{'com.docker.compose.project':'production',
                                       'com.docker.compose.service':service, 'com.docker.compose.oneoff':'False'},
                              'Env':env + (['POSTGRES_HOST=db'] if service=='backend' else [])},
                    'NetworkSettings':{'Networks':{'production_default':{'Aliases':[service]}}}}
        return info('db'), info('backend')

    def test_custom_configuration_requires_explicit_project(self):
        with self.assertRaises(ValueError):recovery.compose_source(env_file='private.env')
        with self.assertRaises(ValueError):recovery.compose_source(project='unsafe --context other')
        with tempfile.TemporaryDirectory() as folder:
            env=Path(folder)/'.env';env.write_text('private')
            base=Path(folder)/'compose.yml';base.write_text('services: {}')
            override=Path(folder)/'production.yml';override.write_text('services: {}')
            result=recovery.compose_source('production',env,[base,override])
            self.assertEqual(result,['compose','--project-name','production','--env-file',str(env.resolve()),
                                     '--file',str(base.resolve()),'--file',str(override.resolve())])

    def test_same_project_database_and_backend_accepted(self):
        self.assertEqual(recovery.validate_source_pair(*self.pair(),'production'),'production')

    def test_mixed_project_stopped_or_oneoff_rejected(self):
        for mutation in ['project','stopped','oneoff','wrong_service']:
            db,backend=self.pair()
            if mutation=='project':backend['Config']['Labels']['com.docker.compose.project']='other'
            if mutation=='stopped':backend['State']['Running']=False
            if mutation=='oneoff':db['Config']['Labels']['com.docker.compose.oneoff']='True'
            if mutation=='wrong_service':backend['Config']['Labels']['com.docker.compose.service']='worker'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                recovery.validate_source_pair(db,backend,'production')

    def test_unrelated_database_host_network_or_credentials_rejected(self):
        for mutation in ['host','network','database','password','port']:
            db,backend=self.pair()
            if mutation=='network':backend['NetworkSettings']['Networks']={'other':{'Aliases':['backend']}}
            else:
                prefix, value={'host':('POSTGRES_HOST','external-db'), 'database':('POSTGRES_DB','other'),
                               'password':('POSTGRES_PASSWORD','other'), 'port':('POSTGRES_PORT','5433')}[mutation]
                backend['Config']['Env']=[v for v in backend['Config']['Env'] if not v.startswith(prefix+'=')]+[prefix+'='+value]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                recovery.validate_source_pair(db,backend,'production')
