"""Workspace Skill authorization defaults closed and stays aligned with each binding."""

import pytest

from src.services.agent_connections.gateway_config import configure
from src.services.agent_connections.service import AgentConnections
from src.services.agent_skill_access import AgentSkillAccess, AgentSkillPolicyError
from src.services.openclaw_relay.directory import skills_payload
from src.services.secret_store import SecretStore
from src.storage.service_store import ServiceStore


@pytest.fixture
def skill_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "test-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.get_user_by_username("owner")
    return store, owner, AgentSkillAccess(store)


def test_default_is_closed_and_policy_updates_use_revision_guard(skill_policy):
    _, owner, access = skill_policy
    policy = access.policy(owner["workspace_id"])
    assert policy["revision"] == 1
    assert policy["allowed_skill_keys"] == []
    assert policy["sync_state"] == "pending"
    changed = access.prepare(owner["workspace_id"], expected_revision=1, allowed_skill_keys=["reader"])
    assert changed["revision"] == 2 and changed["allowed_skill_keys"] == ["reader"]
    with pytest.raises(AgentSkillPolicyError, match="changed"):
        access.prepare(owner["workspace_id"], expected_revision=1, allowed_skill_keys=[])
    with pytest.raises(AgentSkillPolicyError, match="already running"):
        access.prepare(owner["workspace_id"], expected_revision=2, allowed_skill_keys=["reader"])


def test_failed_sync_can_retry_same_revision_and_blocks_chat(skill_policy):
    store, owner, access = skill_policy
    connections = AgentConnections(store, SecretStore(store.data_dir))
    manifest = connections.prepare(owner["id"], "http://127.0.0.1:8080/mcp")
    policy = access.prepare(owner["workspace_id"], expected_revision=1, allowed_skill_keys=[])
    failed = access.finish(
        owner["workspace_id"], revision=policy["revision"], attempt_id=policy["sync_attempt_id"],
        binding_ids=[manifest["binding_id"]],
        error_code="gateway_sync_failed",
    )
    assert failed["sync_state"] == "failed"
    assert not access.chat_ready(owner["workspace_id"], manifest["binding_id"])
    retried = access.prepare(
        owner["workspace_id"], expected_revision=policy["revision"], allowed_skill_keys=[]
    )
    assert retried["revision"] == policy["revision"] and retried["sync_state"] == "pending"


def test_revocation_blocks_the_next_chat_after_the_previous_revision_was_ready(skill_policy):
    store, owner, access = skill_policy
    manifest = AgentConnections(store, SecretStore(store.data_dir)).prepare(
        owner["id"], "http://127.0.0.1:8080/mcp"
    )
    policy = access.prepare(owner["workspace_id"], expected_revision=1, allowed_skill_keys=["reader"])
    access.finish(owner["workspace_id"], revision=policy["revision"],
                  attempt_id=policy["sync_attempt_id"], binding_ids=[manifest["binding_id"]])
    assert access.chat_ready(owner["workspace_id"], manifest["binding_id"])

    revoked = access.prepare(
        owner["workspace_id"], expected_revision=policy["revision"], allowed_skill_keys=[]
    )
    assert revoked["allowed_skill_keys"] == []
    assert not access.chat_ready(owner["workspace_id"], manifest["binding_id"])


def test_new_binding_manifest_and_gateway_config_use_current_allowlist(skill_policy, tmp_path):
    store, owner, access = skill_policy
    policy = access.prepare(owner["workspace_id"], expected_revision=1, allowed_skill_keys=["pdf", "reader"])
    policy = access.finish(owner["workspace_id"], revision=policy["revision"],
                           attempt_id=policy["sync_attempt_id"], binding_ids=[])
    manifest = AgentConnections(store, SecretStore(store.data_dir)).prepare(
        owner["id"], "http://127.0.0.1:8080/mcp"
    )
    assert manifest["version"] == 3 and manifest["skills"] == ["pdf", "reader"]
    config = configure({}, manifest, tmp_path)
    assert config["agents"]["entries"][manifest["agent_id"]]["skills"] == ["pdf", "reader"]


def test_public_projection_never_returns_closed_skills():
    payload = {"skills": [
        {"skillKey": "reader", "name": "Reader", "eligible": True, "disabled": False},
        {"skillKey": "secret", "name": "Secret", "eligible": True, "disabled": False},
    ]}
    result = skills_payload(payload, {"reader"})
    assert [item["skillKey"] for item in result["skills"]] == ["reader"]
    assert skills_payload(payload, set())["skills"] == []


@pytest.mark.parametrize("keys", [["reader", "reader"], ["bad key"], ["x" * 129], [{}]])
def test_invalid_policies_are_rejected(skill_policy, keys):
    _, owner, access = skill_policy
    with pytest.raises(AgentSkillPolicyError):
        access.prepare(owner["workspace_id"], expected_revision=1, allowed_skill_keys=keys)
