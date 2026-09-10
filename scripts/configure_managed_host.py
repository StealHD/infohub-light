"""Operator-only installer for an existing Gateway's restricted SSH adapter."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import sys

from src.services.secret_store import SecretStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--source-ip', required=True)
    parser.add_argument('--mcp-url', required=True)
    args = parser.parse_args()
    from urllib.parse import urlsplit
    url = urlsplit(args.mcp_url)
    if url.scheme != 'https' or not url.hostname or url.path != '/mcp' or url.username or url.password or url.query or url.fragment:
        raise ValueError('Expected exact production HTTPS MCP endpoint')
    source = str(ipaddress.ip_address(args.source_ip))
    root, deployment = Path(args.root), Path(args.deployment)
    for path in (root, deployment):
        if not path.is_absolute() or path.resolve() != path or not path.is_dir():
            raise ValueError('Expected existing canonical directories')
    public = sys.stdin.read(8193).strip()
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9_-]+)?', public):
        raise ValueError('Expected dedicated public key')
    config = json.loads((root / 'openclaw.json').read_text())
    gateway = config.get('gateway', {})
    if gateway.get('bind', 'loopback') != 'loopback':
        raise ValueError('Only local protected Gateway supported')
    token = gateway.get('auth', {}).get('token')
    if isinstance(token, str) and token.startswith('${') and token.endswith('}'):
        token = SecretStore(root, filename='.env').read().get(token[2:-1])
    if not isinstance(token, str) or not token:
        raise ValueError('Resolve Gateway credential via SecretStore first')
    settings = deployment / 'host.env'
    if settings.exists() or settings.is_symlink():
        raise ValueError('Existing adapter settings must be reviewed, not overwritten')
    SecretStore(deployment, filename='host.env').replace_many({
        'HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED': 'true',
        'HORIZON_OPENCLAW_MANAGED_ROOT': str(root),
        'HORIZON_OPENCLAW_SERVER_URL': f"ws://127.0.0.1:{gateway.get('port', 18789)}",
        'HORIZON_OPENCLAW_SERVER_TOKEN': token,
        'HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN': token,
        'INTELISCOPE_MANAGED_MCP_URL': args.mcp_url,
    })
    ssh = Path.home() / '.ssh'
    if ssh.is_symlink():
        raise ValueError('Unsafe SSH directory')
    ssh.mkdir(mode=0o700, exist_ok=True)
    authorized = ssh / 'authorized_keys'
    if authorized.is_symlink():
        raise ValueError('Unsafe authorized keys')
    before = authorized.read_bytes() if authorized.exists() else b''
    if public.split()[1].encode() in before:
        raise ValueError('Key already exists; inspect restrictions instead of duplicating')
    command = 'cd ' + shlex.quote(str(deployment)) + ' && ' + shlex.join([
        str(deployment / '.venv/bin/python'), '-m', 'scripts.managed_host_command', str(settings)])
    line = f'restrict,from="{source}",command="{command}" {public}\n'
    if '"' in command or '\n' in command:
        raise ValueError('Unsafe forced command')
    backup = deployment / 'authorized_keys.before'
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(before)
    temporary = ssh / ('.inteliscope-authorized-' + str(os.getpid()))
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(before + (b'\n' if before and not before.endswith(b'\n') else b'') + line.encode())
        handle.flush()
        os.fsync(handle.fileno())
    if (authorized.read_bytes() if authorized.exists() else b'') != before:
        temporary.unlink()
        raise ValueError('SSH keys changed concurrently')
    temporary.replace(authorized)
    print('Restricted adapter configured; verify exact operator.admin device before use.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Adapter configuration failed; inspect protected state before retry.') from None
