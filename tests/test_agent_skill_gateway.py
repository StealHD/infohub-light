import json

import pytest

from src.services.agent_skill_gateway import ADMIN_SCOPES, AgentSkillGateway, AgentSkillGatewayError


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
async def test_sync_replaces_only_managed_agent_skills_and_verifies_readback(tmp_path, monkeypatch):
    gateway = AgentSkillGateway(object(), tmp_path)
    calls = []

    async def session(operation):
        return await operation("socket", {"features": {"methods": ["config.get", "config.patch"]}})

    async def request(_socket, request_id, method, params):
        calls.append((request_id, method, params))
        if request_id == "config-get":
            return {"hash": "base-hash", "config": {"agents": {"entries": {
                "ih-managed": {"skills": ["old"], "tools": {"allow": ["safe"]}},
                "other": {"skills": ["private"]},
            }}}}
        if request_id == "config-verify":
            return {"config": {"agents": {"entries": {
                "ih-managed": {"skills": ["reader"]}, "other": {"skills": ["private"]},
            }}}}
        return {}

    monkeypatch.setattr(gateway, "_session", session)
    monkeypatch.setattr(gateway, "_request", request)
    await gateway._sync(["ih-managed"], ["reader"])

    patch = calls[1]
    assert ADMIN_SCOPES == ["operator.admin"]
    assert patch[:2] == ("config-patch", "config.patch")
    assert patch[2]["baseHash"] == "base-hash"
    assert patch[2]["replacePaths"] == ["agents.entries.ih-managed.skills"]
    assert json.loads(patch[2]["raw"]) == {
        "agents": {"entries": {"ih-managed": {"skills": ["reader"]}}}
    }


@pytest.mark.anyio
async def test_sync_fails_closed_when_gateway_readback_differs(tmp_path, monkeypatch):
    gateway = AgentSkillGateway(object(), tmp_path)

    async def session(operation):
        return await operation("socket", {"features": {"methods": ["config.get", "config.patch"]}})

    async def request(_socket, request_id, _method, _params):
        if request_id == "config-get":
            return {"hash": "base-hash", "config": {"agents": {"entries": {"ih-managed": {}}}}}
        if request_id == "config-verify":
            return {"config": {"agents": {"entries": {"ih-managed": {"skills": []}}}}}
        return {}

    monkeypatch.setattr(gateway, "_session", session)
    monkeypatch.setattr(gateway, "_request", request)
    with pytest.raises(AgentSkillGatewayError, match="verification"):
        await gateway._sync(["ih-managed"], ["reader"])
