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


def test_capability_sync_distinguishes_changes_from_heartbeat(context, client):
    http, _ = client
    headers = {'Authorization': 'Bearer ' + context[0].test_machine_token}
    path = '/api/connector/information-automations/capabilities'
    body = {'protocol_version': 2, 'models': [{'id': 'test/model', 'name': 'Test', 'thinking_levels': ['low']}]}
    assert http.post(path, headers=headers, json=body).json()['data']['changed'] is False
    body['models'] = []
    assert http.post(path, headers=headers, json=body).json()['data']['changed'] is True
    assert http.post(path, headers=headers, json=body).json()['data']['changed'] is False
