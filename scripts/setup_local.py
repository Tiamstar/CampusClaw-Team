"""Create a local configuration once, without printing credentials."""
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / '.env'
if target.exists():
    print('Existing .env preserved.')
else:
    text = (ROOT / '.env.example').read_text(encoding='utf-8')
    for key in ['DJANGO_SECRET_KEY', 'POSTGRES_PASSWORD', 'MCP_CAMPUS_TOKEN', 'SANDBOX_TOKEN']:
        text = text.replace(f'{key}=\n', f'{key}={secrets.token_urlsafe(48)}\n')
    with target.open('x', encoding='utf-8') as output:
        output.write(text)
    target.chmod(0o600)
    print('Created .env with random local credentials. Model mode is mock.')
