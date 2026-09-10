"""Remote adapter safety, pinned service, receipts and durable revocation fence."""
import asyncio
import hashlib
import json
import sys
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.agent_connections import host_command, ssh_host
from src.services.agent_connections.manifest import READ_TOOLS, receipt
from src.services.agent_connections.host_dispatch import installation_digest


@pytest.fixture
def manifest():
    identity = '1' * 32
    return {'version': 2, 'binding_id': identity, 'agent_id': 'ih-' + identity,
            'mcp_server': 'ih_' + identity[:24], 'secret_ref': 'INTELISCOPE_MCP_' + identity,
            'user_id': 'member', 'workspace_id': 'workspace', 'delegation_id': 'delegation',
            'mcp_url': 'https://service.example/mcp', 'token_sha256': hashlib.sha256(b'test-token').hexdigest(),
            'tools': list(READ_TOOLS), 'skills': []}


def test_pinned_manifest_rejects_extra_paths_tokens_and_other_services(manifest):
    payload = {'action': 'install', 'manifest': manifest, 'token': 'test-token'}
    assert host_command.validate_request(payload, manifest['mcp_url']) == manifest
    for bad in ({**payload, 'root': '/elsewhere'}, {**payload, 'token': 'wrong'},
                {**payload, 'action': 'exec'}, {**payload, 'manifest': {**manifest, 'agent_id': 'main'}}):
        with pytest.raises(ValueError):
            host_command.validate_request(bad, manifest['mcp_url'])
    with pytest.raises(ValueError):
        host_command.validate_request(payload, 'https://other.example/mcp')


def test_ssh_uses_only_fixed_command_and_pinned_private_files(tmp_path, monkeypatch):
    for name in ('KEY', 'KNOWN_HOSTS'):
        path = tmp_path / name
        path.touch(mode=0o600)
        monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_SSH_' + name, str(path))
    monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_SSH_HOST', 'gateway.example')
    monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_SSH_USER', 'ubuntu')
    argv = ssh_host.command()
    assert argv[-2:] == ['ubuntu@gateway.example', 'inteliscope-managed-v1']
    assert 'StrictHostKeyChecking=yes' in argv and '/dev/null' in argv
    for invalid in ('-oProxyCommand=bad', 'host;id', 'host\nother'):
        monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_SSH_HOST', invalid)
        with pytest.raises(ValueError):
            ssh_host.command()
    path.chmod(0o644)
    with pytest.raises(ValueError):
        ssh_host.protected_file(str(path))


def test_remote_proof_is_verified_before_activation(manifest):
    host = object.__new__(ssh_host.SSHHost)
    async def call(payload):
        return receipt(manifest, 'test-token', 'a' * 64)
    host.call = call
    result = asyncio.run(host.install(manifest, 'test-token'))
    assert installation_digest(result) == 'a' * 64
    with pytest.raises(ValueError):
        asyncio.run(host.install(manifest, 'wrong'))


def test_cleanup_fences_reinstall_and_resumes_same_manifest(tmp_path, monkeypatch, manifest):
    calls = []
    class Host:
        def __init__(self, context):
            self.root = tmp_path
        async def install(self, value, token):
            calls.append('install')
            return {}
        async def remove(self, value, advance):
            calls.append('remove')
            advance('verifying')
    monkeypatch.setattr(host_command, 'Host', Host)
    monkeypatch.setattr(host_command, 'RemovalHost', Host)
    monkeypatch.setenv('INTELISCOPE_MANAGED_MCP_URL', manifest['mcp_url'])
    async def check(*args):
        calls.append('mcp')
    monkeypatch.setattr(host_command, 'check_mcp', check)
    from src.services.agent_connections import native_mcp_probe
    async def check_native(*args):
        calls.append('native')
    monkeypatch.setattr(native_mcp_probe, 'check', check_native)
    install = {'action': 'install', 'manifest': manifest, 'token': 'test-token'}
    remove = {'action': 'remove', 'manifest': manifest}
    run = lambda value: asyncio.run(host_command.execute(value, None, lambda _: None))
    assert run(install)['binding_id'] == manifest['binding_id']
    assert run(remove)['removed'] is True
    assert run(remove)['removed'] is True
    with pytest.raises(ValueError, match='Revoked'):
        run(install)
    with pytest.raises(ValueError, match='changed'):
        run({**remove, 'manifest': {**manifest, 'user_id': 'another'}})
    assert calls == ['install', 'native', 'mcp', 'remove', 'remove']


