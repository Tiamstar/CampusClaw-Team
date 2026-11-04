"""Cross-platform checks. Any failed command stops the gate."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd=ROOT):
    print('+ ' + ' '.join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--security', action='store_true')
    args = parser.parse_args()
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise SystemExit('Node.js and npm are required')
    if args.security:
        gitleaks = shutil.which('gitleaks')
        if not gitleaks:
            raise SystemExit('Install Gitleaks 8.30.1 and add it to PATH')
        run([gitleaks, 'git', '--redact', '--no-banner'])
        with tempfile.TemporaryDirectory() as folder:
            paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
            for name in set(filter(None, paths)):
                source = ROOT / name
                if source.is_file():
                    dest = Path(folder) / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, dest)
            run([gitleaks, 'dir', folder, '--redact', '--no-banner', '--report-format', 'json',
                 '--report-path', str(ROOT / 'reports' / 'secret-scan.local.json')])
        for component in ['backend', 'mcp_server', 'sandbox_runner', 'sandbox_image']:
            run([sys.executable, '-m', 'pip_audit', '-r', f'{component}/requirements.lock', '--no-deps', '--disable-pip'])
        run([npm, 'audit', '--registry=https://registry.npmjs.org', '--audit-level=high'], ROOT / 'frontend')
    else:
        run(['docker', 'compose', 'run', '--rm', '--no-deps', 'backend', 'python', 'manage.py', 'makemigrations', '--check', '--dry-run'])
        run(['docker', 'compose', 'run', '--rm', '--no-deps', '-e', 'MODEL_PROVIDER=mock', '-e', 'MODEL_NAME=mock-local', '-e', 'MODEL_API_KEY=', '-e', 'ANTHROPIC_API_KEY=', '-e', 'EMBEDDING_API_KEY=', '-e', 'EMBEDDING_MODEL=', 'backend', 'python', 'manage.py', 'test', 'core', '--noinput'])
        run([npm, 'ci'], ROOT / 'frontend')
        run([npm, 'test'], ROOT / 'frontend')
        run([npm, 'run', 'build'], ROOT / 'frontend')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
