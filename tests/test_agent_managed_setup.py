"""Local-only setup, durable identities, safe retries and cross-browser ownership."""
import json
import threading
import time

import pytest

from tests.test_agent_setup_api import api, ROOT
from tests.test_agent_delegation_api import _login
from src.services.agent_connections import managed_setup
from src.services.agent_connections.managed_host import ManagedSetupError, host_lock, local_root


def settle(client):
    for _ in range(100):
        result = client.get('/api/me/agent-connection').json()['data']
        if result['setup']['state'] != 'running':
            return result
        time.sleep(.01)
    pytest.fail('setup did not finish')


@pytest.fixture
def host(api, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    class Host:
        def __init__(self, context):
            self.root = tmp_path
            self.context = context

        async def install(self, manifest, token):
            entered.set()
            assert release.wait(15)
            return {'test': 'configured'}
        async def remove(self, manifest, advance):
            advance('verifying')
        async def install_analysis(self, manifest, token):
            assert token.startswith('ih_ic_v1_' + manifest['binding_id'] + '.')
            from src.services.information_automations.connector_auth import authenticate
            from src.services.information_automations.model_catalog import Capabilities, sync_catalog
            sync_catalog(self.context.store, authenticate(self.context.store, token), Capabilities(protocol_version=2, models=[], catalog_only=True))
            return {'binding_id': manifest['binding_id'], 'capabilities': {'protocol_version': 2, 'models': []}}
    from src.services.agent_connections import cleanup
    monkeypatch.setattr(cleanup, 'CleanupHost', Host)
    monkeypatch.setattr(managed_setup, 'ManagedHost', Host)
    monkeypatch.setattr(managed_setup, 'local_root', lambda _: tmp_path)
    async def check(*args):
        return None
    monkeypatch.setattr(managed_setup, 'check_mcp', check)
    yield entered, release
    release.set()
    settle(api)


def test_two_browser_requests_share_one_binding_and_keep_fsj(api, host):
    entered, release = host
    store = api.app.state.service_store
    user = store.get_user_by_username('owner')
    old, _ = store.create_agent_delegation(workspace_id=user['workspace_id'], user_id=user['id'], name='fsj')
    before = api.get('/api/me/agent-connection').json()['data']
    assert before['state'] == 'unconfigured'
    assert api.post(ROOT + '/managed', json={'confirmed': True}).status_code == 202
    assert entered.wait(2)
    pending = api.get('/api/me/agent-connection').json()['data']
    # Logging in again yields a separate browser session, not another personal identity.
    api.post('/api/auth/logout')
    _login(api)
    assert api.post(ROOT + '/managed', json={'confirmed': True}).status_code == 202
    assert api.get('/api/me/agent-connection').json()['data']['agent_id'] == pending['agent_id']
    release.set()
    ready = settle(api)
    assert ready['state'] == 'ready'
    assert store.get_active_agent_delegation_principal(old['id'])
    context = api.app.state.api_context
    managed_setup._operations.pop(managed_setup.key(context, user))
    assert api.get('/api/me/agent-connection').json()['data']['agent_id'] == ready['agent_id']
    api.delete('/api/me/agent-connection')
    for _ in range(100):
        if api.get('/api/me/agent-connection').json()['data']['cleanup']['phase'] == 'complete':
            break
        time.sleep(.01)
    assert api.get('/api/me/agent-connection').json()['data']['state'] == 'revoked'
    api.post(ROOT + '/managed', json={'confirmed': True})
    assert settle(api)['state'] == 'revoked'
    assert api.post(ROOT + '/reconnect', json={'confirmed': False}).status_code == 400
    assert api.get('/api/me/agent-connection').json()['data']['state'] == 'revoked'
    assert api.post(ROOT + '/reconnect', json={'confirmed': True}).status_code == 202
    renewed = settle(api)
    assert renewed['state'] == 'ready'
    assert renewed['agent_id'] != ready['agent_id']
    assert not store.get_active_agent_delegation_principal(ready['delegation_id'])
    api.post(ROOT + '/reconnect', json={'confirmed': True})
    assert settle(api)['agent_id'] == renewed['agent_id']
    assert store.get_active_agent_delegation_principal(old['id'])


@pytest.mark.parametrize('role', ['member', 'viewer'])
def test_non_admin_rejected_without_host_access(api, role):
    store = api.app.state.service_store
    user = store.get_user_by_username('owner')
    store.create_user(workspace_id=user['workspace_id'], username='member', password='test-password', role=role)
    api.post('/api/auth/logout')
    _login(api, 'member', 'test-password')
    assert api.post(ROOT + '/managed', json={'confirmed': True}).status_code == 403
    assert api.post(ROOT + '/reconnect', json={'confirmed': True}).status_code == 403


def test_no_confirmation_or_identity_override_and_no_local_mode(api):
    for payload in ({'confirmed': False}, {'confirmed': 'true'}, {'confirmed': True, 'user_id': 'other'},
                    {'confirmed': True, 'root': '/tmp'}, {'confirmed': True, 'command': 'anything'}):
        assert api.post(ROOT + '/managed', json=payload).status_code == 400
    assert api.post(ROOT + '/managed', json={'confirmed': True}).status_code == 409
    assert api.get('/api/me/agent-connection').json()['data']['state'] == 'unconfigured'


def test_failed_verification_resumes_same_identity(api, host, monkeypatch):
    host[1].set()
    async def fail(*args):
        raise RuntimeError('secret-value /private/path')
    monkeypatch.setattr(managed_setup, 'check_mcp', fail)
    api.post(ROOT + '/managed', json={'confirmed': True})
    failed = settle(api)
    assert failed['state'] == 'pending_verification'
    assert 'secret-value' not in json.dumps(failed)
    async def succeed(*args):
        pass
    monkeypatch.setattr(managed_setup, 'check_mcp', succeed)
    api.post(ROOT + '/managed', json={'confirmed': True})
    ready = settle(api)
    assert ready['state'] == 'ready' and ready['agent_id'] == failed['agent_id']


def test_host_guard_rejects_remote_mismatch_and_symlinks(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED', 'true')
    monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_ROOT', str(tmp_path))
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_URL', 'ws://127.0.0.1:13789')
    (tmp_path / 'openclaw.json').write_text(json.dumps({'gateway': {'port': 13789, 'bind': 'loopback'}}))
    assert local_root('http://127.0.0.1:8080/mcp') == tmp_path
    for target in ['https://remote.example/mcp', 'http://127.0.0.1:8080/mcp?token=secret']:
        with pytest.raises(ManagedSetupError):
            local_root(target)
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_URL', 'wss://vps.example')
    with pytest.raises(ManagedSetupError):
        local_root('http://localhost:8080/mcp')
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_URL', 'ws://127.0.0.1:13789')
    (tmp_path / '.env').symlink_to(tmp_path / 'outside')
    with pytest.raises(ManagedSetupError):
        local_root('http://localhost:8080/mcp')


def test_host_lock_is_cross_process_compatible(tmp_path):
    with host_lock(tmp_path):
        with pytest.raises(ManagedSetupError):
            with host_lock(tmp_path):
                pytest.fail('second operation entered')


def test_different_accounts_keep_distinct_bindings_and_credentials(api, host):
    _, release = host
    release.set()
    store = api.app.state.service_store
    owner = store.get_user_by_username('owner')
    api.post(ROOT + '/managed', json={'confirmed': True})
    first = settle(api)
    other = store.create_user(workspace_id=owner['workspace_id'], username='second',
                              password='test-password', role='admin')
    api.post('/api/auth/logout')
    _login(api, 'second', 'test-password')
    assert api.get('/api/me/agent-connection').json()['data']['state'] == 'unconfigured'
    api.post(ROOT + '/managed', json={'confirmed': True})
    second = settle(api)
    assert first['agent_id'] != second['agent_id']
    from src.services.agent_connections.service import AgentConnections
    service = AgentConnections(store, api.app.state.api_context.secret_values)
    assert service.export(owner['id'])[1] != service.export(other['id'])[1]
    api.delete('/api/me/agent-connection')
    assert service.live(owner)
    assert not service.live(other)


def test_plaintext_transport_requires_explicit_local_only_flag(monkeypatch):
    from src.services.openclaw_relay.settings import configuration
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_TOKEN', 'test')
    monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED', 'true')
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_URL', 'ws://remote.example')
    with pytest.raises(ValueError):
        configuration()
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_URL', 'ws://127.0.0.1:13789')
    assert configuration()[0].startswith('ws://127.0.0.1:')
    monkeypatch.setenv('HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED', 'false')
    with pytest.raises(ValueError):
        configuration()
