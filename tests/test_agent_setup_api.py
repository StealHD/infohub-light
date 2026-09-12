"""Trusted web setup keeps personal identities and credentials account-scoped."""
import base64
import io
import json
import tarfile

import pytest

from tests.test_agent_delegation_api import _client, _login
from src.services.agent_connections.manifest import receipt

ROOT = '/api/me/agent-connection/setup'


@pytest.fixture
def api(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, enabled=True) as client:
        _login(client)
        yield client


def download(api):
    response = api.post(ROOT + '/bundle', json={'confirmed': True})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(response.json()['data']['archive_base64']))) as archive:
        assert [entry.name for entry in archive] == ['personal-agent', 'personal-agent/manifest.json', 'personal-agent/token']
        assert archive.getmember('personal-agent').mode == 0o700
        assert archive.getmember('personal-agent/token').mode == 0o600
        assert archive.getmember('personal-agent/manifest.json').mode == 0o600
        return json.load(archive.extractfile('personal-agent/manifest.json')), archive.extractfile('personal-agent/token').read().decode().strip()


def test_prepare_download_activate_preserves_existing_connection(api):
    store = api.app.state.service_store
    user = store.get_user_by_username('owner')
    old, _ = store.create_agent_delegation(workspace_id=user['workspace_id'], user_id=user['id'], name='fsj')
    assert api.get('/api/me/agent-connection').json()['data']['can_manage_setup'] is True
    first = api.post(ROOT, json={'confirmed': True})
    assert first.status_code == 200
    assert first.json()['data']['state'] == 'pending_verification'
    assert api.post(ROOT, json={'confirmed': True}).json() == first.json()
    manifest, token = download(api)
    assert manifest['user_id'] == user['id']
    assert manifest['mcp_url'] == 'http://127.0.0.1:8080/mcp'
    assert manifest['delegation_id'] != old['id']
    assert store.get_active_agent_delegation_principal(old['id'])
    assert 'inteliscope:system-settings:write' in store.authenticate_agent_delegation(token)['scopes']
    assert api.get('/api/me/agent-connection').json()['data']['state'] == 'pending_verification'
    proof = receipt(manifest, token, 'a' * 64)
    response = api.post(ROOT + '/activate', json={'confirmed': True, 'receipt_json': json.dumps(proof)})
    assert response.status_code == 200
    assert response.json()['data']['state'] == 'ready'
    assert token not in response.text + api.get('/api/me/agent-connection').text
    assert api.post(ROOT + '/bundle', json={'confirmed': True}).status_code == 409


@pytest.mark.parametrize('role', ['member', 'viewer'])
def test_non_operator_cannot_prepare_export_or_activate(api, role):
    store = api.app.state.service_store
    user = store.get_user_by_username('owner')
    store.create_user(workspace_id=user['workspace_id'], username='other', password='other-password', role=role)
    api.post('/api/auth/logout')
    _login(api, 'other', 'other-password')
    assert api.get('/api/me/agent-connection').json()['data']['can_manage_setup'] is False
    for suffix in ['', '/bundle', '/activate']:
        payload = {'confirmed': True, **({'receipt_json': '{}'} if suffix == '/activate' else {})}
        assert api.post(ROOT + suffix, json=payload).status_code == 403


def test_confirmation_and_payload_reject_identity_overrides(api):
    assert api.post(ROOT, json={'confirmed': False}).status_code == 400
    assert api.post(ROOT, json={'confirmed': 'true'}).status_code == 400
    for field in ['user_id', 'agent_id', 'mcp_url']:
        assert api.post(ROOT, json={'confirmed': True, field: 'other'}).status_code == 400
    assert api.get('/api/me/agent-connection').json()['data']['state'] == 'unconfigured'


@pytest.mark.parametrize('proof', ['{}', '[]', 'null', 'invalid', '{"signature": "forged"}'])
def test_invalid_receipt_never_activates(api, proof):
    api.post(ROOT, json={'confirmed': True})
    response = api.post(ROOT + '/activate', json={'confirmed': True, 'receipt_json': proof})
    assert response.status_code == 400
    assert api.get('/api/me/agent-connection').json()['data']['state'] == 'pending_verification'
