#!/usr/bin/env python3
"""Gateway-host operator install/verify. Never calls a model or restarts a Gateway."""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.services.agent_connections.gateway_config import configure, verify_config
from src.services.agent_connections.manifest import canonical, digest, receipt, validate_manifest
from src.services.secret_store import SecretStore


def private_write(path, content):
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_openclaw(path, token_env, executable):
    env = {**os.environ, **token_env, 'OPENCLAW_CONFIG_PATH': str(path)}
    result = subprocess.run([executable, 'config', 'validate'], env=env, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('OpenClaw configuration validation failed (raw output suppressed)')


async def check_mcp(manifest, token, *, transport=None):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with asyncio.timeout(40):
        async with httpx.AsyncClient(transport=transport, headers={'Authorization': 'Bearer ' + token},
                                     timeout=30, follow_redirects=False) as client:
            async with streamable_http_client(manifest['mcp_url'], http_client=client,
                                               terminate_on_close=False) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    if not set(manifest['tools']) <= names or any(
                            not tool.annotations or tool.annotations.readOnlyHint is not True
                            for tool in tools.tools if tool.name in manifest['tools']):
                        raise ValueError('MCP tools differ from personal read-only policy')
                    result = await session.call_tool('list_subscriptions', {})
                    if result.isError:
                        raise ValueError('Personal MCP read failed')


def install(root, manifest, token, executable):
    config_path = root / 'openclaw.json'
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError('Regular OpenClaw config required')
    current = json.loads(config_path.read_text())
    target = configure(current, manifest, root)
    candidate = root / ('.agent-config-' + uuid.uuid4().hex + '.json')
    try:
        private_write(candidate, json.dumps(target, indent=2) + '\n')
        secrets = SecretStore(root, filename='.env')
        environment = {**secrets.read(), manifest['secret_ref']: token}
        validate_openclaw(candidate, environment, executable)
        for field in ('workspace', 'agentDir'):
            directory = Path(target['agents']['entries'][manifest['agent_id']][field])
            if directory.resolve() != directory:
                raise ValueError('Managed directories must not use symlinks')
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        verify_config(target, manifest, root)
        # Backups can contain legacy secrets and remain local/private.
        private_write(root / ('openclaw.pre-agent-' + uuid.uuid4().hex + '.json'), config_path.read_text())
        secrets.set(manifest['secret_ref'], token)
        os.replace(candidate, config_path)
    finally:
        candidate.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'verify'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--bundle-dir', type=Path, required=True)
    parser.add_argument('--openclaw', default='openclaw')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    try:
        root = args.root.expanduser().resolve()
        manifest = validate_manifest(json.loads((args.bundle_dir / 'manifest.json').read_text()))
        token_path = args.bundle_dir / 'token'
        if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
            raise ValueError('Token file must be private and regular')
        token = token_path.read_text().strip()
        if hashlib.sha256(token.encode()).hexdigest() != manifest['token_sha256']:
            raise ValueError('Token and manifest do not match')
        if args.action == 'install':
            install(root, manifest, token, args.openclaw)
            result = {'status': 'installed_pending_verification'}
        else:
            if not args.receipt:
                parser.error('--receipt required for verify')
            config = json.loads((root / 'openclaw.json').read_text())
            verify_config(config, manifest, root)
            environment = SecretStore(root, filename='.env').read()
            if environment.get(manifest['secret_ref']) != token:
                raise ValueError('Installed credential differs')
            validate_openclaw(root / 'openclaw.json', environment, args.openclaw)
            asyncio.run(check_mcp(manifest, token))
            private_write(args.receipt, canonical(receipt(manifest, token, digest(config))) + '\n')
            result = {'status': 'verified', 'binding_id': manifest['binding_id']}
        print(json.dumps(result))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'reason': str(error) if type(error) is ValueError else 'Check inputs and target environment'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
