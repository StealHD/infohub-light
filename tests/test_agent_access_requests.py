"""Member approvals do not confer administrator identity or duplicate provisioning."""
import time
import pytest
from tests.test_agent_setup_api import api
from tests.test_agent_managed_setup import host
from tests.test_agent_delegation_api import _login
from src.services.agent_connections.service import AgentConnections

ROOT = '/api/admin/agent-access-requests'


def test_two_admins_only_one_decision_wins(api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.services.agent_connections.access_requests import AccessRequests, AccessError
    target = member(api)
    context = api.app.state.api_context
    first = context.store.get_user_by_username('owner')
    second = context.store.create_user(workspace_id=first['workspace_id'], username='second-admin',
                                       password='test-password', role='admin')
    request = AccessRequests(context).submit(target)
    barrier = Barrier(2)
    def decision(actor):
        try:
            barrier.wait(timeout=3)
            AccessRequests(context).decide(request['id'], actor, 1, 'rejected', '暂不开放')
            return True
        except AccessError:
            return False
        finally:
            context.store.close_current()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decision, [first, second])) == [False, True]
    assert AccessRequests(context).latest(target)['revision'] == 2


def test_existing_database_requires_explicit_migration(api):
    from src.storage.agent_access_schema import apply_migration, ready
    conn = api.app.state.service_store.connect()
    conn.execute('DROP TABLE agent_access_requests')
    conn.execute('DELETE FROM schema_migrations WHERE version=42')
    conn.commit()
    assert not ready(conn)
    apply_migration(conn)
    apply_migration(conn)
    assert ready(conn)
    assert conn.execute('SELECT count(*) FROM agent_access_requests').fetchone()[0] == 0


def member(client, role='member'):
    store = client.app.state.service_store
    owner = store.get_user_by_username('owner')
    user = store.create_user(workspace_id=owner['workspace_id'], username='applicant', password='test-password', role=role)
    client.post('/api/auth/logout')
    _login(client, 'applicant', 'test-password')
    return user


def admin(client):
    client.post('/api/auth/logout')
    _login(client)


def wait_ready(client):
    for _ in range(150):
        row = client.get(ROOT, params={'group': 'processed'}).json()['data']['items']
        if row and row[0]['state'] == 'ready':
            return row[0]
        time.sleep(.02)
    pytest.fail('approved setup did not become ready')


def test_member_request_approval_creates_member_not_admin_agent(api, host):
    target = member(api)
    first = api.post('/api/me/agent-access-requests', json={}).json()['data']
    assert api.post('/api/me/agent-access-requests', json={}).json()['data']['id'] == first['id']
    assert api.get(ROOT).status_code == 403
    assert api.get('/api/me/agent-connection').json()['data']['access_request']['state'] == 'pending'
    admin(api)
    response = api.post(ROOT + '/' + first['id'] + '/decision', json={'revision': 1, 'decision': 'approved'})
    assert response.status_code == 200
    assert host[0].wait(2)
    assert api.post(ROOT + '/' + first['id'] + '/decision', json={'revision': 1, 'decision': 'rejected', 'reason': 'late'}).status_code == 409
    host[1].set()
    wait_ready(api)
    context = api.app.state.api_context
    service = AgentConnections(context.store, context.secret_values)
    assert service.live(target)
    assert not service.row(context.store.get_user_by_username('owner')['id'])
    manifest, token = service.export(target['id'])
    assert manifest['user_id'] == target['id']
    assert context.store.authenticate_agent_delegation(token)['user_id'] == target['id']


def test_reject_requires_reason_and_reapply_is_explicit(api):
    member(api)
    row = api.post('/api/me/agent-access-requests', json={}).json()['data']
    admin(api)
    url = ROOT + '/' + row['id'] + '/decision'
    assert api.post(url, json={'revision': 1, 'decision': 'rejected'}).status_code == 400
    assert api.post(url, json={'revision': 1, 'decision': 'rejected', 'reason': '暂未开放'}).status_code == 200
    api.post('/api/auth/logout'); _login(api, 'applicant', 'test-password')
    assert api.get('/api/me/agent-connection').json()['data']['access_request']['reason'] == '暂未开放'
    assert api.post('/api/me/agent-access-requests', json={}).json()['data']['id'] != row['id']