def test_process_progress_exit_status_and_redaction():
    host = object.__new__(ssh_host.SSHHost)
    host.command = [sys.executable, '-c',
                    'import sys; sys.stdin.readline(); print(\'{"phase":"stopping"}\', flush=True); sys.stdin.readline(); print(\'{"result":{"ok":true}}\')']
    phases = []
    assert asyncio.run(host.call({'action': 'remove'}, phases.append)) == {'ok': True}
    assert phases == ['stopping']
    host.command = [sys.executable, '-c',
                    'import sys; sys.stdin.readline(); print("secret-test-token"); sys.exit(1)']
    with pytest.raises(ValueError) as error:
        asyncio.run(host.call({'token': 'secret-test-token'}))
    assert 'secret-test-token' not in str(error.value)


def test_failed_cleanup_keeps_revocation_fence(tmp_path, monkeypatch, manifest):
    class Host:
        def __init__(self, context):
            self.root = tmp_path
        async def remove(self, value, advance):
            raise RuntimeError('gateway offline')
    monkeypatch.setattr(host_command, 'RemovalHost', Host)
    monkeypatch.setenv('INTELISCOPE_MANAGED_MCP_URL', manifest['mcp_url'])
    with pytest.raises(RuntimeError):
        asyncio.run(host_command.execute({'action': 'remove', 'manifest': manifest}, None, lambda _: None))
    assert (tmp_path / 'inteliscope-revoked' / manifest['binding_id']).is_file()


def test_cleanup_does_not_acknowledge_lost_administrator_authority(tmp_path):
    marker = tmp_path / 'unauthorized'
    host = object.__new__(ssh_host.SSHHost)
    host.command = [sys.executable, '-c',
                    'import sys,pathlib; sys.stdin.readline(); print(\'{"phase":"removing"}\',flush=True); '
                    'ack=sys.stdin.readline(); pathlib.Path(sys.argv[1]).touch() if ack else None', str(marker)]
    def denied(phase):
        raise PermissionError('revoked administrator')
    with pytest.raises(ValueError):
        asyncio.run(host.call({'action': 'remove'}, denied))
    assert not marker.exists()


def test_installer_preserves_operator_keys_and_refuses_overwrite(tmp_path, monkeypatch):
    from scripts import configure_managed_host as installer
    root, deployment = tmp_path / 'openclaw', tmp_path / 'adapter'
    root.mkdir()
    deployment.mkdir()
    (root / 'openclaw.json').write_text(json.dumps({'gateway': {'auth': {'token': 'fixture-token'}}}))
    (root / 'openclaw.mjs').write_text('// controlled installation')
    ssh = tmp_path / '.ssh'
    ssh.mkdir()
    authorized = ssh / 'authorized_keys'
    authorized.write_text('# existing operator key stays\n')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, 'argv', ['install', '--root', str(root), '--deployment', str(deployment),
                                    '--source-ip', '192.0.2.1', '--mcp-url', 'https://service.example/mcp', '--openclaw-package', str(root)])
    monkeypatch.setattr(sys, 'stdin', io.StringIO('ssh-ed25519 AAAAtest dedicated'))
    installer.main()
    result = authorized.read_text()
    assert result.startswith('# existing operator key stays\n')
    assert 'restrict,from="192.0.2.1",command=' in result
    assert 'scripts.managed_host_command' in result
    assert 'fixture-token' not in result
    assert (deployment / 'host.env').stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(sys, 'stdin', io.StringIO('ssh-ed25519 AAAAtest dedicated'))
    with pytest.raises(ValueError, match='Existing adapter'):
        installer.main()
    assert authorized.read_text() == result
