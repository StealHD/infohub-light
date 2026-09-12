import asyncio
import json
import pytest
from tests.test_agent_connections import personal  # noqa: F401
from tests.test_agent_managed_host import installation, Gateway  # noqa: F401
from src.services.agent_connections.analysis_host import install, registry_path
from src.services.agent_connections.analysis_cleanup import remove
from src.services.agent_connections.managed_host import ManagedSetupError, host_lock
from src.services.secret_store import SecretStore


class AnalysisGateway(Gateway):
    async def _request(self, socket, identity, method, params):
        if method == 'models.list':
            return {'models': [{'id': 'model', 'provider': 'test', 'name': 'Test', 'available': True}]}
        if method == 'agents.list':
            return {'agents': [{'id': key} for key in json.loads((self.root / 'openclaw.json').read_text())['agents']['entries']]}
        if method in {'sessions.list', 'cron.list'}:
            return {'sessions': [], 'jobs': [], 'total': 0}
        if method == 'config.patch':
            self.writes.append(params)
            path = self.root / 'openclaw.json'
            config = json.loads(path.read_text())
            def merge(target, patch):
                for key, value in patch.items():
                    if value is None:
                        target.pop(key, None)
                    elif isinstance(value, dict):
                        merge(target.setdefault(key, {}), value)
                    else:
                        target[key] = value
            merge(config, json.loads(params['raw']))
            path.write_text(json.dumps(config))
            return {}
        return await super()._request(socket, identity, method, params)


def prepared(installation):
    host, base, personal_token = installation
    asyncio.run(host.install(base, personal_token))
    host.gateway = AnalysisGateway(host.root)
    token = 'ih_ic_v1_' + base['binding_id'] + '.' + 'a' * 43
    return host, base, token


def test_install_idempotent_catalog_bounded_and_cleanup_preserves_shared_state(installation):
    host, base, token = prepared(installation)
    first = asyncio.run(install(host, base, token))
    assert first['capabilities']['models'][0]['id'] == 'test/model'
    assert asyncio.run(install(host, base, token)) == first
    assert len(host.gateway.writes) == 1
    config = json.loads((host.root / 'openclaw.json').read_text())
    assert 'allowedCompletionModels' not in config['plugins']['entries']['llm-task']['llm']
    path = registry_path(host.root, base)
    assert path.stat().st_mode & 0o077 == 0
    assert token not in path.read_text() + json.dumps(config) + json.dumps(host.gateway.writes)
    asyncio.run(remove(host, base))
    after = json.loads((host.root / 'openclaw.json').read_text())
    assert 'ic-' + base['binding_id'] not in after['agents']['entries']
    assert after['agents']['entries']['main'] == config['agents']['entries']['main']
    assert after['mcp'] == config['mcp'] and after['plugins'] == config['plugins']
    assert 'INTELISCOPE_CONNECTOR_' + base['binding_id'].upper() not in SecretStore(host.root, filename='.env').read()
    asyncio.run(remove(host, base))
    with pytest.raises(ManagedSetupError):
        asyncio.run(install(host, base, token))


def test_explicit_model_prohibition_never_widened(installation):
    host, base, token = prepared(installation)
    path = host.root / 'openclaw.json'
    config = json.loads(path.read_text())
    config['plugins'] = {'entries': {'llm-task': {'enabled': False}}}
    path.write_text(json.dumps(config))
    with pytest.raises(ManagedSetupError, match='明确禁止'):
        asyncio.run(install(host, base, token))
    assert json.loads(path.read_text()) == config
    assert not host.gateway.writes


def test_inflight_completion_fences_claims_without_false_cleanup_success(installation):
    host, base, token = prepared(installation)
    asyncio.run(install(host, base, token))
    directory = host.root / 'managed' / ('ic-' + base['binding_id'])
    with host_lock(directory):
        with pytest.raises(ManagedSetupError):
            asyncio.run(remove(host, base))
    assert json.loads(registry_path(host.root, base).read_text())['state'] == 'revoked'
    assert 'ic-' + base['binding_id'] in json.loads((host.root / 'openclaw.json').read_text())['agents']['entries']
    asyncio.run(remove(host, base))


def test_lost_completion_result_is_not_mistaken_for_stopped_runtime(installation):
    from src.services.information_automations.completion_guard import record
    host, base, token = prepared(installation)
    asyncio.run(install(host, base, token))
    directory = host.root / 'managed' / ('ic-' + base['binding_id'])
    record(directory / 'result.json', 'claim', 'ic-' + base['binding_id'], 'inflight')
    with pytest.raises(ManagedSetupError, match='结束状态尚未确认'):
        asyncio.run(remove(host, base))
    assert json.loads(registry_path(host.root, base).read_text())['state'] == 'revoked'