def test_viewer_and_identity_injection_cannot_request(api):
    member(api, 'viewer')
    assert api.post('/api/me/agent-access-requests', json={}).status_code == 403
    admin(api)
    assert api.post('/api/me/agent-access-requests', json={}).status_code == 403
    assert api.post('/api/me/agent-access-requests', json={'user_id': 'other'}).status_code == 400


def test_disabled_member_rejected_and_request_survives_failed_setup(api, host):
    target = member(api)
    row = api.post('/api/me/agent-access-requests', json={}).json()['data']
    admin(api)
    api.app.state.service_store.update_user(target['id'], enabled=False)
    assert api.post(ROOT + '/' + row['id'] + '/decision', json={'revision': 1, 'decision': 'approved'}).status_code == 409
    assert api.get(ROOT).json()['data']['items'][0]['state'] == 'pending'


def test_permission_change_during_install_prevents_activation(api, host):
    target = member(api)
    row = api.post('/api/me/agent-access-requests', json={}).json()['data']
    admin(api)
    api.post(ROOT + '/' + row['id'] + '/decision', json={'revision': 1, 'decision': 'approved'})
    assert host[0].wait(2)
    store = api.app.state.service_store
    binding = AgentConnections(store, api.app.state.api_context.secret_values).row(target['id'])
    store.update_user(target['id'], enabled=False)
    host[1].set()
    for _ in range(100):
        current = api.get(ROOT, params={'group': 'processing'}).json()['data']['items'][0]
        if current['phase'] == 'failed':
            break
        time.sleep(.02)
    assert current['phase'] == 'failed'
    store.update_user(target['id'], enabled=True)
    service = AgentConnections(store, api.app.state.api_context.secret_values)
    assert not service.live(target)
    assert service.row(target['id'])['binding_id'] == binding['binding_id']


def test_workspace_guard_and_restart_projection(api):
    from src.services.agent_connections.access_requests import AccessRequests, AccessError
    from src.services.agent_connections.access_setup import project
    target = member(api)
    row = api.post('/api/me/agent-access-requests', json={}).json()['data']
    admin(api)
    context = api.app.state.api_context
    actor = context.store.get_user_by_username('owner')
    requests = AccessRequests(context)
    with pytest.raises(AccessError):
        requests.get(row['id'], {**actor, 'workspace_id': 'other-workspace'})
    approved = requests.decide(row['id'], actor, 1, 'approved', '')
    assert project(context, approved)['phase'] == 'recovery'
    assert not AgentConnections(context.store, context.secret_values).row(target['id'])


def test_failed_gateway_verification_retries_same_binding(api, host, monkeypatch):
    from src.services.agent_connections import managed_setup
    target = member(api)
    row = api.post('/api/me/agent-access-requests', json={}).json()['data']
    admin(api)
    async def fail(*args):
        raise RuntimeError('test failure')
    monkeypatch.setattr(managed_setup, 'check_mcp', fail)
    host[1].set()
    api.post(ROOT + '/' + row['id'] + '/decision', json={'revision': 1, 'decision': 'approved'})
    for _ in range(100):
        current = api.get(ROOT, params={'group': 'processing'}).json()['data']['items'][0]
        if current['phase'] == 'failed':
            break
        time.sleep(.02)
    assert current['phase'] == 'failed'
    service = AgentConnections(api.app.state.service_store, api.app.state.api_context.secret_values)
    original = service.row(target['id'])
    async def success(*args):
        return None
    monkeypatch.setattr(managed_setup, 'check_mcp', success)
    api.post(ROOT + '/' + row['id'] + '/retry', json={})
    wait_ready(api)
    assert service.row(target['id'])['binding_id'] == original['binding_id']
