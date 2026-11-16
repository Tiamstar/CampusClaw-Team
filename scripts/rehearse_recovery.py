"""Back up the live Compose database/media and verify an isolated restore.

Requires Docker and Python only. Backups contain private data; never commit them.
The source transaction is read-only. The restored database has no application,
worker, published port, credentials from .env, or external network access.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]

# Run the exact same manifest implementation in the source and recovery image.
# No row contents or filenames leave the containers in public evidence.
MANIFEST = r'''
import hashlib, json, os, sys
from pathlib import Path
import psycopg
from psycopg import sql

def connect():
    return psycopg.connect(host=os.environ['POSTGRES_HOST'],
        dbname=os.environ['POSTGRES_DB'], user=os.environ['POSTGRES_USER'],
        password=os.environ.get('POSTGRES_PASSWORD', ''), connect_timeout=10)

def database_manifest(conn):
    result = {}
    conn.execute("SET TIME ZONE 'UTC'")
    conn.execute('SET extra_float_digits = 3')
    tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    for (name,) in tables:
        digest = hashlib.sha256()
        count = 0
        query = sql.SQL('SELECT row_to_json(t)::text FROM public.{} t ORDER BY row_to_json(t)::text COLLATE "C"').format(sql.Identifier(name))
        with conn.cursor(name='recovery_rows') as cur:
            cur.execute(query)
            for (row,) in cur:
                payload = row.encode('utf-8')
                digest.update(len(payload).to_bytes(8, 'big'))
                digest.update(payload)
                count += 1
        result[name] = {'rows': count, 'sha256': digest.hexdigest()}
    return result

def media_manifest(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Media symlinks are unsupported')
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            result[path.relative_to(root).as_posix()] = {
                'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
    return result
'''

SOURCE = MANIFEST + r'''
import tarfile
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'campus.settings')
import django
django.setup()
from django.apps import apps
from django.db.models import FileField
from django.conf import settings
conn = connect()
conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
snapshot = conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
tables = database_manifest(conn)
root = Path(settings.MEDIA_ROOT)
files = media_manifest(root)
references = set()
for model in apps.get_models():
    fields = [f for f in model._meta.fields if isinstance(f, FileField)]
    for field in fields:
        query = sql.SQL('SELECT {} FROM {} WHERE {} IS NOT NULL AND {} <> \'\'').format(
            sql.Identifier(field.column), sql.Identifier(model._meta.db_table),
            sql.Identifier(field.column), sql.Identifier(field.column))
        references.update(row[0] for row in conn.execute(query))
missing = sorted(references - files.keys())
with tarfile.open(sys.argv[1], 'w:gz') as archive:
    archive.add(root, arcname='media')
if media_manifest(root) != files:
    raise RuntimeError('Media changed while backing up; retry in a quiet window')
print(json.dumps({'snapshot':snapshot, 'tables':tables, 'files':files,
    'filefield_references':len(references), 'missing_references':len(missing)}), flush=True)
# Keep the exported snapshot valid until pg_dump has finished importing it.
if sys.stdin.readline().strip() != 'release':
    raise RuntimeError('Snapshot release missing')
conn.rollback()
conn.close()
'''

RESTORE = MANIFEST + r'''
import tarfile
with tarfile.open('/tmp/media.tar.gz', 'r:gz') as archive:
    archive.extractall('/restore', filter='data')
with connect() as conn:
    conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
    tables = database_manifest(conn)
    # Sequence values are not MVCC snapshots. Check the safety invariant on
    # the restored copy rather than claiming their exact source equality.
    sequence_checks = []
    columns = conn.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND (column_default LIKE 'nextval(%' OR is_identity='YES')").fetchall()
    for table, column in columns:
        seq = conn.execute('SELECT pg_get_serial_sequence(%s,%s)', ('public.'+table,column)).fetchone()[0]
        if seq:
            last, called = conn.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(*seq.split('.')))).fetchone()
            maximum = conn.execute(sql.SQL('SELECT max({}) FROM {}').format(sql.Identifier(column),sql.Identifier(table))).fetchone()[0]
            sequence_checks.append(maximum is None or last > maximum or (last == maximum and called))
print(json.dumps({'tables':tables, 'files':media_manifest('/restore/media'),
    'sequence_checks':len(sequence_checks), 'sequence_safe':all(sequence_checks)}))
'''


def assert_equal(expected, restored):
    """Exact equality includes removed/added tables, rows, files and bytes."""
    checks = {
        'all_table_rows_equal': bool(expected['tables']) and expected['tables'] == restored['tables'],
        'all_media_bytes_equal': expected['files'] == restored['files'],
        'filefield_references_exist': expected['missing_references'] == 0,
        'restored_sequences_safe': restored['sequence_safe'],
    }
    return checks


def backup_directory(path):
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError('Backup directory must be outside the repository')
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', type=Path, required=True,
                        help='New private directory outside the repository; never overwritten')
    args = parser.parse_args()
    folder = backup_directory(args.backup_dir)
    suffix = uuid.uuid4().hex[:12]
    name = 'campus-recovery-' + suffix
    network, db, probe, volume = [name + '-' + s for s in ('net', 'db', 'probe', 'pgdata')]
    source = None
    db_started = False
    evidence = {'started_at':datetime.now(timezone.utc).isoformat(),
                'scope':'local isolated recovery observation; not agreed RPO/RTO or independent acceptance',
                'source_business_writes':False, 'external_calls':False,
                'checks':{}, 'passed':False}
    log = (folder / 'private-diagnostics.log').open('w', encoding='utf-8')

    def run(args, *, binary=False, timeout=180):
        result = subprocess.run(['docker', *args], cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout)
        if result.stderr:
            log.write(result.stderr.decode('utf-8', errors='replace')); log.flush()
        if result.returncode:
            # Docker/SQL diagnostics can contain private row values.
            raise RuntimeError('Docker operation failed; see private-diagnostics.log')
        return result.stdout if binary else result.stdout.decode('utf-8').strip()

    def service(name):
        cid = run(['compose','ps','-q',name])
        if not cid or '\n' in cid:
            raise RuntimeError('Exactly one running Compose service required: ' + name)
        state = json.loads(run(['inspect',cid]))[0]
        if state['Config']['Labels'].get('com.docker.compose.oneoff', '').lower() != 'false':
            raise RuntimeError('One-off containers cannot be used as source')
        return cid, state

    started = time.monotonic()
    try:
        source_db, db_info = service('db')
        backend, backend_info = service('backend')
        evidence['commit'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        evidence['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        evidence['database_image'] = db_info['Image']
        evidence['backend_image'] = backend_info['Image']
        env = dict(item.split('=',1) for item in db_info['Config']['Env'] if '=' in item)
        remote_dump, remote_media = '/tmp/'+name+'.dump', '/tmp/'+name+'.tar.gz'
        source = subprocess.Popen(['docker','exec','-i',backend,'python','-u','-c',SOURCE,remote_media],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding='utf-8')
        # A bounded read also detects early source failure; no credentials printed.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                line = pool.submit(source.stdout.readline).result(timeout=120)
            except TimeoutError:
                source.kill()
                raise RuntimeError('Source snapshot timed out') from None
        if not line:
            raise RuntimeError('Source snapshot failed; see private diagnostics')
        expected = json.loads(line)
        run(['exec',source_db,'pg_dump','-U',env['POSTGRES_USER'],'-d',env['POSTGRES_DB'],
             '--format=custom','--no-owner','--no-acl','--snapshot='+expected['snapshot'],'--file='+remote_dump])
        source.communicate('release\n', timeout=15)
        if source.returncode:
            raise RuntimeError('Source snapshot release failed')
        run(['cp',source_db+':'+remote_dump,str(folder/'database.dump')])
        run(['cp',backend+':'+remote_media,str(folder/'media.tar.gz')])
        (folder/'source-private.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
        evidence['backup_seconds'] = round(time.monotonic()-started,3)
        evidence['backup'] = {}
        for filename in ('database.dump','media.tar.gz'):
            path = folder/filename
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream,'sha256').hexdigest()
            evidence['backup'][filename] = {'bytes':path.stat().st_size,'sha256':digest}
        restored_at = time.monotonic()
        run(['network','create','--internal',network])
        run(['volume','create',volume])
        run(['run','-d','--name',db,'--network',network,'--mount','type=volume,source='+volume+',target=/var/lib/postgresql/data',
             '-e','POSTGRES_USER=recovery','-e','POSTGRES_DB=recovery','-e','POSTGRES_HOST_AUTH_METHOD=trust',db_info['Image']])
        db_started = True
        # pg_isready is polled against this specific isolated container only.
        deadline = time.monotonic()+60
        while True:
            ready = subprocess.run(['docker','exec',db,'pg_isready','-U','recovery','-d','recovery'],capture_output=True)
            if ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Isolated PostgreSQL readiness timed out')
            time.sleep(1)
        run(['cp',str(folder/'database.dump'),db+':/tmp/database.dump'])
        run(['exec',db,'pg_restore','--exit-on-error','--no-owner','--no-acl','-U','recovery','-d','recovery','/tmp/database.dump'])
        run(['create','--name',probe,'--network',network,'--entrypoint','python',
             '-e','POSTGRES_HOST='+db,'-e','POSTGRES_DB=recovery','-e','POSTGRES_USER=recovery',
             backend_info['Image'],'-u','-c',RESTORE])
        net_info = json.loads(run(['network','inspect',network]))[0]
        db_state = json.loads(run(['inspect',db]))[0]
        probe_state = json.loads(run(['inspect',probe]))[0]
        isolated = (net_info['Internal'] and not db_state['HostConfig']['PortBindings']
                    and not probe_state['HostConfig']['PortBindings']
                    and set(db_state['NetworkSettings']['Networks']) == {network}
                    and set(probe_state['NetworkSettings']['Networks']) == {network})
        if not isolated:
            raise RuntimeError('Recovery network isolation check failed')
        run(['cp',str(folder/'media.tar.gz'),probe+':/tmp/media.tar.gz'])
        output = run(['start','-a',probe])
        exit_code = run(['inspect','--format','{{.State.ExitCode}}',probe])
        if exit_code != '0':
            raise RuntimeError('Isolated manifest failed; see private diagnostics')
        restored = json.loads(output)
        (folder/'restored-private.json').write_text(json.dumps(restored,ensure_ascii=False,indent=2),encoding='utf-8')
        evidence['checks'] = assert_equal(expected,restored)
        evidence['checks']['internal_network_without_published_ports'] = isolated
        evidence['restoration_and_verification_seconds'] = round(time.monotonic()-restored_at,3)
        evidence['tables'] = expected['tables']
        evidence['media_files'] = len(expected['files'])
        evidence['media_bytes'] = sum(v['bytes'] for v in expected['files'].values())
        evidence['filefield_references'] = expected['filefield_references']
        evidence['sequence_checks'] = restored['sequence_checks']
        evidence['passed'] = all(evidence['checks'].values())
        if not evidence['passed']:
            raise RuntimeError('Recovery comparison failed; both manifests retained')
    finally:
        if source is not None and source.poll() is None:
            source.kill()
            source.communicate(timeout=15)
        if db_started:
            try:
                run(['stop',db],timeout=45)
            except (RuntimeError,subprocess.TimeoutExpired):
                evidence['stop_failed'] = True
        # Preserve backups, stopped recovery DB and probe for review. Never
        # issue rm/down/prune or touch source services/volumes.
        evidence['recovery_resources'] = {'database':db,'probe':probe,'volume':volume,'network':network}
        evidence['finished_at'] = datetime.now(timezone.utc).isoformat()
        evidence['total_seconds'] = round(time.monotonic()-started,3)
        (folder/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        log.close()
    print(json.dumps({'passed':evidence['passed'],'checks':evidence['checks'],
                      'table_count':len(evidence['tables']),'media_files':evidence['media_files'],
                      'seconds':evidence['total_seconds']},ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
