from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.services.apify_key_pool import (
    ApifyKeyPoolConflictError,
    ApifyKeyPoolService,
)
from src.storage.service_store import ServiceStore


def _minimal_config() -> dict:
    return {
        "version": "1.0",
        "ai": {
            "enabled": False,
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "api_key_env": "GOOGLE_API_KEY",
        },
        "tags": ["AI"],
        "personal_tags": [],
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }


def _client(tmp_path, monkeypatch) -> tuple[TestClient, ServiceStore]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(_minimal_config()),
        encoding="utf-8",
    )
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    store = ServiceStore(data_dir)
    store.initialize()
    return client, store


def _login(
    client: TestClient,
    username: str = "owner",
    password: str = "secret-password",
) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def _create_apify_secret(
    client: TestClient,
    *,
    name: str,
    env_name: str,
    value: str,
) -> dict:
    response = client.post(
        "/api/admin/secrets",
        json={
            "name": name,
            "kind": "apify",
            "provider": "apify",
            "env_name": env_name,
            "value": value,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_admin_pool_order_lifecycle_and_safe_projection(tmp_path, monkeypatch):
    client, _store = _client(tmp_path, monkeypatch)
    _login(client)
    primary = _create_apify_secret(
        client,
        name="Primary",
        env_name="APIFY_POOL_PRIMARY",
        value="private-primary-token",
    )
    backup_one = _create_apify_secret(
        client,
        name="Backup One",
        env_name="APIFY_POOL_BACKUP_ONE",
        value="private-backup-one-token",
    )
    backup_two = _create_apify_secret(
        client,
        name="Backup Two",
        env_name="APIFY_POOL_BACKUP_TWO",
        value="private-backup-two-token",
    )

    response = client.get("/api/admin/apify-key-pool")
    assert response.status_code == 200
    pool = response.json()["data"]
    assert pool["enabled"] is True
    assert pool["status"] == "ready"
    assert pool["active_secret_id"] == primary["id"]
    assert [item["secret_id"] for item in pool["members"]] == [
        primary["id"],
        backup_one["id"],
        backup_two["id"],
    ]
    for member in pool["members"]:
        assert set(member) == {
            "secret_id",
            "position",
            "status",
            "blocked_until",
            "cycle_end_at",
            "last_checked_at",
            "last_error_code",
            "active_run_count",
        }
    serialized = response.text
    for forbidden in (
        "private-primary-token",
        "private-backup-one-token",
        "private-backup-two-token",
        "APIFY_POOL_PRIMARY",
        "remote_run_id",
        "dataset_id",
    ):
        assert forbidden not in serialized

    invalid_order = client.put(
        "/api/admin/apify-key-pool/order",
        json={
            "secret_ids": [primary["id"], backup_one["id"], backup_one["id"]],
            "expected_generation": pool["generation"],
        },
    )
    assert invalid_order.status_code == 400
    assert invalid_order.json()["error"]["code"] == "invalid_request"

    reordered = client.put(
        "/api/admin/apify-key-pool/order",
        json={
            "secret_ids": [
                primary["id"],
                backup_two["id"],
                backup_one["id"],
            ],
            "expected_generation": pool["generation"],
        },
    )
    assert reordered.status_code == 200, reordered.text
    reordered_pool = reordered.json()["data"]
    assert reordered_pool["generation"] == pool["generation"] + 1
    assert [item["secret_id"] for item in reordered_pool["members"]] == [
        primary["id"],
        backup_two["id"],
        backup_one["id"],
    ]

    conflict = client.put(
        "/api/admin/apify-key-pool/order",
        json={
            "secret_ids": [
                primary["id"],
                backup_one["id"],
                backup_two["id"],
            ],
            "expected_generation": pool["generation"],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "apify_key_pool_conflict"

    for method, path, body in (
        ("PUT", f"/api/admin/secrets/{primary['id']}/value", {"value": "new"}),
        ("DELETE", f"/api/admin/secrets/{primary['id']}", None),
    ):
        busy = client.request(method, path, json=body)
        assert busy.status_code == 409
        assert busy.json()["error"]["code"] == "apify_key_busy"
        assert "private-primary-token" not in busy.text

    drained = client.post(
        f"/api/admin/apify-key-pool/{primary['id']}/drain"
    )
    assert drained.status_code == 200, drained.text
    drained_pool = drained.json()["data"]
    assert drained_pool["generation"] == reordered_pool["generation"] + 1
    assert drained_pool["active_secret_id"] == backup_two["id"]
    assert drained_pool["members"][-1]["secret_id"] == primary["id"]
    assert drained_pool["members"][-1]["status"] == "standby"

    rotated = client.put(
        f"/api/admin/secrets/{primary['id']}/value",
        json={"value": "rotated-after-drain"},
    )
    assert rotated.status_code == 200
    assert "rotated-after-drain" not in rotated.text


def test_apify_secret_create_rolls_back_ref_and_value_when_pool_append_fails(
    tmp_path,
    monkeypatch,
):
    def reject_append(_service, _secret_id):
        raise ApifyKeyPoolConflictError()

    monkeypatch.setattr(ApifyKeyPoolService, "append_secret", reject_append)
    client, store = _client(tmp_path, monkeypatch)
    _login(client)

    response = client.post(
        "/api/admin/secrets",
        json={
            "name": "Rejected",
            "kind": "apify",
            "provider": "apify",
            "env_name": "APIFY_POOL_REJECTED",
            "value": "private-rejected-token",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "apify_key_pool_conflict"
    workspace = store.get_default_workspace()
    assert store.get_secret_ref_by_env(
        workspace_id=workspace["id"],
        env_name="APIFY_POOL_REJECTED",
    ) is None
    secrets_file = tmp_path / "data" / "secrets.env"
    assert "private-rejected-token" not in (
        secrets_file.read_text(encoding="utf-8") if secrets_file.exists() else ""
    )


def test_single_active_key_can_be_rotated_after_safe_drain(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    secret = _create_apify_secret(
        client,
        name="Only Key",
        env_name="APIFY_POOL_ONLY",
        value="private-original-token",
    )
    workspace = store.get_default_workspace()
    pool_service = ApifyKeyPoolService(store)
    pool_service.record_member_quota(
        workspace_id=workspace["id"],
        secret_id=secret["id"],
        remaining_included_credits_usd=4,
        checked_at="2026-07-23T00:00:00+00:00",
        cycle_end_at="2026-08-01T00:00:00+00:00",
    )

    drained = client.post(f"/api/admin/apify-key-pool/{secret['id']}/drain")
    assert drained.status_code == 200
    drained_pool = drained.json()["data"]
    assert drained_pool["status"] == "exhausted"
    assert drained_pool["active_secret_id"] is None

    rotated = client.put(
        f"/api/admin/secrets/{secret['id']}/value",
        json={"value": "private-rotated-token"},
    )
    assert rotated.status_code == 200
    assert "private-rotated-token" not in rotated.text
    pool = client.get("/api/admin/apify-key-pool").json()["data"]
    member = next(item for item in pool["members"] if item["secret_id"] == secret["id"])
    assert pool["status"] == "ready"
    assert pool["active_secret_id"] == secret["id"]
    assert pool["generation"] == drained_pool["generation"] + 1
    assert member["status"] == "active"
    assert member["last_checked_at"] is None
    assert member["cycle_end_at"] is None


def test_pool_managed_sources_reject_secret_env_and_hide_legacy_reference(
    tmp_path,
    monkeypatch,
):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    secret = _create_apify_secret(
        client,
        name="Workspace Apify",
        env_name="APIFY_POOL_SOURCE_TEST",
        value="private-source-token",
    )
    payload = {
        "scope": "private",
        "type": "apify_social",
        "display_name": "OpenAI X",
        "config": {
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
    }

    rejected = client.post(
        "/api/catalog/sources",
        json={**payload, "secret_env": secret["env_name"]},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "apify_key_pool_managed"
    rejected_null = client.post(
        "/api/catalog/sources",
        json={**payload, "secret_env": None},
    )
    assert rejected_null.status_code == 409
    assert rejected_null.json()["error"]["code"] == "apify_key_pool_managed"

    created = client.post("/api/catalog/sources", json=payload)
    assert created.status_code == 200, created.text
    source = created.json()["data"]
    assert "secret_env" not in source
    assert source["secret_configured"] is True

    store.connect().execute(
        "UPDATE source_catalog SET secret_env = ? WHERE id = ?",
        (secret["env_name"], source["id"]),
    )
    store.connect().commit()
    listed = client.get("/api/catalog/sources").json()["data"]["sources"]
    projected = next(item for item in listed if item["id"] == source["id"])
    assert "secret_env" not in projected
    assert projected["secret_configured"] is True

    patch = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"secret_env": None},
    )
    assert patch.status_code == 409
    assert patch.json()["error"]["code"] == "apify_key_pool_managed"

    registry = client.get("/api/catalog/source-types").json()["data"][
        "source_types"
    ]
    apify = next(item for item in registry if item["type"] == "apify_social")
    assert apify["credential_mode"] == "workspace_apify_pool"
    assert apify["supports_secret_env"] is False


def test_pool_routes_require_admin_and_are_workspace_isolated(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    local = _create_apify_secret(
        client,
        name="Local",
        env_name="APIFY_POOL_LOCAL",
        value="private-local-token",
    )
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert owner is not None
    now = "2026-07-23T00:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO workspaces (id, name, created_at, updated_at)
        VALUES ('workspace-other', 'Other', ?, ?)
        """,
        (now, now),
    )
    store.connect().commit()
    store.initialize()
    other = store.create_secret_ref(
        workspace_id="workspace-other",
        owner_user_id=None,
        name="Other",
        env_name="APIFY_POOL_OTHER",
        kind="apify",
        provider="apify",
    )
    ApifyKeyPoolService(store).append_secret(other["id"])

    pool = client.get("/api/admin/apify-key-pool").json()["data"]
    assert [item["secret_id"] for item in pool["members"]] == [local["id"]]
    cross_workspace = client.post(
        f"/api/admin/apify-key-pool/{other['id']}/drain"
    )
    assert cross_workspace.status_code == 404

    created_member = client.post(
        "/api/users",
        json={
            "username": "member",
            "password": "member-password",
            "role": "member",
        },
    )
    assert created_member.status_code == 200
    client.post("/api/auth/logout")
    _login(client, "member", "member-password")
    for method, path, body in (
        ("GET", "/api/admin/apify-key-pool", None),
        (
            "PUT",
            "/api/admin/apify-key-pool/order",
            {"secret_ids": [local["id"]], "expected_generation": pool["generation"]},
        ),
        (
            "POST",
            f"/api/admin/apify-key-pool/{local['id']}/drain",
            None,
        ),
    ):
        denied = client.request(method, path, json=body)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "forbidden"
