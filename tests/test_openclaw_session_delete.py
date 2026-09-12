import asyncio
import pytest
from src.services.openclaw_relay.policy import request_params, response_payload
from src.services.openclaw_relay.ownership import Ownership


def test_delete_requires_current_agent_ownership_and_full_cleanup(tmp_path):
    owner = Ownership(tmp_path, 'alice')
    for key in ['agent:own:old', 'agent:own:main', 'agent:retired:old']:
        owner.add(key)
    params = {'key': 'agent:own:old', 'deleteTranscript': True}
    assert request_params('sessions.delete', params, owner, 'own') == params
    for changed in [{'key':'agent:other:old'}, {'key':'agent:own:main'}, {'key':'agent:retired:old'}, {'deleteTranscript':False}, {'extra':True}]:
        with pytest.raises(PermissionError):
            request_params('sessions.delete', {**params, **changed}, owner, 'own')
    with pytest.raises(PermissionError):
        request_params('sessions.delete', params, owner, 'own', readonly=True)
    assert response_payload('sessions.delete', {'ok': True, 'deleted': True, 'archived': ['/private/file']}, owner, 'own', params) == {'ok': True, 'deleted': True}
    with pytest.raises(ValueError):
        response_payload('sessions.delete', {'ok': True, 'deleted': True, 'key':'wrong'}, owner, 'own', params)


@pytest.mark.parametrize('active,valid,expected', [(False, True, True), (True, True, False), (None, True, False), (False, False, False)])
def test_privileged_delete_rechecks_idle_and_authority(tmp_path, monkeypatch, active, valid, expected):
    from types import SimpleNamespace
    from src.services.openclaw_relay import session_delete
    calls = []
    class Gateway:
        def __init__(self, *_args): pass
        async def _session(self, operation):
            return await operation(None, {'features': {'methods': ['sessions.list', 'sessions.delete']}})
        async def _request(self, _socket, _request_id, method, params):
            calls.append((method, params))
            if method == 'sessions.list':
                return {'sessions': [{'key': 'agent:own:old', 'agentId': 'own', 'hasActiveRun': active, 'sessionId': 'immutable-id'}]}
            return {'ok': True, 'deleted': True}
    monkeypatch.setattr(session_delete, 'AgentSkillGateway', Gateway)
    owner = Ownership(tmp_path, 'alice'); owner.add('agent:own:old')
    context = SimpleNamespace(secret_values=None, store=SimpleNamespace(data_dir=tmp_path))
    operation = session_delete.delete_owned_session(context, owner, 'own', {'key': 'agent:own:old', 'deleteTranscript': True}, lambda: valid)
    if expected:
        assert asyncio.run(operation) == {'ok': True, 'deleted': True}
        assert calls[-1] == ('sessions.delete', {'key': 'agent:own:old', 'deleteTranscript': True, 'expectedSessionId': 'immutable-id'})
    else:
        with pytest.raises(PermissionError):
            asyncio.run(operation)
        assert [method for method, _ in calls] == ['sessions.list']


def test_worktree_session_is_preserved_before_gateway_delete(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.services.openclaw_relay import session_delete
    calls = []
    class Gateway:
        def __init__(self, *_): pass
        async def _session(self, operation):
            return await operation(None, {'features': {'methods': ['sessions.list', 'sessions.delete']}})
        async def _request(self, _socket, _identity, method, params):
            calls.append(method)
            return {'sessions': [{'key': 'agent:own:old', 'hasActiveRun': False, 'worktree': {'id': 'wt'}}]}
    monkeypatch.setattr(session_delete, 'AgentSkillGateway', Gateway)
    owner = Ownership(tmp_path, 'alice'); owner.add('agent:own:old')
    context = SimpleNamespace(secret_values=None, store=SimpleNamespace(data_dir=tmp_path))
    with pytest.raises(PermissionError, match='Worktree'):
        asyncio.run(session_delete.delete_owned_session(context, owner, 'own', {'key': 'agent:own:old', 'deleteTranscript': True}, lambda: True))
    assert calls == ['sessions.list']
