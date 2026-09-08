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
    assert http.post(path, headers=headers, json={'isolated_completion': True, 'user_id': 'other'}).status_code == 422
    assert http.post(path, headers=headers, content=b'x' * 65537).status_code == 413
    response = http.post(path, headers=headers, json={'isolated_completion': True})
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    task = response.json()['data']['task']
    # Future-ready production batches are not claimed before their creation timestamp.
    if task:
        assert 'target_id' not in task and 'user_id' not in task
        result = http.post('/api/connector/information-automations/claims/' + task['claim_id'] + '/result',
                           headers=headers, json={'claim_token': task['claim_token'], 'result': answer(task)})
        assert result.status_code == 200
