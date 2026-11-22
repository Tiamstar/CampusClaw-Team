"""Generate a separate production configuration; never copy local credentials."""
import argparse
import ipaddress
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[1]


def host_value(value):
    value = value.lower()
    if len(value) > 253 or '.' not in value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.')):
        raise ValueError('Use a DNS hostname without scheme, port, path or wildcard')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError('Use a DNS hostname, not an IP address')


def create_config(target, host, email):
    host = host_value(host)
    if not re.fullmatch(r'[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+', email):
        raise ValueError('Use an ACME contact email without whitespace or configuration syntax')
    host_value(email.rsplit('@', 1)[1])
    text = (ROOT / '.env.example').read_text(encoding='utf-8')
    for key in ['DJANGO_SECRET_KEY', 'POSTGRES_PASSWORD', 'MCP_CAMPUS_TOKEN', 'SANDBOX_TOKEN']:
        text = text.replace(f'{key}=\n', f'{key}={secrets.token_urlsafe(48)}\n')
    text += f'\n# Dedicated HTTPS deployment; set real model/SMTP values before public acceptance.\nPUBLIC_HOST={host}\nACME_EMAIL={email}\n'
    # Exclusive create prevents overwriting local or production configuration.
    with Path(target).open('x', encoding='utf-8') as stream:
        stream.write(text)
    Path(target).chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / '.env.production')
    args = parser.parse_args()
    try:
        create_config(args.output, args.host, args.email)
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, str(exc) + '\n')
    print('Created separate configuration with new random credentials. Configure real external services before public acceptance.')


if __name__ == '__main__':
    main()
