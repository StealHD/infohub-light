import json
from copy import deepcopy

import pytest

from src.services.agent_skill_gateway import ADMIN_SCOPES, AgentSkillGateway, AgentSkillGatewayError
from src.services.agent_connections.skill_tools import skill_tool_policy


def test_sync_wraps_transport_failures_without_exposing_credentials(tmp_path, monkeypatch):
    gateway = AgentSkillGateway(object(), tmp_path)

    async def fail(*_args):
        raise TimeoutError("TOKEN_SENTINEL")

    monkeypatch.setattr(gateway, "_sync", fail)
    with pytest.raises(AgentSkillGatewayError) as captured:
        gateway.sync(["ih-" + "a" * 32], ["reader"])
    assert "TOKEN_SENTINEL" not in str(captured.value)


def test_empty_binding_set_needs_no_gateway_credential(tmp_path):
    AgentSkillGateway(object(), tmp_path).sync([], [])


@pytest.mark.anyio
async def test_sync_replaces_managed_skills_and_capabilities_and_verifies_readback(tmp_path, monkeypatch):
    gateway = AgentSkillGateway(object(), tmp_path)
    calls = []

    async def session(operation):
        return await operation("socket", {"features": {"methods": ["config.get", "config.patch", "sessions.list", "tools.effective"]}})

    async def request(_socket, request_id, method, params):
        calls.append((request_id, method, params))
        if request_id == "config-get":
            return {"hash": "base-hash", "config": {"agents": {"entries": {
                "ih-managed": {"skills": ["old"], "tools": {"allow": ["safe"]}},
                "other": {"skills": ["private"]},
            }}}}
        if request_id == "config-verify":
            return {"config": {"agents": {"entries": {
                "ih-managed": {"skills": ["reader"], "tools": skill_tool_policy({'allow': ['safe']}, ['reader'])},
                "other": {"skills": ["private"]},
            }}}}
        if method == 'sessions.list':
            return {'sessions': [{'key': 'agent:ih-managed:existing'}]}
        if method == 'tools.effective':
            return {'agentId': 'ih-managed', 'groups': [{'tools': [{'id': 'read'}]}]}
        return {}

    monkeypatch.setattr(gateway, "_session", session)
    monkeypatch.setattr(gateway, "_request", request)
    await gateway._sync(["ih-managed"], ["reader"])

    patch = calls[1]
    assert ADMIN_SCOPES == ["operator.admin"]
    assert patch[:2] == ("config-patch", "config.patch")
    assert patch[2]["baseHash"] == "base-hash"
    assert patch[2]["replacePaths"] == [
        'agents.entries.ih-managed.skills', 'agents.entries.ih-managed.tools.allow',
        'agents.entries.ih-managed.tools.deny',
    ]
    assert json.loads(patch[2]["raw"]) == {
        "agents": {"entries": {"ih-managed": {
            "skills": ["reader"], "tools": skill_tool_policy({'allow': ['safe']}, ['reader']),
        }}}
    }
    assert calls[-1][1:] == ('tools.effective', {'agentId': 'ih-managed', 'sessionKey': 'agent:ih-managed:existing'})


@pytest.mark.anyio
async def test_sync_fails_closed_when_gateway_readback_differs(tmp_path, monkeypatch):
    gateway = AgentSkillGateway(object(), tmp_path)

    async def session(operation):
        return await operation("socket", {"features": {"methods": ["config.get", "config.patch", "sessions.list", "tools.effective"]}})

    async def request(_socket, request_id, _method, _params):
        if request_id == "config-get":
            return {"hash": "base-hash", "config": {"agents": {"entries": {"ih-managed": {'tools': {'allow': ['safe']}}}}}}
        if request_id == "config-verify":
            return {"config": {"agents": {"entries": {"ih-managed": {"skills": []}}}}}
        return {}

    monkeypatch.setattr(gateway, "_session", session)
    monkeypatch.setattr(gateway, "_request", request)
    with pytest.raises(AgentSkillGatewayError, match="verification"):
        await gateway._sync(["ih-managed"], ["reader"])


