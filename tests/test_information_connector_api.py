"""A browser session alone never authorizes machine task access."""
from test_information_automation_rules import context  # noqa: F401
from test_information_automation_api import client  # noqa: F401
from test_information_semantic_claims import setup, answer


def test_machine_credentials_required_and_bounded_body(context, client):
    _, _, token, _, _, _ = setup(context)
    http, _ = client
    path = '/api/connector/information-automations/claim'
    assert http.post(path, json={'isolated_completion': True}).status_code == 401
    assert http.post(path, headers={'Authorization': 'Bearer fake'}, json={'isolated_completion': True}).status_code == 401
    headers = {'Authorization': 'Bearer ' + token}
    assert http.post(path, headers=headers, json={'isolated_completion': False}).status_code == 400
    assert http.post(path, headers=headers, json={'isolated_completion': True}).status_code == 409
    assert http.post(path, headers=headers, json={'isolated_completion': True, 'user_id': 'other'}).status_code == 422
    assert http.post(path, headers=headers, content=b'x' * 65537).status_code == 413
    response = http.post(path, headers=headers, json={'isolated_completion': True, 'protocol_version': 2})
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    task = response.json()['data']['task']
    # Future-ready production batches are not claimed before their creation timestamp.
    if task:
        assert 'target_id' not in task and 'user_id' not in task
        result = http.post('/api/connector/information-automations/claims/' + task['claim_id'] + '/result',
                           headers=headers, json={'claim_token': task['claim_token'], 'result': answer(task)})
        assert result.status_code == 200


def test_model_catalog_is_personal_and_cannot_be_written_by_browser(context, client):
    from src.api.system_auth import current_user
    http, app = client
    path = '/api/me/information-automations/models'
    first = http.get(path)
    assert first.status_code == 200 and first.headers['Cache-Control'] == 'no-store'
    assert [model['id'] for model in first.json()['data']['models']] == ['test/model']
    assert http.post('/api/connector/information-automations/capabilities',
                     json={'protocol_version': 2, 'models': []}).status_code == 401
    app.dependency_overrides[current_user] = lambda: context[4]
    assert http.get(path).json()['data']['models'] == []
    app.dependency_overrides[current_user] = lambda: context[5]
    assert http.post(path + '/refresh').status_code == 403



def test_model_refresh_returns_direct_gateway_catalog_without_executor(context, client, monkeypatch):
    http, app = client
    from types import SimpleNamespace
    from src.api.system_auth import api_context
    from src.services.secret_store import SecretStore
    from src.services.information_automations import direct_model_catalog
    secrets = SecretStore(context[0].data_dir)
    secrets.set('HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN', 'gateway-admin-token')
    app.dependency_overrides[api_context] = lambda: SimpleNamespace(
        store=context[0], notification_targets=context[1].targets, secret_values=secrets,
        openclaw_chat_settings=SimpleNamespace(enabled=True, default_gateway_url='ws://127.0.0.1:13789'),
        data_path=context[0].data_dir,
    )
    observed = {}
    async def gateway(url, token, agent_id, device_dir):
        observed.update(url=url, token=token, agent_id=agent_id, device_dir=device_dir)
        return {'models': [{'id': 'gpt-5.6-terra', 'provider': 'openai', 'name': 'GPT-5.6 Terra'}]}
    monkeypatch.setattr(direct_model_catalog, 'rpc_models', gateway)

    response = http.post('/api/me/information-automations/models/refresh')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.json()['data']['models'][0]['id'] == 'openai/gpt-5.6-terra'
    assert observed['agent_id'].startswith('ih-')
    assert observed['token'] == 'gateway-admin-token'

def test_capability_sync_distinguishes_changes_from_heartbeat(context, client):
    http, _ = client
    headers = {'Authorization': 'Bearer ' + context[0].test_machine_token}
    path = '/api/connector/information-automations/capabilities'
    body = {'protocol_version': 2, 'models': [{'id': 'test/model', 'name': 'Test', 'thinking_levels': ['low']}]}
    assert http.post(path, headers=headers, json=body).json()['data']['changed'] is False
    body['models'] = []
    assert http.post(path, headers=headers, json=body).json()['data']['changed'] is True
    assert http.post(path, headers=headers, json=body).json()['data']['changed'] is False
