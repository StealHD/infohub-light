import json

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


def _minimal_config():
    return {
        "version": "1.0",
        "ai": {
            "enabled": False,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "tags": ["AI Agent"],
        "personal_tags": ["高定"],
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    (data_dir / "site").mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (data_dir / "config.json").write_text(json.dumps(_minimal_config()), encoding="utf-8")
    app = create_app(data_dir=data_dir, static_dir=static_dir)
    return TestClient(app), data_dir


def _login_as(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response


def _logout(client):
    client.post("/api/auth/logout")


def _seed_roles_and_sources(client, data_dir):
    _login_as(client, "owner", "secret-password")
    users = {}
    for username, role in [("admin", "admin"), ("member", "member"), ("viewer", "viewer")]:
        users[username] = client.post(
            "/api/users",
            json={"username": username, "password": f"{username}-password", "role": role},
        ).json()["data"]

    public_source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Public Matrix RSS",
            "config": {"name": "Public Matrix RSS", "url": "https://example.com/public.xml"},
        },
    ).json()["data"]
    client.post(f"/api/catalog/sources/{public_source['id']}/subscribe")
    owner_job = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]

    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    member_private_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=users["member"]["id"],
        source_type="rss",
        display_name="Member Private RSS",
        config={"name": "Member Private RSS", "url": "https://example.com/member.xml"},
    )
    store.create_subscription(
        user_id=users["member"]["id"], source_id=member_private_id
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=users["viewer"]["id"],
        job_id="job_viewer",
        payload={"generated_at": "2026-07-09T15:30:00+08:00", "items": [{"id": "rss:item:viewer"}]},
    )
    _logout(client)
    return {
        "users": users,
        "public_source": public_source,
        "member_private_id": member_private_id,
        "owner_job": owner_job,
    }


def _assert_error(response, status_code, code):
    assert response.status_code == status_code
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    assert set(payload["error"]) == {"code", "message", "retryable", "action"}


def test_anonymous_core_api_returns_unauthorized_envelope(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)

    for method, path in [
        ("GET", "/api/users"),
        ("GET", "/api/catalog/sources"),
        ("GET", "/api/me/subscriptions"),
        ("GET", "/api/jobs"),
        ("GET", "/api/feed/latest"),
        ("GET", "/api/feed/end-messages"),
        ("GET", "/api/config"),
        ("GET", "/api/me/item-state?article_ids=rss:item:1"),
        ("GET", "/api/me/notification-settings"),
    ]:
        response = client.request(method, path)
        _assert_error(response, 401, "unauthorized")


def test_api_unknown_path_and_validation_errors_use_envelope(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)

    missing = client.get("/api/does-not-exist")
    _assert_error(missing, 404, "not_found")

    _login_as(client, "owner", "secret-password")
    invalid = client.post("/api/catalog/sources", json={"type": "rss"})
    _assert_error(invalid, 400, "invalid_request")