@pytest.mark.anyio
@pytest.mark.parametrize('failure', ['missing_read', 'missing_browser', 'wrong_agent', 'tool_drift', 'none'])
async def test_same_skill_selection_repairs_old_tools_and_checks_effective_capabilities(tmp_path, monkeypatch, failure):
    gateway = AgentSkillGateway(object(), tmp_path)
    original = {'skills': ['book-skill'], 'tools': {'allow': ['safe', 'browser'],
                'deny': ['read', 'group:fs', 'exec', 'write', 'other__*']}, 'model': 'keep'}
    entry = deepcopy(original)
    writes = []

    async def session(operation):
        return await operation('socket', {'features': {'methods': ['config.get', 'config.patch', 'sessions.list', 'tools.effective']}})

    async def request(_socket, request_id, method, params):
        if method == 'config.get':
            projected = deepcopy(entry)
            if failure == 'tool_drift' and request_id == 'config-verify':
                projected['tools']['fs']['workspaceOnly'] = False
            return {'hash': 'current', 'config': {'agents': {'entries': {'ih-managed': projected}}}}
        if method == 'config.patch':
            writes.append(params)
            patched = json.loads(params['raw'])['agents']['entries']['ih-managed']
            # Native Gateway rejects array removals unless the exact leaf is declared.
            for field in ('allow', 'deny'):
                if set(entry['tools'].get(field, [])) - set(patched['tools'][field]):
                    assert f'agents.entries.ih-managed.tools.{field}' in params['replacePaths']
            entry.update(patched)
            return {}
        if method == 'sessions.list':
            return {'sessions': [{'key': 'agent:ih-managed:existing'}]}
        assert method == 'tools.effective'
        assert params == {'agentId': 'ih-managed', 'sessionKey': 'agent:ih-managed:existing'}
        names = ['read', 'browser']
        if failure.startswith('missing_'):
            names.remove(failure.removeprefix('missing_'))
        return {'agentId': 'other' if failure == 'wrong_agent' else 'ih-managed',
                'groups': [{'tools': [{'id': name} for name in names]}]}

    monkeypatch.setattr(gateway, '_session', session)
    monkeypatch.setattr(gateway, '_request', request)
    if failure == 'none':
        await gateway._sync(['ih-managed'], ['book-skill'])
        await gateway._sync(['ih-managed'], ['book-skill'])
        assert entry['model'] == 'keep'
        assert 'other__*' in entry['tools']['deny']
        assert entry['tools']['fs'] == {'workspaceOnly': True}
    else:
        with pytest.raises((AgentSkillGatewayError, ValueError)):
            await gateway._sync(['ih-managed'], ['book-skill'])
    assert len(writes) == 1


@pytest.mark.anyio
async def test_missing_tool_verification_method_rejects_before_writing(tmp_path, monkeypatch):
    gateway = AgentSkillGateway(object(), tmp_path)

    async def session(operation):
        return await operation('socket', {'features': {'methods': ['config.get', 'config.patch']}})

    monkeypatch.setattr(gateway, '_session', session)
    with pytest.raises(AgentSkillGatewayError, match='support'):
        await gateway._sync(['ih-managed'], ['book-skill'])


@pytest.mark.anyio
@pytest.mark.parametrize('rows', [[], [{'key': 'agent:other:private'}]])
async def test_tool_verification_never_creates_sessions_or_reads_another_agent(tmp_path, monkeypatch, rows):
    gateway = AgentSkillGateway(object(), tmp_path)
    calls = []

    async def request(_socket, _id, method, params):
        calls.append((method, params))
        assert method == 'sessions.list'
        return {'sessions': rows}

    monkeypatch.setattr(gateway, '_request', request)
    if rows:
        with pytest.raises(AgentSkillGatewayError, match='identity'):
            await gateway._verify_tools('socket', 'ih-managed', ['book-skill'])
    else:
        await gateway._verify_tools('socket', 'ih-managed', ['book-skill'])
    assert calls == [('sessions.list', {'agentId': 'ih-managed', 'limit': 1, 'archived': 'all'})]


@pytest.mark.anyio
async def test_revoking_skills_declares_exact_allow_array_removal(tmp_path, monkeypatch):
    gateway = AgentSkillGateway(object(), tmp_path)
    entry = {'skills': ['book-skill'], 'tools': skill_tool_policy({'allow': ['safe']}, ['book-skill'])}

    async def session(operation):
        methods = ['config.get', 'config.patch', 'sessions.list', 'tools.effective']
        return await operation('socket', {'features': {'methods': methods}})

    async def request(_socket, _request_id, method, params):
        if method == 'config.get':
            return {'hash': 'current', 'config': {'agents': {'entries': {'ih-managed': deepcopy(entry)}}}}
        assert method == 'config.patch'
        patched = json.loads(params['raw'])['agents']['entries']['ih-managed']
        removed = set(entry['tools']['allow']) - set(patched['tools']['allow'])
        assert removed == {'read', 'browser'}
        assert 'agents.entries.ih-managed.tools.allow' in params['replacePaths']
        assert 'agents.entries.ih-managed.skills' in params['replacePaths']
        entry.update(patched)
        return {}

    monkeypatch.setattr(gateway, '_session', session)
    monkeypatch.setattr(gateway, '_request', request)
    await gateway._sync(['ih-managed'], [])
    assert entry['skills'] == []
    assert entry['tools']['allow'] == ['safe']
    assert {'read', 'browser', 'group:fs', 'group:ui'} <= set(entry['tools']['deny'])
