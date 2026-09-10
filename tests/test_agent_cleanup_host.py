import asyncio
import json
import pytest
from tests.test_agent_connections import personal
from tests.test_agent_managed_host import installation, Gateway
from src.services.agent_connections.cleanup_host import CleanupHost
from src.services.agent_connections.managed_host import ManagedSetupError
from src.services.secret_store import SecretStore


class CleanupGateway(Gateway):
    async def _session(self, operation):
        return await operation(self, {'features': {'methods': ['config.get', 'config.patch', 'agents.list',
                                                               'sessions.list', 'chat.abort', 'cron.list', 'cron.update']}})

    async def _request(self, socket, identity, method, params):
        if method == 'sessions.list':
            return {'sessions': [], 'totalCount': 0}
        if method == 'cron.list':
            return {'jobs': [], 'total': 0}
        path = self.root / 'openclaw.json'
        if method == 'agents.list':
            return {'agents': [{'id': key} for key in json.loads(path.read_text())['agents']['entries']]}
        if method == 'config.patch':
            current = json.loads(path.read_text())
            patch = json.loads(params['raw'])
            assert len(patch['agents']['entries']) == len(patch['mcp']['servers']) == 1
            assert all(value is None for value in patch['agents']['entries'].values())
            for name in patch['agents']['entries']:
                current['agents']['entries'].pop(name, None)
            for name in patch['mcp']['servers']:
                current['mcp']['servers'].pop(name, None)
            path.write_text(json.dumps(current))
            self.writes.append(params)
            return {}
        return await super()._request(socket, identity, method, params)


def test_cleanup_preserves_history_other_agents_and_is_idempotent(installation):
    installed, manifest, token = installation
    before = asyncio.run(installed.install(manifest, token))
    history = installed.root / 'managed' / manifest['agent_id'] / 'workspace' / 'history.txt'
    history.write_text('retain history')
    host = CleanupHost.__new__(CleanupHost)
    host.root, host.gateway = installed.root, CleanupGateway(installed.root)
    phases = []
    asyncio.run(host.remove(manifest, phases.append))
    after = json.loads((host.root / 'openclaw.json').read_text())
    assert manifest['agent_id'] not in after['agents']['entries']
    assert manifest['mcp_server'] not in after['mcp']['servers']
    assert after['agents']['entries']['main'] == before['agents']['entries']['main']
    assert after['mcp']['servers']['fsj'] == before['mcp']['servers']['fsj']
    assert history.read_text() == 'retain history'
    assert SecretStore(host.root, filename='.env').read() == {'OTHER_TOKEN': 'untouched'}
    asyncio.run(host.remove(manifest, phases.append))
    assert len(host.gateway.writes) == 0  # no destructive roster RPC or session-index purge
    assert phases[-1] == 'verifying'


def test_changed_target_configuration_is_not_removed(installation):
    installed, manifest, token = installation
    config = asyncio.run(installed.install(manifest, token))
    config['agents']['entries'][manifest['agent_id']]['workspace'] = '/another-workspace'
    (installed.root / 'openclaw.json').write_text(json.dumps(config))
    host = CleanupHost.__new__(CleanupHost)
    host.root, host.gateway = installed.root, CleanupGateway(installed.root)
    with pytest.raises(ManagedSetupError):
        asyncio.run(host.remove(manifest, lambda _: None))
    assert not host.gateway.writes
    assert SecretStore(host.root, filename='.env').read()[manifest['secret_ref']] == token


def test_derived_monitor_retained_then_reclaimed_by_gateway(installation):
    installed, manifest, token = installation
    asyncio.run(installed.install(manifest, token))
    class DerivedGateway(CleanupGateway):
        async def _request(self, socket, identity, method, params):
            if method == 'cron.list':
                present = manifest['agent_id'] in json.loads((self.root / 'openclaw.json').read_text())['agents']['entries']
                return {'jobs': [{'id': 'derived', 'agentId': manifest['agent_id'], 'enabled': True,
                    'declarationKey': 'skill-collection-review:' + manifest['agent_id'],
                    'payload': {'kind': 'skillCollectionReview'}}] if present else []}
            assert method not in {'cron.update', 'cron.remove', 'agents.delete'}
            return await super()._request(socket, identity, method, params)
    host = CleanupHost.__new__(CleanupHost)
    host.root, host.gateway = installed.root, DerivedGateway(installed.root)
    asyncio.run(host.remove(manifest, lambda _: None))
    archives = list(host.root.glob('inteliscope-setup-backup-*/retained-monitor-records.json'))
    assert len(archives) == 1 and archives[0].stat().st_mode & 0o777 == 0o600
    assert json.loads(archives[0].read_text())['records'][0]['id'] == 'derived'


def test_unreclaimed_monitor_never_reports_complete(installation, monkeypatch):
    installed, manifest, token = installation
    asyncio.run(installed.install(manifest, token))
    class StaleGateway(CleanupGateway):
        async def _request(self, socket, identity, method, params):
            if method == 'cron.list':
                return {'jobs': [{'id': 'derived', 'agentId': manifest['agent_id'], 'enabled': True,
                    'declarationKey': 'skill-collection-review:' + manifest['agent_id'],
                    'payload': {'kind': 'skillCollectionReview'}}]}
            return await super()._request(socket, identity, method, params)
    async def no_sleep(*args): pass
    monkeypatch.setattr('src.services.agent_connections.cleanup_host.asyncio.sleep', no_sleep)
    host = CleanupHost.__new__(CleanupHost)
    host.root, host.gateway = installed.root, StaleGateway(installed.root)
    from src.services.agent_connections.cleanup_host import CleanupBlocked
    with pytest.raises(CleanupBlocked):
        asyncio.run(host.remove(manifest, lambda _: None))


def test_atomic_removal_preserves_concurrent_configuration(installation):
    from src.services.agent_connections.cleanup_config import remove_config
    installed, manifest, token = installation
    asyncio.run(installed.install(manifest, token))
    path = installed.root / 'openclaw.json'
    before = path.read_bytes()
    changed = json.loads(before)
    changed['manual_setting'] = 'preserve'
    path.write_text(json.dumps(changed))
    with pytest.raises(ManagedSetupError):
        remove_config(installed.root, before, manifest)
    assert json.loads(path.read_text()) == changed
    assert not list(installed.root.glob('.inteliscope-remove-*'))
