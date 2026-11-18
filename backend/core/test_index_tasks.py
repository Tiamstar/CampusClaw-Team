import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (User, Course, Membership, Material, StoredFile, MaterialIndexTask,
                     KnowledgeEntry, KnowledgeChunk, ChunkEmbedding)
from .index_service import (enqueue, process, claim, recover_expired, transition, prepare_index,
                            IndexConflict, safe_error, IndexFailure)


def prepared():
    return {'body': 'new text', 'parser': 'txt', 'hash': 'a' * 64, 'strategy': 'auto',
            'pieces': [('new text', 0, 8)], 'vectors': [[0.1] * 2048], 'model': 'fixture'}


class IndexTaskTests(TransactionTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=Path(self.directory.name))
        self.settings_override.enable(); self.addCleanup(self.settings_override.disable)
        self.teacher = User.objects.create_user('index-teacher@test.example', 'test-password')
        self.student = User.objects.create_user('index-student@test.example', 'test-password')
        self.outsider = User.objects.create_user('index-outsider@test.example', 'test-password')
        self.course = Course.objects.create(name='Index tasks', created_by=self.teacher)
        Membership.objects.create(user=self.teacher, course=self.course, role='teacher')
        Membership.objects.create(user=self.student, course=self.course, role='student')
        self.tc, self.sc, self.oc = [self.client_for(u) for u in (self.teacher, self.student, self.outsider)]
        self.url = f'/api/courses/{self.course.pk}/materials/'

    def client_for(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(RefreshToken.for_user(user).access_token))
        return client

    def upload(self, key='upload-key', text=b'Indexing fixture text', name='fixture.txt'):
        return self.tc.post(self.url, {'request_key': key, 'title': 'Fixture', 'file': SimpleUploadedFile(name, text)}, format='multipart')

    def task(self):
        response = self.upload()
        self.assertEqual(response.status_code, 202, response.content)
        return MaterialIndexTask.objects.get(pk=response.data['index_task']['id'])

    def test_upload_returns_durable_job_without_external_work_and_is_idempotent(self):
        with patch('core.agent_runtime.embed_texts', new=AsyncMock()) as model:
            first, replay = self.upload(), self.upload()
            model.assert_not_called()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(replay.data['id'], first.data['id'])
        self.assertEqual(replay.data['index_task']['id'], first.data['index_task']['id'])
        self.assertEqual(Material.objects.count(), 1)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(first.data['index_status'], 'queued')
        self.assertEqual(self.upload(text=b'changed').status_code, 409)
        task = MaterialIndexTask.objects.get()
        with self.assertRaises(IndexConflict):
            enqueue(task.material, self.teacher)
        self.assertEqual(self.tc.get(self.url).data[0]['index_task']['status'], 'queued')

    def test_authorization_get_is_readonly_and_student_sees_no_task_metadata(self):
        task = self.task()
        with patch('core.index_service.prepare_index') as prepare:
            self.assertEqual(self.tc.get(f'/api/index-tasks/{task.pk}/').status_code, 200)
            self.assertEqual(self.tc.get(f'/api/materials/{task.material_id}/index-tasks/').status_code, 200)
            prepare.assert_not_called()
        task.refresh_from_db(); self.assertEqual(task.status, 'queued')
        self.assertEqual(self.sc.get(f'/api/index-tasks/{task.pk}/').status_code, 403)
        self.assertEqual(self.oc.get(f'/api/index-tasks/{task.pk}/').status_code, 404)
        self.assertIsNone(self.sc.get(self.url).data[0]['index_task'])
        self.assertEqual(self.sc.post(f'/api/materials/{task.material_id}/reindex/', {}, format='json').status_code, 403)
        self.assertEqual(self.sc.post(self.url, {'file': SimpleUploadedFile('a.txt', b'x')}, format='multipart').status_code, 403)

    def test_parallel_claims_do_not_duplicate_execution(self):
        task = self.task()
        def attempt(_):
            close_old_connections()
            try:
                return claim(task.pk) is not None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, [1, 2])), [False, True])

    def test_success_replaces_chunks_and_vectors_in_one_commit(self):
        task = self.task()
        with patch('core.index_service.prepare_index', return_value=prepared()):
            self.assertTrue(process(task.pk))
        task.refresh_from_db()
        self.assertEqual(task.status, 'succeeded')
        self.assertEqual(task.result['chunks'], 1)
        entry = KnowledgeEntry.objects.get(material=task.material)
        self.assertEqual(entry.status, 'ready')
        self.assertEqual(entry.content_hash, 'a' * 64)
        self.assertEqual(entry.chunks.get().embedding_record.model, 'fixture')
        self.assertFalse(process(task.pk))

    def test_parse_and_embedding_batches_without_media_writes(self):
        task = self.task()
        phases = []
        async def embeddings(texts):
            return [[0.1] * 2048 for _ in texts], 'fixture'
        with patch('core.agent_runtime.embed_texts', embeddings):
            output = prepare_index(task.material, phase=lambda name, **_: phases.append(name))
        self.assertEqual(output['body'], 'Indexing fixture text')
        self.assertEqual(phases[:2], ['extract', 'embed'])
        self.assertFalse(list(Path(self.directory.name).glob('.extract-*')))
        with patch('core.agent_runtime.embed_texts', new=AsyncMock(return_value=([[float('nan')] * 2048], 'bad'))):
            with self.assertRaises(IndexFailure):
                prepare_index(task.material)

    def test_failed_rebuild_keeps_old_chunks_and_atomic_persist_rolls_back(self):
        task = self.task()
        entry = KnowledgeEntry.objects.get(material=task.material)
        old = KnowledgeChunk.objects.create(entry=entry, chunk_index=0, chunk_text='old', start_offset=0, end_offset=3, status='ready')
        with patch('core.index_service.prepare_index', return_value=prepared()), patch('core.index_service.ChunkEmbedding.objects.create', side_effect=RuntimeError('database fixture failure')):
            process(task.pk)
        task.refresh_from_db(); entry.refresh_from_db()
        self.assertEqual(task.error_code, 'persist_failed')
        self.assertEqual(entry.chunks.get().pk, old.pk)
        self.assertEqual(entry.chunks.get().chunk_text, 'old')
        self.assertEqual(entry.status, 'failed')

    def test_cancel_and_retry_ignore_late_completion_and_retain_history(self):
        task = self.task()
        url = f'/api/index-tasks/{task.pk}/'
        new_ids = []
        def prepare(*args, **kwargs):
            running = MaterialIndexTask.objects.get(pk=task.pk)
            self.assertEqual(self.tc.post(url, {'action': 'cancel', 'expected_revision': running.revision}, format='json').status_code, 200)
            cancelled = MaterialIndexTask.objects.get(pk=task.pk)
            result = self.tc.post(url, {'action': 'retry', 'expected_revision': cancelled.revision, 'request_key': 'retry-1'}, format='json')
            self.assertEqual(result.status_code, 202)
            new_ids.append(result.data['id'])
            return prepared()
        with patch('core.index_service.prepare_index', side_effect=prepare):
            self.assertFalse(process(task.pk))
        task.refresh_from_db()
        self.assertEqual(task.status, 'cancelled')
        self.assertEqual(KnowledgeEntry.objects.get(material=task.material).status, 'pending')
        retried = MaterialIndexTask.objects.get(pk=new_ids[0])
        self.assertEqual(retried.retry_of_id, task.pk)
        self.assertEqual(retried.status, 'queued')
        self.assertFalse(KnowledgeChunk.objects.exists())
        self.assertEqual(len(self.tc.get(f'/api/materials/{task.material_id}/index-tasks/').data['results']), 2)

    def test_expired_worker_lease_recovers_and_old_token_cannot_publish(self):
        task = self.task()
        def prepare(*args, **kwargs):
            MaterialIndexTask.objects.filter(pk=task.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
            self.assertEqual(recover_expired(), 1)
            return prepared()
        with patch('core.index_service.prepare_index', side_effect=prepare):
            self.assertFalse(process(task.pk))
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertEqual(task.error_code, 'worker_interrupted')
        self.assertFalse(KnowledgeChunk.objects.exists())

    def test_revoke_teacher_before_claim_or_during_external_work(self):
        task = self.task()
        Membership.objects.filter(course=self.course, user=self.teacher).update(role='student')
        with patch('core.index_service.prepare_index') as prepare:
            self.assertFalse(process(task.pk)); prepare.assert_not_called()
        task.refresh_from_db(); self.assertEqual(task.status, 'failed')
        Membership.objects.filter(course=self.course, user=self.teacher).update(role='teacher')
        second = enqueue(task.material, self.teacher, 'new-request')
        def prepare(*args, **kwargs):
            Membership.objects.filter(course=self.course, user=self.teacher).update(role='student')
            return prepared()
        with patch('core.index_service.prepare_index', side_effect=prepare):
            process(second.pk)
        second.refresh_from_db()
        self.assertEqual(second.error_code, 'permission_or_source')
        self.assertFalse(KnowledgeChunk.objects.exists())

    def test_failures_are_safe_and_have_authorized_retry_path(self):
        task = self.task()
        with patch('core.index_service.prepare_index', side_effect=RuntimeError('Authorization: secret-token https://private-host')):
            process(task.pk)
        task.refresh_from_db()
        self.assertNotIn('secret-token', str(self.tc.get(f'/api/index-tasks/{task.pk}/').data))
        self.assertEqual(self.tc.post(f'/api/index-tasks/{task.pk}/', {'action': 'retry', 'expected_revision': 0}, format='json').status_code, 409)
        response = self.tc.post(f'/api/index-tasks/{task.pk}/', {'action': 'retry', 'expected_revision': task.revision, 'request_key': 'safe-retry'}, format='json')
        self.assertEqual(response.status_code, 202)
        replay = self.tc.post(f'/api/index-tasks/{task.pk}/', {'action': 'retry', 'expected_revision': task.revision, 'request_key': 'safe-retry'}, format='json')
        self.assertEqual(replay.data['id'], response.data['id'])
        exc = httpx.HTTPStatusError('secret-url', request=httpx.Request('POST', 'https://private.example'), response=httpx.Response(429))
        self.assertEqual(safe_error(exc)[0], 'dependency_rate_limit')

    def test_cancel_before_claim_and_bulk_reindex_enqueue_only(self):
        task = self.task()
        self.tc.post(f'/api/index-tasks/{task.pk}/', {'action': 'cancel', 'expected_revision': task.revision}, format='json')
        with patch('core.index_service.prepare_index') as prepare:
            self.assertFalse(process(task.pk))
            response = self.tc.post(f'/api/courses/{self.course.pk}/knowledge/reindex/', {'request_key': 'batch'}, format='json')
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()['results'][0]['status'], 'queued')
            prepare.assert_not_called()

    def test_unsupported_file_fails_without_embedding_and_untracked_is_honest(self):
        task = MaterialIndexTask.objects.get(pk=self.upload(name='archive.zip', text=b'fake zip').data['index_task']['id'])
        with patch('core.agent_runtime.embed_texts', new=AsyncMock()) as embed:
            process(task.pk); embed.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.error_code, 'unsupported')
        material = task.material
        task.delete()
        KnowledgeEntry.objects.filter(material=material).update(status='pending')
        self.assertEqual(self.tc.get(self.url).data[0]['index_status'], 'untracked')

    def test_total_deadline_bounds_blocking_parser_work(self):
        task = self.task()
        with patch('core.index_service.RUN_SECONDS', 0.05), patch('core.index_service.prepare_index', side_effect=lambda *_args, **_kwargs: time.sleep(1)):
            process(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertEqual(task.error_code, 'timeout')
        self.assertFalse(KnowledgeChunk.objects.exists())

    def test_moved_material_rejects_late_result_without_touching_other_course(self):
        task = self.task()
        other = Course.objects.create(name='Other scope', created_by=self.outsider)
        def prepare(*args, **kwargs):
            Material.objects.filter(pk=task.material_id).update(course=other)
            KnowledgeEntry.objects.filter(material_id=task.material_id).update(status='ready', body_text='other course state')
            return prepared()
        with patch('core.index_service.prepare_index', side_effect=prepare):
            process(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.error_code, 'permission_or_source')
        entry = KnowledgeEntry.objects.get(material_id=task.material_id)
        self.assertEqual(entry.status, 'ready')
        self.assertEqual(entry.body_text, 'other course state')
        response = self.tc.post(f'/api/index-tasks/{task.pk}/', {'action': 'retry', 'expected_revision': task.revision}, format='json')
        self.assertEqual(response.status_code, 403)
