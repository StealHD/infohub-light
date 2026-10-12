"""Pending Bilibili sources remain identifiable and fail before job creation."""

import pytest

from src.services.actorops.binding_service import ActorOpsBindingService
from src.storage.bilibili_actor_cutover import apply_cutover
from tests.api_service_test_support import client as build_client, login, login_as
from tests.test_bilibili_actor_cutover import _source


def _context(tmp_path, monkeypatch):
    client, _ = build_client(tmp_path, monkeypatch)
    login(client)
    store = client.app.state.service_store
    owner = store.get_user_by_username("owner")
    source_id = _source(store, "39627524")
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    with store.connect():
        store.connect().execute("BEGIN IMMEDIATE")
        apply_cutover(store)
    return client, store, source_id, subscription["id"]


def test_cutover_source_has_bilibili_label_and_pending_state(tmp_path, monkeypatch):
    client, _, source_id, _ = _context(tmp_path, monkeypatch)
    sources = client.get("/api/catalog/sources?include_disabled=true").json()["data"]["sources"]
    source = next(row for row in sources if row["id"] == source_id)
    assert source["type"] == "rss"
    assert source["setup_type"] == "bilibili"
    assert source["acquisition"] == {
        "provider": "apify", "status": "pending", "allowed": False,
        "reason": "actorops_v2_binding_pending",
    }


@pytest.mark.parametrize("endpoint", ["source-fetch", "source-test"])
def test_pending_source_returns_actionable_conflict_without_work(tmp_path, monkeypatch, endpoint):
    client, store, source_id, subscription_id = _context(tmp_path, monkeypatch)
    before = store.connect().execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
    response = client.post(f"/api/jobs/{endpoint}", json={
        "source_id": source_id, "subscription_id": subscription_id,
    })
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "actorops_v2_binding_pending"
    assert "验证" in error["message"] and "ActorOps" in error["action"]
    assert store.connect().execute("SELECT COUNT(*) FROM fetch_jobs").fetchone()[0] == 0
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
    assert store.connect().execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == before


def test_disabled_binding_is_distinct_from_pending(tmp_path, monkeypatch):
    client, store, source_id, subscription_id = _context(tmp_path, monkeypatch)
    ActorOpsBindingService(store, workspace_id=store.get_default_workspace()["id"]).disable(source_id)
    response = client.post("/api/jobs/source-fetch", json={"source_id": source_id, "subscription_id": subscription_id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "actorops_v2_binding_disabled"


def test_pending_private_source_is_not_disclosed_to_another_user(tmp_path, monkeypatch):
    client, store, source_id, subscription_id = _context(tmp_path, monkeypatch)
    owner = store.get_user_by_username("owner")
    store.update_source(source_id, scope="private", owner_user_id=owner["id"])
    store.create_user(workspace_id=owner["workspace_id"], username="other", password="other-password", role="member")
    login_as(client, "other", "other-password")
    response = client.post("/api/jobs/source-fetch", json={"source_id": source_id, "subscription_id": subscription_id})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_member_can_identify_their_own_pending_subscription(tmp_path, monkeypatch):
    client, store, source_id, _ = _context(tmp_path, monkeypatch)
    owner = store.get_user_by_username("owner")
    member = store.create_user(workspace_id=owner["workspace_id"], username="member", password="member-password", role="member")
    store.create_subscription(user_id=member["id"], source_id=source_id)
    login_as(client, "member", "member-password")
    sources = client.get("/api/catalog/sources").json()["data"]["sources"]
    source = next(row for row in sources if row["id"] == source_id)
    assert source["setup_type"] == "bilibili" and source["acquisition"]["status"] == "pending"
    response = client.post("/api/jobs/source-fetch", json={"source_id": source_id})
    assert response.status_code == 409
    assert "联系管理员" in response.json()["error"]["action"]


def test_unbound_source_is_blocked_before_queueing(tmp_path, monkeypatch):
    client, store, source_id, _ = _context(tmp_path, monkeypatch)
    store.connect().execute("DELETE FROM actor_source_bindings_v2 WHERE source_id=?", (source_id,))
    store.connect().commit()
    response = client.post("/api/jobs/source-test", json={"source_id": source_id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "actorops_v2_binding_missing"


def test_ordinary_disabled_rss_keeps_not_found_behavior(tmp_path, monkeypatch):
    client, store, _, _ = _context(tmp_path, monkeypatch)
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(workspace_id=owner["workspace_id"], scope="workspace", owner_user_id=None,
                                    source_type="rss", display_name="Disabled RSS", enabled=False,
                                    config={"url": "https://example.com/rss"})
    response = client.post("/api/jobs/source-fetch", json={"source_id": source_id})
    assert response.status_code == 404
