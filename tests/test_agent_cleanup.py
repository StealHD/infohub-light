"""Revocation fails closed, owns only the selected binding, and is resumable."""
import asyncio
import json
import time
import pytest
from tests.test_agent_setup_api import api
from tests.test_agent_managed_setup import host
from tests.test_agent_access_requests import member, admin, wait_ready, ROOT
from src.services.agent_connections import cleanup, cleanup_store
from src.services.agent_connections.service import AgentConnections
from src.services.agent_connections.cleanup_host import stop_owned, check_owned
from src.services.agent_connections.managed_host import ManagedSetupError


def provision(api, host):
    target = member(api)
    request = api.post('/api/me/agent-access-requests', json={}).json()['data']
    admin(api)
    assert api.post(ROOT + '/' + request['id'] + '/decision', json={'revision': 1, 'decision': 'approved'}).status_code == 200
    assert host[0].wait(2)
    host[1].set()
    return target, wait_ready(api)


def finished(api, target):
    for _ in range(200):
        row = cleanup.public(api.app.state.api_context, target['id'])
        if row and row['phase'] in {'failed', 'complete'}:
            return row
        time.sleep(.01)
    pytest.fail('cleanup did not settle')


def test_revoke_stops_access_and_retry_keeps_same_identity(api, host, monkeypatch):
    target, request = provision(api, host)
    context = api.app.state.api_context
    service = AgentConnections(context.store, context.secret_values)
    manifest, token = service.export(target['id'])
    async def offline(*args):
        raise ManagedSetupError('offline secret must not escape')
    monkeypatch.setattr(cleanup.CleanupHost, 'remove', offline)
    url = ROOT + '/' + request['id'] + '/revoke'
    assert api.post(url, json={'revision': request['revision'] + 1, 'confirmed': True}).status_code == 409
    assert service.live(target)
    assert api.post(url, json={'revision': request['revision'], 'confirmed': True}).status_code == 200
    failed = finished(api, target)
    assert failed['phase'] == 'failed'
    assert 'secret' not in failed['error']
    assert not service.live(target)
    assert not context.store.authenticate_agent_delegation(token)
    assert cleanup_store.pending(context.store, target['id'])
    from src.services.agent_connections.access_requests import AccessRequests, AccessError
    with pytest.raises(AccessError):
        AccessRequests(context).submit(target)
    calls = []
    async def remove(self, snapshot, advance):
        calls.append(snapshot['binding_id'])
        advance('verifying')
    monkeypatch.setattr(cleanup.CleanupHost, 'remove', remove)
    assert api.post(ROOT + '/' + request['id'] + '/cleanup-retry', json={'revision': failed['revision'], 'confirmed': True}).status_code == 200
    assert finished(api, target)['phase'] == 'complete'
    assert calls == [manifest['binding_id']]
    assert AccessRequests(context).submit(target)['id'] != request['id']


def test_member_cannot_revoke_other_request(api, host):
    target, request = provision(api, host)
    from tests.test_agent_delegation_api import _login
    api.post('/api/auth/logout'); _login(api, 'applicant', 'test-password')
    assert api.post(ROOT + '/' + request['id'] + '/revoke', json={'revision': request['revision'], 'confirmed': True}).status_code == 403
    assert api.delete('/api/me/agent-connection').status_code == 200
    assert finished(api, target)['phase'] == 'complete'


def test_stop_checks_real_termination_and_never_other_agents():
    class Gateway:
        calls = []
        stopped = False
        enabled = True
        async def _request(self, socket, identity, method, params):
            self.calls.append((method, params))
            if method == 'cron.list':
                return {'jobs': [{'id': 'job', 'agentId': 'ih-target', 'enabled': self.enabled}], 'total': 1}
            if method == 'cron.update':
                self.enabled = False
                return {}
            if method == 'sessions.list':
                return {'sessions': [{'agentId': 'ih-target', 'key': 'agent:ih-target:chat', 'hasActiveRun': not self.stopped}], 'totalCount': 1}
            if method == 'chat.abort':
                self.stopped = True
                return {'aborted': True}
            raise AssertionError(method)
    gateway = Gateway()
    asyncio.run(stop_owned(gateway, None, 'ih-target'))
    assert gateway.stopped and not gateway.enabled
    assert sum(method == 'sessions.list' for method, _ in gateway.calls) == 2
    assert all(params.get('agentId', 'ih-target') == 'ih-target' for _, params in gateway.calls)


def test_unknown_owner_and_config_conflict_fail_closed():
    class Gateway:
        async def _request(self, socket, identity, method, params):
            assert method == 'cron.list'
            return {'jobs': [{'id': 'other', 'agentId': 'other', 'enabled': True}]}
    with pytest.raises(ManagedSetupError):
        asyncio.run(stop_owned(Gateway(), None, 'ih-target'))


def test_system_monitor_requires_supported_stop_not_file_bypass():
    from src.services.agent_connections.cleanup_host import CleanupBlocked
    class Gateway:
        async def _request(self, socket, identity, method, params):
            assert method == 'cron.list'
            return {'jobs': [{'id': 'monitor', 'agentId': 'ih-target', 'enabled': True,
                              'payload': {'kind': 'skillCollectionReview'}}]}
    with pytest.raises(ManagedSetupError):
        asyncio.run(stop_owned(Gateway(), None, 'ih-target'))


def test_revoke_during_configuration_never_activates(api, host):
    target = member(api)
    row = api.post('/api/me/agent-access-requests', json={}).json()['data']
    admin(api)
    api.post(ROOT + '/' + row['id'] + '/decision', json={'revision': 1, 'decision': 'approved'})
    assert host[0].wait(2)
    context = api.app.state.api_context
    from src.services.agent_connections.access_requests import AccessRequests
    request = AccessRequests(context).latest(target)
    assert request['binding_id']
    url = ROOT + '/' + row['id'] + '/revoke'
    assert api.post(url, json={'revision': request['revision'], 'confirmed': True}).status_code == 200
    host[1].set()
    for _ in range(200):
        if AccessRequests(context).latest(target)['phase'] == 'failed':
            break
        time.sleep(.01)
    assert not AgentConnections(context.store, context.secret_values).live(target)
    assert AgentConnections(context.store, context.secret_values).row(target['id'])['state'] == 'revoked'


def test_restart_projection_and_duplicate_revoke(api, host, monkeypatch):
    target, request = provision(api, host)
    context = api.app.state.api_context
    monkeypatch.setattr(cleanup, 'start', lambda *args: None)
    url = ROOT + '/' + request['id'] + '/revoke'
    payload = {'revision': request['revision'], 'confirmed': True}
    assert api.post(url, json=payload).status_code == 200
    assert api.post(url, json=payload).status_code == 200
    assert cleanup.public(context, target['id'])['phase'] == 'recovery'
    assert context.store.connect().execute('SELECT COUNT(*) FROM agent_cleanup').fetchone()[0] == 1
    assert not AgentConnections(context.store, context.secret_values).live(target)
