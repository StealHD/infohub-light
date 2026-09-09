"""Admin Skill policy API is role-bound, revisioned, and reports synchronization failures."""

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.services.agent_connections.service import AgentConnections
from tests.test_agent_connections import bind


class FakeGateway:
    fail = False
    syncs = []

    def __init__(self, *_args):
        pass

    def catalog(self, _agent_id):
        return [
            {"skillKey": "reader", "name": "Reader", "eligible": True, "disabled": False, "missing": {}},
            {"skillKey": "pdf", "name": "PDF", "eligible": False, "disabled": False,
             "missing": {"bins": ["pdftotext"]}},
        ]

    def sync(self, agent_ids, keys):
        if self.fail:
            from src.services.agent_skill_gateway import AgentSkillGatewayError
            raise AgentSkillGatewayError("test failure")
        self.syncs.append((agent_ids, keys))


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    static = tmp_path / "static"
    static.mkdir()
    static.joinpath("index.html").write_text("<!doctype html>")
    result = TestClient(create_app(data_dir=tmp_path / "data", static_dir=static))
    assert result.post("/api/auth/login", json={"username": "owner", "password": "secret-password"}).status_code == 200
    return result


def test_admin_lists_full_catalog_and_synchronizes_all_active_agents(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    store = api.app.state.service_store
    owner = store.get_user_by_username("owner")
    manifest, _, _ = bind(AgentConnections(store, api.app.state.api_context.secret_values), owner)
    monkeypatch.setattr("src.api.agent_skill_routes.AgentSkillGateway", FakeGateway)
    FakeGateway.fail = False
    FakeGateway.syncs = []
    listed = api.get("/api/admin/agent-skills")
    assert listed.status_code == 200
    assert [item["skillKey"] for item in listed.json()["data"]["skills"]] == ["reader", "pdf"]
    assert listed.json()["data"]["policy"]["sync_in_progress"] is False
    assert "sync_attempt_id" not in listed.text
    revision = listed.json()["data"]["policy"]["revision"]
    updated = api.put("/api/admin/agent-skills/policy", json={
        "expected_revision": revision, "allowed_skill_keys": ["reader"],
    })
    assert updated.status_code == 200
    assert updated.json()["data"]["policy"]["sync_state"] == "synced"
    assert FakeGateway.syncs == [([manifest["agent_id"]], ["reader"])]
    conflict = api.put("/api/admin/agent-skills/policy", json={
        "expected_revision": revision, "allowed_skill_keys": [],
    })
    assert conflict.status_code == 409


def test_member_cannot_read_or_change_management_catalog(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    store = api.app.state.service_store
    owner = store.get_user_by_username("owner")
    store.create_user(workspace_id=owner["workspace_id"], username="member", password="member-password", role="member")
    api.post("/api/auth/logout")
    api.post("/api/auth/login", json={"username": "member", "password": "member-password"})
    assert api.get("/api/admin/agent-skills").status_code == 403
    assert api.put("/api/admin/agent-skills/policy", json={
        "expected_revision": 1, "allowed_skill_keys": [],
    }).status_code == 403


def test_forged_unknown_skill_key_is_rejected_without_pre_authorizing_future_discovery(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    store = api.app.state.service_store
    owner = store.get_user_by_username("owner")
    bind(AgentConnections(store, api.app.state.api_context.secret_values), owner)
    monkeypatch.setattr("src.api.agent_skill_routes.AgentSkillGateway", FakeGateway)
    response = api.put("/api/admin/agent-skills/policy", json={
        "expected_revision": 1, "allowed_skill_keys": ["future-skill"],
    })
    assert response.status_code == 400
    policy = store.connect().execute(
        "SELECT revision,allowed_skill_keys_json,sync_state FROM workspace_agent_skill_policies"
    ).fetchone()
    assert tuple(policy) == (1, "[]", "synced")


def test_gateway_failure_persists_failed_state_and_retry_uses_same_revision(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    store = api.app.state.service_store
    owner = store.get_user_by_username("owner")
    bind(AgentConnections(store, api.app.state.api_context.secret_values), owner)
    monkeypatch.setattr("src.api.agent_skill_routes.AgentSkillGateway", FakeGateway)
    FakeGateway.fail = True
    response = api.put("/api/admin/agent-skills/policy", json={
        "expected_revision": 1, "allowed_skill_keys": ["reader"],
    })
    assert response.status_code == 503
    policy = store.connect().execute(
        "SELECT revision,sync_state,sync_error_code FROM workspace_agent_skill_policies"
    ).fetchone()
    assert tuple(policy) == (2, "failed", "gateway_sync_failed")
    assert AgentConnections(store, api.app.state.api_context.secret_values).status(owner)["can_chat"] is False
    FakeGateway.fail = False
    retried = api.put("/api/admin/agent-skills/policy", json={
        "expected_revision": 2, "allowed_skill_keys": ["reader"],
    })
    assert retried.status_code == 200
    assert retried.json()["data"]["policy"]["revision"] == 2
    assert AgentConnections(store, api.app.state.api_context.secret_values).status(owner)["can_chat"] is True
