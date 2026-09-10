"""Provisioning writes only personal config and verifies live application."""
import asyncio
import json

import pytest

from tests.test_agent_connections import personal
from src.services.agent_connections.managed_host import ManagedHost, ManagedSetupError
from src.services.secret_store import SecretStore


class Gateway:
    def __init__(self, root, *, apply=True, drift=False, fail=False):
        self.root, self.apply, self.drift, self.fail = root, apply, drift, fail
        self.frames, self.writes = [], []

    async def _session(self, operation):
        return await operation(self, {'features': {'methods': ['config.get', 'config.patch', 'agents.list']}})

    async def _request(self, socket, identity, method, params):
        path = self.root / 'openclaw.json'
        current = json.loads(path.read_text())
        if method == 'config.get':
            if self.drift and identity == 'setup-config':
                path.write_text(json.dumps({**current, 'changed': True}))
            return {'path': str(path), 'hash': 'version', 'configRevisionHash': 'new',
                    'appliedConfigHash': 'new' if self.apply else 'old'}
        assert method == 'config.patch'
        assert json.loads(params['raw'])['agents']['ownership'] == 'explicit'
        self.writes.append(params)
        if self.fail:
            raise ValueError('rejected')
        def merge(target, patch):
            for key, value in patch.items():
                if value is None:
                    target.pop(key, None)
                elif isinstance(value, dict):
                    merge(target.setdefault(key, {}), value)
                else:
                    target[key] = value
        merge(current, json.loads(params['raw']))
        path.write_text(json.dumps(current))
        return {'ok': True}

    async def send(self, raw):
        request = json.loads(raw)
        assert request['method'] == 'agents.list'
        config = json.loads((self.root / 'openclaw.json').read_text())
        self.frames.append(json.dumps({'type': 'res', 'id': request['id'], 'ok': True,
                                      'payload': {'agents': [{'id': key} for key in config['agents']['entries']]}}))

    async def recv(self):
        return self.frames.pop(0)


@pytest.fixture
def installation(personal, tmp_path):
    _, connections, alice, _ = personal
    manifest = connections.prepare(alice['id'], 'http://localhost:8080/mcp')
    _, token = connections.export(alice['id'])
    root = tmp_path / 'gateway'
    root.mkdir()
    (root / 'openclaw.json').write_text(json.dumps({'agents': {'entries': {'main': {'model': 'keep-model', 'default': True}}},
                                                 'mcp': {'servers': {'fsj': {'url': 'https://example.test/mcp'}}}}))
    SecretStore(root, filename='.env').set('OTHER_TOKEN', 'untouched')
    host = ManagedHost.__new__(ManagedHost)
    host.root, host.gateway = root, Gateway(root)
    return host, manifest, token


def test_install_preserves_other_config_and_secret_and_creates_private_backup(installation):
    host, manifest, token = installation
    result = asyncio.run(host.install(manifest, token))
    assert result['agents']['entries']['main']['model'] == 'keep-model'
    assert result['agents']['ownership'] == 'explicit'
    assert 'default' not in result['agents']['entries']['main']
    assert result['mcp']['servers']['fsj']['url'] == 'https://example.test/mcp'
    assert SecretStore(host.root, filename='.env').read()['OTHER_TOKEN'] == 'untouched'
    assert token not in json.dumps(result) + json.dumps(host.gateway.writes)
    backups = list(host.root.glob('inteliscope-setup-backup-*'))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o700
    assert (backups[0] / '.env').stat().st_mode & 0o777 == 0o600
    assert asyncio.run(host.install(manifest, token)) == result
    assert len(host.gateway.writes) == 1


def test_manual_drift_fails_before_secret_or_gateway_write(installation):
    host, manifest, token = installation
    host.gateway.drift = True
    with pytest.raises(ManagedSetupError):
        asyncio.run(host.install(manifest, token))
    assert not host.gateway.writes
    assert manifest['secret_ref'] not in SecretStore(host.root, filename='.env').read()
    assert json.loads((host.root / 'openclaw.json').read_text())['changed'] is True


def test_rejected_patch_rolls_back_only_new_secret(installation):
    host, manifest, token = installation
    host.gateway.fail = True
    with pytest.raises(ValueError):
        asyncio.run(host.install(manifest, token))
    assert SecretStore(host.root, filename='.env').read() == {'OTHER_TOKEN': 'untouched'}


def test_not_loaded_never_reports_success_and_retry_verifies_without_rewrite(installation):
    host, manifest, token = installation
    host.gateway.apply = False
    with pytest.raises(ManagedSetupError, match='等待安全重载'):
        asyncio.run(host.install(manifest, token))
    host.gateway.apply = True
    asyncio.run(host.install(manifest, token))
    assert len(host.gateway.writes) == 1


def test_secret_write_failure_does_not_submit_config(installation, monkeypatch):
    host, manifest, token = installation
    def fail(*args):
        raise OSError('test-only credential failure')
    monkeypatch.setattr(SecretStore, 'set', fail)
    with pytest.raises(OSError):
        asyncio.run(host.install(manifest, token))
    assert not host.gateway.writes
    assert SecretStore(host.root, filename='.env').read() == {'OTHER_TOKEN': 'untouched'}


def test_disabled_hot_reload_never_schedules_a_restart(installation):
    host, manifest, token = installation
    path = host.root / 'openclaw.json'
    config = json.loads(path.read_text())
    config['gateway'] = {'reload': {'mode': 'off'}}
    path.write_text(json.dumps(config))
    with pytest.raises(ManagedSetupError, match='安全热加载'):
        asyncio.run(host.install(manifest, token))
    assert not host.gateway.writes
    assert SecretStore(host.root, filename='.env').read() == {'OTHER_TOKEN': 'untouched'}


def test_unknown_patch_result_is_checked_before_retry(installation, monkeypatch):
    host, manifest, token = installation
    request = host.gateway._request
    async def uncertain(socket, identity, method, params):
        result = await request(socket, identity, method, params)
        if method == 'config.patch':
            raise TimeoutError('response lost after write')
        return result
    monkeypatch.setattr(host.gateway, '_request', uncertain)
    with pytest.raises(TimeoutError):
        asyncio.run(host.install(manifest, token))
    assert SecretStore(host.root, filename='.env').read()[manifest['secret_ref']] == token
    monkeypatch.setattr(host.gateway, '_request', request)
    asyncio.run(host.install(manifest, token))
    assert len(host.gateway.writes) == 1
