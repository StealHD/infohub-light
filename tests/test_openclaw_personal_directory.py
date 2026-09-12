"""Personal directory cannot adopt shared history or another principal's keys."""
import pytest
from src.services.openclaw_relay.ownership import Ownership
from src.services.openclaw_relay.policy import request_params, response_payload

AGENT = 'ih-' + 'a' * 32
OTHER = 'ih-' + 'b' * 32


def test_directory_routes_by_binding_and_paginates(tmp_path):
    owner = Ownership(tmp_path, 'alice')
    params = request_params('sessions.list', {'offset': 50, 'limit': 25, 'search': 'draft'}, owner, AGENT)
    assert params == {'agentId': AGENT, 'offset': 50, 'limit': 25, 'search': 'draft',
                      'archived': False, 'sortBy': 'updatedAt',
                      'includeDerivedTitles': True, 'includeLastMessage': True}
    key = f'agent:{AGENT}:imported'
    payload = {'sessions': [{'key': key, 'label': 'Draft', 'sessionFile': '/private/transcript'}],
               'totalCount': 100, 'hasMore': True, 'nextOffset': 75}
    result = response_payload('sessions.list', payload, owner, AGENT)
    assert result['sessions'] == [{'key': key, 'label': 'Draft'}]
    assert result['nextOffset'] == 75 and result['hasMore']
    assert owner.owns(key)
    assert response_payload('sessions.list', payload, owner, AGENT) == result


@pytest.mark.parametrize('params', [{'agentId': OTHER}, {'ownerId': 'bob'}, {'limit': True},
                                    {'limit': 101}, {'offset': -1}, {'archived': 1},
                                    {'search': 'x' * 513}, {'sortBy': 'lastInteractionAt'}])
def test_rejects_unbounded_or_cross_user_query(tmp_path, params):
    with pytest.raises(PermissionError):
        request_params('sessions.list', params, Ownership(tmp_path, 'alice'), AGENT)


@pytest.mark.parametrize('key', ['agent:main:shared', f'agent:{OTHER}:secret'])
def test_upstream_cannot_leak_or_adopt_other_agent(tmp_path, key):
    owner = Ownership(tmp_path, 'alice')
    with pytest.raises(ValueError):
        response_payload('sessions.list', {'sessions': [{'key': key}]}, owner, AGENT)
    assert not owner.owns(key)


def test_conflicting_ownership_is_never_reassigned(tmp_path):
    alice, bob = Ownership(tmp_path, 'alice'), Ownership(tmp_path, 'bob')
    key = f'agent:{AGENT}:session'
    bob.add(key)
    with pytest.raises(PermissionError):
        response_payload('sessions.list', {'sessions': [{'key': key}]}, alice, AGENT)
    assert bob.owns(key) and not alice.owns(key)


def test_skills_readonly_and_public_projection(tmp_path):
    owner = Ownership(tmp_path, 'alice')
    assert request_params('skills.status', {}, owner, AGENT, readonly=True) == {'agentId': AGENT}
    with pytest.raises(PermissionError):
        request_params('skills.status', {'sessionKey': 'agent:main:shared'}, owner, AGENT)
    result = response_payload('skills.status', {'skills': [{'skillKey': 'reader', 'name': 'Reader',
                              'eligible': True, 'disabled': False, 'filePath': '/private/skill',
                              'primaryEnv': 'SECRET', 'apiKey': 'never-expose'}],
                              'install': {'allowUploadedArchives': True}}, owner, AGENT)
    assert result == {'skills': [{'skillKey': 'reader', 'name': 'Reader', 'eligible': True,
                                  'disabled': False, 'missing': {}}], 'install': {'allowUploadedArchives': False}}
    with pytest.raises(PermissionError):
        request_params('skills.update', {'skillKey': 'reader'}, owner, AGENT)


def test_legacy_exact_search_keeps_owned_history_without_adopting_shared_rows(tmp_path):
    owner = Ownership(tmp_path, 'alice')
    owner.add('agent:main:old')
    params = request_params('sessions.list', {'search': 'agent:main:old'}, owner, AGENT)
    assert params == {'search': 'agent:main:old', 'limit': 1, 'archived': 'all'}
    result = response_payload('sessions.list', {'sessions': [{'key': 'agent:main:old'},
                              {'key': 'agent:main:other'}], 'totalCount': 9}, owner, AGENT, params)
    assert result == {'sessions': [{'key': 'agent:main:old'}], 'count': 1}
    assert not owner.owns('agent:main:other')


def test_status_does_not_claim_connectable_without_gateway_configuration(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from fastapi import Response
    from src.api import agent_connection_routes as routes
    from src.api import agent_access_routes
    monkeypatch.setattr(agent_access_routes, 'own_status', lambda *_: {'can_request': False, 'access_request': None})
    base = {'can_connect': True, 'can_chat': True, 'verification': {'own_content': True, 'deployment': True}}
    monkeypatch.setattr(routes, 'AgentConnections', lambda *_: SimpleNamespace(status=lambda _: base))
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'true')
    monkeypatch.delenv('HORIZON_OPENCLAW_SERVER_URL', raising=False)
    monkeypatch.delenv('HORIZON_OPENCLAW_SERVER_TOKEN', raising=False)
    monkeypatch.setattr(routes, 'reminders_ready', lambda _: True)
    context = SimpleNamespace(store=SimpleNamespace(connect=lambda: None, data_dir=tmp_path), secret_values=None,
                              notification_targets=SimpleNamespace(list_public_targets=lambda **_: {'targets': [{'available': True}]}),
                              openclaw_chat_settings=SimpleNamespace(enabled=True),
                              remote_mcp_settings=SimpleNamespace(enabled=True, subscription_writes_enabled=False, system_settings_writes_enabled=False))
    response = Response()
    import asyncio
    asyncio.run(routes.connection_status(response, {'id': 'alice', 'workspace_id': 'workspace', 'role': 'member'}, context))
    assert not base['can_connect'] and not base['can_chat']
    assert base['verification']['information_automations'] and base['verification']['notifications']
    assert response.headers['Cache-Control'] == 'no-store'


def test_skill_requirement_names_survive_without_values_or_paths(tmp_path):
    payload = {'skills': [{'skillKey': 'reader', 'eligible': False, 'disabled': False,
                          'missing': {'bins': ['reader', '/private/path'],
                                      'env': ['READER_TOKEN', 'READER_TOKEN=value'],
                                      'config': ['tools.reader'], 'os': ['linux']}}]}
    result = response_payload('skills.status', payload, Ownership(tmp_path, 'alice'), AGENT)
    assert result['skills'][0]['missing'] == {'bins': ['reader'], 'env': ['READER_TOKEN'],
                                            'config': ['tools.reader'], 'os': ['linux']}
