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