def test_viewer_is_read_only_across_core_service_api(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    fixture = _seed_roles_and_sources(client, data_dir)
    public_source_id = fixture["public_source"]["id"]

    _login_as(client, "viewer", "viewer-password")

    for response in [
        client.get("/api/catalog/sources"),
        client.get("/api/me/subscriptions"),
        client.get("/api/jobs"),
        client.get("/api/feed/latest"),
        client.get("/api/feed/end-messages"),
        client.get("/api/me/item-state?article_ids=rss:item:viewer"),
        client.get("/api/config"),
        client.get("/api/me/notification-settings"),
    ]:
        assert response.status_code == 200
        assert response.json()["ok"] is True

    forbidden_requests = [
        client.post(
            "/api/catalog/sources",
            json={
                "scope": "private",
                "type": "rss",
                "display_name": "Viewer RSS",
                "config": {"name": "Viewer RSS", "url": "https://example.com/viewer.xml"},
            },
        ),
        client.post(f"/api/catalog/sources/{public_source_id}/subscribe"),
        client.post("/api/jobs/user-feed-refresh", json={}),
        client.patch("/api/me/items/rss:item:viewer/state", json={"is_read": True}),
        client.post("/api/config/action", json={"action": "upsert_rss", "payload": {"name": "Viewer RSS"}}),
        client.post("/api/source/test", json={"source_id": public_source_id}),
        client.post("/api/source/update", json={"source_id": public_source_id}),
        client.patch(
            "/api/me/notification-settings",
            json={
                "enabled": True,
                "channel": "webhook",
                "webhook_url": "https://hooks.example.com/viewer",
            },
        ),
        client.post("/api/me/notification-settings/test"),
        client.post("/api/admin/feed-end-messages/refresh"),
    ]
    for response in forbidden_requests:
        _assert_error(response, 403, "forbidden")


def test_global_config_actions_require_admin_role(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _seed_roles_and_sources(client, data_dir)
    actions = [
        (
            "set_ai",
            {
                "enabled": False,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
                "languages": "zh",
            },
        ),
        (
            "set_feed_end_messages",
            {
                "ai_generation_enabled": False,
                "refresh_days": 7,
                "style_preset": "restrained",
                "style_prompt": "",
                "list_count": 12,
            },
        ),
        ("set_rsshub", {"base_url": "https://rsshub.example.com"}),
        ("set_filtering", {"ai_score_threshold": 8.0}),
        ("set_tags", {"tags": "Blocked Topic"}),
        ("set_settings_bundle", {"topics": {"topics": ["Blocked Topic"]}}),
        ("set_personal_tags", {"personal_tags": "Blocked Personal Tag"}),
        ("set_hackernews", {"enabled": True, "fetch_top_stories": 30, "min_score": 100}),
        ("set_apify_social_settings", {"enabled": False, "token_envs": "APIFY_TOKEN"}),
    ]

    for username in ("member", "viewer"):
        _login_as(client, username, f"{username}-password")
        for action, payload in actions:
            response = client.post(
                "/api/config/action",
                json={"action": action, "payload": payload},
            )
            _assert_error(response, 403, "forbidden")
        _logout(client)

    _login_as(client, "admin", "admin-password")
    for action, payload in actions:
        response = client.post(
            "/api/config/action",
            json={"action": action, "payload": payload},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_member_source_and_job_permissions_are_user_scoped(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    fixture = _seed_roles_and_sources(client, data_dir)
    public_source_id = fixture["public_source"]["id"]
    member_private_id = fixture["member_private_id"]
    owner_job_id = fixture["owner_job"]["id"]

    _login_as(client, "member", "member-password")

    for response in [
        client.patch(f"/api/catalog/sources/{public_source_id}", json={"display_name": "Blocked"}),
        client.delete(f"/api/catalog/sources/{public_source_id}"),
    ]:
        _assert_error(response, 403, "forbidden")

    patched = client.patch(
        f"/api/catalog/sources/{member_private_id}",
        json={"display_name": "Member Private Updated"},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["display_name"] == "Member Private Updated"

    member_job = client.post("/api/jobs/user-feed-refresh", json={})
    assert member_job.status_code == 200
    assert member_job.json()["data"]["user_id"] == fixture["users"]["member"]["id"]

    for response in [
        client.get(f"/api/jobs/{owner_job_id}"),
        client.post(f"/api/jobs/{owner_job_id}/cancel"),
        client.post(f"/api/jobs/{owner_job_id}/retry"),
    ]:
        _assert_error(response, 403, "forbidden")


def test_admin_can_manage_shared_source(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    fixture = _seed_roles_and_sources(client, data_dir)
    public_source_id = fixture["public_source"]["id"]

    _login_as(client, "admin", "admin-password")
    patched = client.patch(
        f"/api/catalog/sources/{public_source_id}",
        json={"display_name": "Admin Updated RSS"},
    )
    deleted = client.delete(f"/api/catalog/sources/{public_source_id}")

    assert patched.status_code == 200
    assert patched.json()["data"]["display_name"] == "Admin Updated RSS"
    assert deleted.status_code == 200
    assert deleted.json()["data"]["enabled"] is False


def test_viewer_can_read_but_cannot_patch_own_feed_schedule(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _seed_roles_and_sources(client, data_dir)
    _login_as(client, "viewer", "viewer-password")

    fetched = client.get("/api/me/feed-schedule")
    patched = client.patch(
        "/api/me/feed-schedule",
        json={"enabled": False, "interval_minutes": 360},
    )

    assert fetched.status_code == 200
    assert fetched.json()["data"]["enabled"] is False
    _assert_error(patched, 403, "forbidden")
