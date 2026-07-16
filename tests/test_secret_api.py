from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.storage.service_store import ServiceStore


def _minimal_config() -> dict:
    return {
        "version": "1.0",
        "ai": {
            "enabled": True,
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "api_key_env": "GOOGLE_API_KEY",
        },
        "tags": ["AI Agent"],
        "personal_tags": [],
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }


def _client(tmp_path, monkeypatch) -> tuple[TestClient, ServiceStore]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps(_minimal_config()), encoding="utf-8")
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    store = ServiceStore(data_dir)
    store.initialize()
    return client, store


def _login(client: TestClient, username: str = "owner", password: str = "secret-password") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def _create_secret(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Apify Primary",
        "kind": "apify",
        "provider": "apify",
        "env_name": "APIFY_TOKEN",
        "value": "private-apify-value",
    }
    payload.update(overrides)
    response = client.post("/api/admin/secrets", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_admin_secret_crud_is_write_only_and_duplicate_env_is_rejected(tmp_path, monkeypatch) -> None:
    client, _store = _client(tmp_path, monkeypatch)
    _login(client)

    created = _create_secret(client)
    assert created["is_set"] is True
    assert set(created) == {
        "id", "name", "kind", "provider", "env_name", "is_set", "used_by", "created_at", "updated_at"
    }
    assert "private-apify-value" not in json.dumps(created)

    listed = client.get("/api/admin/secrets")
    assert listed.status_code == 200
    assert listed.json()["data"]["secrets"] == [created]
    assert "private-apify-value" not in listed.text

    duplicate = client.post(
        "/api/admin/secrets",
        json={
            "name": "Duplicate",
            "kind": "apify",
            "provider": "apify",
            "env_name": "APIFY_TOKEN",
            "value": "another-private-value",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "secret_env_conflict"
    assert "another-private-value" not in duplicate.text

    rotated = client.put(
        f"/api/admin/secrets/{created['id']}/value",
        json={"value": "rotated-private-value"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["data"]["is_set"] is True
    assert "rotated-private-value" not in rotated.text

    deleted = client.delete(f"/api/admin/secrets/{created['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/admin/secrets").json()["data"]["secrets"] == []


def test_deepseek_secret_is_allowed_and_never_echoes_value(tmp_path, monkeypatch) -> None:
    client, _store = _client(tmp_path, monkeypatch)
    _login(client)

    response = client.post(
        "/api/admin/secrets",
        json={
            "name": "DeepSeek",
            "kind": "ai",
            "provider": "deepseek",
            "env_name": "DEEPSEEK_API_KEY",
            "value": "deepseek-private-test-value",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["provider"] == "deepseek"
    assert response.json()["data"]["env_name"] == "DEEPSEEK_API_KEY"
    assert "deepseek-private-test-value" not in response.text
    listed = client.get("/api/admin/secrets")
    assert listed.status_code == 200
    assert "deepseek-private-test-value" not in listed.text


def test_secret_admin_routes_reject_member_and_viewer(tmp_path, monkeypatch) -> None:
    client, _store = _client(tmp_path, monkeypatch)
    _login(client)
    for username, role in (("member", "member"), ("viewer", "viewer")):
        created = client.post(
            "/api/users",
            json={"username": username, "password": f"{username}-password", "role": role},
        )
        assert created.status_code == 200

    for username in ("member", "viewer"):
        client.post("/api/auth/logout")
        _login(client, username, f"{username}-password")
        for method, path, body in (
            ("GET", "/api/admin/secrets", None),
            ("POST", "/api/admin/secrets", {
                "name": "Blocked", "kind": "ai", "provider": "gemini",
                "env_name": "BLOCKED_KEY", "value": "blocked-value",
            }),
            ("PUT", "/api/admin/secrets/missing/value", {"value": "blocked-value"}),
            ("DELETE", "/api/admin/secrets/missing", None),
        ):
            response = client.request(method, path, json=body)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "forbidden"
            assert "blocked-value" not in response.text


def test_referenced_secret_cannot_be_deleted_and_rotation_resets_only_its_health(tmp_path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    secret = _create_secret(client)
    owner = store.get_user_by_username("owner")
    workspace = store.get_default_workspace()
    assert owner is not None

    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "apify_social",
            "display_name": "X Primary",
            "config": {"platform": "x", "kind": "profile", "target": "example", "fetch_limit": 20},
            "secret_env": "APIFY_TOKEN",
        },
    ).json()["data"]
    other_source_id = store.create_source(
        workspace_id=workspace["id"], scope="private", owner_user_id=owner["id"],
        source_type="rss", display_name="Other RSS",
        config={"url": "https://example.com/rss.xml"}, source_key="rss:https://example.com/rss.xml",
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source["id"])
    other_subscription = store.create_subscription(user_id=owner["id"], source_id=other_source_id)
    for source_id, sub_id in ((source["id"], subscription["id"]), (other_source_id, other_subscription["id"])):
        store.connect().execute(
            """
            INSERT INTO user_source_health (
                subscription_id, workspace_id, user_id, source_id, status,
                last_attempt_at, consecutive_failures, last_fetched_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'healthy', ?, 0, 1, ?, ?)
            """,
            (
                sub_id, workspace["id"], owner["id"], source_id,
                "2026-07-13T00:00:00+00:00", "2026-07-13T00:00:00+00:00",
                "2026-07-13T00:00:00+00:00",
            ),
        )
    store.connect().commit()

    denied = client.delete(f"/api/admin/secrets/{secret['id']}")
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "secret_in_use"

    rotated = client.put(
        f"/api/admin/secrets/{secret['id']}/value",
        json={"value": "new-private-value"},
    )
    assert rotated.status_code == 200
    remaining = store.connect().execute(
        "SELECT source_id FROM user_source_health ORDER BY source_id"
    ).fetchall()
    assert [row[0] for row in remaining] == [other_source_id]


def test_non_admin_catalog_hides_env_name_and_cannot_assign_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MISSING_APIFY_KEY", raising=False)
    client, _store = _client(tmp_path, monkeypatch)
    _login(client)
    _create_secret(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "apify_social",
            "display_name": "Shared X",
            "config": {"platform": "x", "kind": "profile", "target": "example", "fetch_limit": 20},
            "secret_env": "APIFY_TOKEN",
        },
    )
    assert source.status_code == 200
    missing_value_source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "apify_social",
            "display_name": "Shared X Missing Key",
            "config": {"platform": "x", "kind": "profile", "target": "missing", "fetch_limit": 20},
            "secret_env": "MISSING_APIFY_KEY",
        },
    )
    assert missing_value_source.status_code == 200
    member = client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )
    assert member.status_code == 200
    client.post("/api/auth/logout")
    _login(client, "member", "member-password")

    listed_sources = {
        item["display_name"]: item
        for item in client.get("/api/catalog/sources").json()["data"]["sources"]
    }
    assert all("secret_env" not in item for item in listed_sources.values())
    assert listed_sources["Shared X"]["secret_configured"] is True
    assert listed_sources["Shared X Missing Key"]["secret_configured"] is False

    forbidden = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "apify_social",
            "display_name": "Member X",
            "config": {"platform": "x", "kind": "profile", "target": "member", "fetch_limit": 20},
            "secret_env": "APIFY_TOKEN",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"

    facade_forbidden = client.post(
        "/api/config/action",
        json={
            "action": "upsert_apify_social_subscription",
            "payload": {
                "platform": "x", "kind": "profile", "target": "member",
                "fetch_limit": 20, "token_env": "APIFY_TOKEN", "enabled": True,
            },
        },
    )
    assert facade_forbidden.status_code == 403
    assert facade_forbidden.json()["error"]["code"] == "forbidden"
