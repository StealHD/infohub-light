import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.models import ContentItem, SourceType
from src.services.user_feed_store import UserFeedStore
from src.storage.article_store import ArticleStore
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
        "tags": ["AI Agent", "产品创业"],
        "personal_tags": ["高定"],
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }


def _write_config(data_dir, config=None):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text(
        json.dumps(config or _minimal_config()),
        encoding="utf-8",
    )


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    (data_dir / "site").mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_app(data_dir=data_dir, static_dir=static_dir)
    return TestClient(app), data_dir


def _login(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "secret-password"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    return response


def _login_as(client, username, password):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response


def test_api_auth_users_and_error_envelope(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)

    status = client.get("/api/auth/status").json()
    assert status == {"ok": True, "data": {"authenticated": False, "user": None}}

    forbidden = client.get("/api/users")
    assert forbidden.status_code == 401
    assert forbidden.json()["ok"] is False
    assert forbidden.json()["error"]["code"] == "unauthorized"

    _login(client)
    created = client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )
    assert created.status_code == 200
    assert created.json()["data"]["username"] == "member"
    assert "password_hash" not in created.json()["data"]

    users = client.get("/api/users").json()["data"]["users"]
    assert {user["username"] for user in users} == {"owner", "member"}


def test_api_catalog_permissions_and_subscription_flow(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Public Feed",
            "default_channel": "AI",
            "default_topics": ["Codex"],
            "config": {"name": "Public Feed", "url": "https://example.com/feed.xml"},
            "secret_env": "RSS_PRIVATE_TOKEN",
        },
    ).json()["data"]
    assert source["secret_env"] == "RSS_PRIVATE_TOKEN"
    assert "real-token-value" not in json.dumps(source)

    client.post("/api/auth/logout")
    login_member = client.post(
        "/api/auth/login",
        json={"username": "member", "password": "member-password"},
    )
    assert login_member.status_code == 200
    forbidden = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Blocked",
            "config": {"name": "Blocked", "url": "https://example.com/blocked.xml"},
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"

    private_source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Private Feed",
            "config": {"name": "Private Feed", "url": "https://example.com/private.xml"},
        },
    )
    assert private_source.status_code == 200

    visible = client.get("/api/catalog/sources").json()["data"]["sources"]
    assert {item["display_name"] for item in visible} == {"Public Feed", "Private Feed"}

    subscription = client.post(
        "/api/me/subscriptions",
        json={
            "source_id": source["id"],
            "override_channel": "产品机会",
            "override_topics": ["价格监控"],
            "personal_tags": ["高定"],
            "analysis_mode": "personal_only",
        },
    )
    assert subscription.status_code == 200
    assert subscription.json()["data"]["source_id"] == source["id"]
    assert subscription.json()["data"]["personal_tags"] == ["高定"]


def test_catalog_subscribe_shortcut_and_viewer_read_only_boundaries(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )
    client.post(
        "/api/users",
        json={"username": "viewer", "password": "viewer-password", "role": "viewer"},
    )
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Shortcut Feed",
            "config": {"name": "Shortcut Feed", "url": "https://example.com/shortcut.xml"},
        },
    ).json()["data"]

    client.post("/api/auth/logout")
    _login_as(client, "member", "member-password")
    subscribed = client.post(f"/api/catalog/sources/{source['id']}/subscribe")
    assert subscribed.status_code == 200
    assert subscribed.json()["data"]["subscription"]["source_id"] == source["id"]

    unsubscribed = client.delete(f"/api/catalog/sources/{source['id']}/subscription")
    assert unsubscribed.status_code == 200
    assert unsubscribed.json()["data"]["deleted"] is True
    assert client.get("/api/me/subscriptions").json()["data"]["subscriptions"] == []

    client.post("/api/auth/logout")
    _login_as(client, "viewer", "viewer-password")
    for response in [
        client.post(f"/api/catalog/sources/{source['id']}/subscribe"),
        client.post(
            "/api/catalog/sources",
            json={
                "scope": "private",
                "type": "rss",
                "display_name": "Viewer Feed",
                "config": {"name": "Viewer Feed", "url": "https://example.com/viewer.xml"},
            },
        ),
        client.post("/api/jobs/user-feed-refresh", json={}),
    ]:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


def test_catalog_delete_soft_disables_source(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Deleted From Catalog",
            "config": {"name": "Deleted From Catalog", "url": "https://example.com/delete.xml"},
        },
    ).json()["data"]

    deleted = client.delete(f"/api/catalog/sources/{source['id']}")

    assert deleted.status_code == 200
    assert deleted.json()["data"]["enabled"] is False
    assert client.get("/api/catalog/sources").json()["data"]["sources"] == []
    store = ServiceStore(data_dir)
    store.initialize()
    assert store.get_source(source["id"])["enabled"] is False


def test_catalog_source_types_endpoint_and_validated_source_writes(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)

    unauthorized = client.get("/api/catalog/source-types")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    _login(client)
    source_types = client.get("/api/catalog/source-types")
    assert source_types.status_code == 200
    assert "github_release" in {item["type"] for item in source_types.json()["data"]["source_types"]}

    invalid_config = client.post(
        "/api/catalog/sources",
        json={"type": "rss", "display_name": "Bad RSS", "config": {"url": "ftp://example.com/feed.xml"}},
    )
    invalid_secret = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Secret RSS",
            "config": {"url": "https://example.com/feed.xml"},
            "secret_env": "sk-real-secret",
        },
    )
    created = client.post(
        "/api/catalog/sources",
        json={
            "type": "github_release",
            "display_name": "OpenAI Codex Releases",
            "config": {"owner": "OpenAI", "repo": "Codex"},
            "secret_env": "GITHUB_TOKEN",
        },
    )

    assert invalid_config.status_code == 400
    assert invalid_config.json()["error"]["code"] == "invalid_source_config"
    assert invalid_secret.status_code == 400
    assert invalid_secret.json()["error"]["code"] == "invalid_secret_env"
    assert created.status_code == 200
    source = created.json()["data"]
    assert source["scope"] == "public"
    assert source["source_key"] == "github_release:openai/codex"
    assert source["config"]["type"] == "repo_releases"
    assert source["secret_env"] == "GITHUB_TOKEN"

    patched = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"config": {"owner": "OpenAI", "repo": "Codex-CLI"}},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["source_key"] == "github_release:openai/codex-cli"


def test_catalog_import_config_sources_is_admin_only_and_idempotent(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    config = _minimal_config()
    config["sources"] = {
        "rss": [
            {
                "name": "Example RSS",
                "url": "https://example.com/feed.xml",
                "channel": "AI",
                "topics": ["Codex"],
            }
        ],
        "github": [
            {
                "type": "repo_releases",
                "owner": "OpenAI",
                "repo": "Codex",
                "channel": "AI",
            }
        ],
        "hackernews": {"enabled": True, "fetch_top_stories": 10, "min_score": 50},
        "reddit": {
            "enabled": True,
            "subreddits": [{"subreddit": "LocalLLaMA"}],
            "users": [{"username": "spez"}],
        },
        "telegram": {"enabled": True, "channels": [{"channel": "durov"}]},
        "apify_social": {
            "enabled": True,
            "token_env": "APIFY_TOKEN",
            "token_envs": ["APIFY_TOKEN"],
            "subscriptions": [
                {
                    "platform": "x",
                    "kind": "profile",
                    "target": "openai",
                    "token_env": "APIFY_TOKEN",
                }
            ],
        },
    }
    _write_config(data_dir, config)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )

    dry_run = client.post("/api/catalog/import-config-sources", json={"dry_run": True})
    first = client.post("/api/catalog/import-config-sources", json={})
    second = client.post("/api/catalog/import-config-sources", json={})

    assert dry_run.status_code == 200
    assert dry_run.json()["data"]["dry_run"] is True
    assert dry_run.json()["data"]["created"] == 0
    assert len(dry_run.json()["data"]["candidates"]) == 7
    assert first.status_code == 200
    assert first.json()["data"]["created"] == 7
    assert first.json()["data"]["updated"] == 0
    assert second.status_code == 200
    assert second.json()["data"]["created"] == 0
    assert second.json()["data"]["updated"] == 7

    sources = client.get("/api/catalog/sources").json()["data"]["sources"]
    subscriptions = client.get("/api/me/subscriptions").json()["data"]["subscriptions"]
    assert len(sources) == 7
    assert len(subscriptions) == 7
    assert "reddit_user:spez" in {source["source_key"] for source in sources}

    client.post("/api/auth/logout")
    _login_as(client, "member", "member-password")
    forbidden = client.post("/api/catalog/import-config-sources", json={})
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_user_feed_refresh_job_endpoint_creates_queued_job(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)

    response = client.post("/api/jobs/user-feed-refresh", json={"payload": {"reason": "manual"}})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["job_type"] == "user_feed_refresh"
    assert data["status"] == "queued"
    assert data["payload_json"] == {"reason": "manual"}


def test_job_cancel_and_retry_api_respects_owner_permissions(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    job = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]

    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"

    retried = client.post(f"/api/jobs/{job['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "queued"
    assert retried.json()["data"]["attempts"] == 0


def test_viewer_cannot_cancel_or_retry_jobs(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "viewer", "password": "viewer-password", "role": "viewer"},
    )
    job = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]
    client.post("/api/auth/logout")
    _login_as(client, "viewer", "viewer-password")

    for response in [
        client.post(f"/api/jobs/{job['id']}/cancel"),
        client.post(f"/api/jobs/{job['id']}/retry"),
    ]:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


def test_dashboard_summary_requires_login_and_returns_counts(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    (data_dir / "site" / "radar-data.json").write_text(
        json.dumps({"items": [], "generated_at": "2026-07-09T00:00:00+08:00"}),
        encoding="utf-8",
    )

    unauthorized = client.get("/api/dashboard/summary")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Dashboard Feed",
            "config": {"name": "Dashboard Feed", "url": "https://example.com/dashboard.xml"},
        },
    ).json()["data"]
    client.post(f"/api/catalog/sources/{source['id']}/subscribe")
    client.post("/api/jobs/user-feed-refresh", json={})
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_dashboard",
        payload={"items": [], "generated_at": "2026-07-09T00:00:00+08:00"},
    )

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_count"] == 1
    assert data["subscription_count"] == 1
    assert data["queued_job_count"] == 1
    assert data["running_job_count"] == 0
    assert data["failed_job_count"] == 0
    assert data["latest_generated_at"] == "2026-07-09T00:00:00+08:00"
    assert data["current_user"]["username"] == "owner"
    assert "password_hash" not in data["current_user"]


def test_api_jobs_feed_and_archive_facades(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)

    latest_payload = {"items": [{"id": "rss:item:archive", "channel": "AI"}], "generated_at": "now"}
    graph_payload = {"nodes": [], "edges": []}
    (data_dir / "site" / "radar-data.json").write_text(json.dumps(latest_payload), encoding="utf-8")
    (data_dir / "site" / "article-graph.json").write_text(json.dumps(graph_payload), encoding="utf-8")
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_latest",
        payload=latest_payload,
    )

    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Public Feed",
            "config": {"name": "Public Feed", "url": "https://example.com/feed.xml"},
        },
    ).json()["data"]
    job = client.post(
        "/api/jobs/source-test",
        json={"source_id": source["id"], "payload": {"source_type": "rss"}},
    )
    assert job.status_code == 200
    assert job.json()["data"]["status"] == "queued"
    assert client.get(f"/api/jobs/{job.json()['data']['id']}").json()["data"]["job_type"] == "source_test"

    latest_data = client.get("/api/feed/latest").json()["data"]
    assert latest_data["items"][0]["id"] == "rss:item:archive"
    assert latest_data["items"][0]["channel"] == "AI"
    assert latest_data["items"][0]["user_state"]["is_read"] is False
    assert latest_data["generated_at"] == "now"
    assert latest_data["scope"] == "user"
    assert client.get("/api/feed/history").json()["data"] == {
        "snapshots": [
            {
                "snapshot_id": snapshot["id"],
                "generated_at": "now",
                "item_count": 1,
                "job_id": "job_latest",
            }
        ],
        "scope": "user",
    }
    assert client.get("/api/archive/graph").json()["data"] == graph_payload

    article_store = ArticleStore(data_dir)
    article_store.initialize()
    item = ContentItem(
        id="rss:item:archive",
        source_type=SourceType.RSS,
        title="Archive item",
        url="https://example.com/archive",
        published_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )
    item.ai_score = 8.5
    item.ai_channel = "AI"
    item.ai_topics = ["Codex"]
    article_store.upsert_articles_light([item])

    trends = client.get("/api/archive/trends?group_by=channel").json()["data"]["trends"]
    assert trends == [{"key": "AI", "count": 1}]

    quality = client.get("/api/archive/source-quality").json()["data"]["sources"]
    assert quality[0]["source"] == "rss"
    assert quality[0]["total_items"] == 1


def test_archive_source_quality_falls_back_to_user_snapshot_without_article_store(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_snapshot_quality",
        payload={
            "generated_at": "2026-07-09T12:00:00+08:00",
            "today_items": [
                {
                    "id": "rss:item:snapshot-quality",
                    "source": "GitHub Blog",
                    "channel": "其他",
                    "topics": [],
                    "score": 0,
                    "signal_strength": "thin",
                    "published_at": "2026-07-09T00:00:00+00:00",
                }
            ],
        },
    )

    quality = client.get("/api/archive/source-quality").json()["data"]["sources"]

    assert quality == [
        {
            "source": "GitHub Blog",
            "total_items": 1,
            "hit_rate": 0.0,
            "other_channel_rate": 1.0,
            "empty_topics_rate": 1.0,
            "thin_signal_rate": 1.0,
            "last_seen_at": "2026-07-09T00:00:00+00:00",
        }
    ]


def test_api_catalog_source_fetch_queues_source_scoped_job_and_viewer_is_read_only(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "viewer", "password": "viewer-password", "role": "viewer"},
    )
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Catalog Fetch Feed",
            "config": {"name": "Catalog Fetch Feed", "url": "https://example.com/catalog-fetch.xml"},
        },
    ).json()["data"]

    queued = client.post(
        "/api/jobs/source-fetch",
        json={"source_id": source["id"], "payload": {"hours": 168}},
    )

    assert queued.status_code == 200
    job = queued.json()["data"]
    assert job["job_type"] == "source_fetch"
    assert job["source_id"] == source["id"]
    assert job["payload_json"] == {"hours": 168}
    assert job["status"] == "queued"

    client.post("/api/auth/logout")
    _login_as(client, "viewer", "viewer-password")
    forbidden = client.post(
        "/api/jobs/source-fetch",
        json={"source_id": source["id"], "payload": {"hours": 168}},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_feed_latest_returns_user_scoped_degraded_payload_without_snapshot(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    (data_dir / "site" / "radar-data.json").write_text(
        json.dumps({"items": [{"id": "global:item"}], "generated_at": "global"}),
        encoding="utf-8",
    )

    latest = client.get("/api/feed/latest")
    history = client.get("/api/feed/history")

    assert latest.status_code == 200
    assert latest.json()["data"] == {
        "items": [],
        "channels": [],
        "topics": [],
        "generated_at": "",
        "ai_enabled": False,
        "scope": "user",
        "degraded": True,
        "reason": "no_user_snapshot",
    }
    assert history.json()["data"] == {"snapshots": [], "scope": "user"}


def test_admin_can_read_member_feed_snapshot_but_member_cannot_read_others(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    member = client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    ).json()["data"]
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_id="job_member",
        payload={"generated_at": "2026-07-09T10:00:00+08:00", "items": [{"id": "rss:item:member"}]},
    )

    admin_view = client.get(f"/api/feed/latest?user_id={member['id']}")
    _login_as(client, "member", "member-password")
    forbidden = client.get(f"/api/feed/latest?user_id={owner['id']}")

    assert admin_view.status_code == 200
    assert admin_view.json()["data"]["items"][0]["id"] == "rss:item:member"
    assert admin_view.json()["data"]["scope"] == "user"
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_item_state_api_updates_visible_items_and_feed_returns_user_state(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    unauthorized = client.get("/api/me/item-state?article_ids=rss:item:1")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    _login(client)
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_owner",
        payload={
            "generated_at": "2026-07-09T12:30:00+08:00",
            "items": [{"id": "rss:item:1", "title": "Visible item"}],
        },
    )

    missing = client.patch("/api/me/items/rss:item:missing/state", json={"is_saved": True})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    updated = client.patch(
        "/api/me/items/rss:item:1/state",
        json={"is_read": True, "is_saved": True, "is_later": True},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["is_read"] is True
    assert updated.json()["data"]["is_saved"] is True
    assert updated.json()["data"]["is_later"] is True

    feedback = client.post(
        "/api/me/items/rss:item:1/feedback",
        json={"feedback_type": "more_like_this", "reason": "useful"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["data"]["feedback_type"] == "more_like_this"

    invalid_feedback = client.post(
        "/api/me/items/rss:item:1/feedback",
        json={"feedback_type": "bad_signal"},
    )
    assert invalid_feedback.status_code == 400
    assert invalid_feedback.json()["error"]["code"] == "invalid_feedback_type"

    states = client.get("/api/me/item-state?article_ids=rss:item:1,rss:item:missing")
    assert states.status_code == 200
    assert states.json()["data"]["states"]["rss:item:1"]["is_saved"] is True
    assert states.json()["data"]["states"]["rss:item:missing"]["is_read"] is False

    latest = client.get("/api/feed/latest").json()["data"]
    assert latest["items"][0]["user_state"]["is_read"] is True
    assert latest["items"][0]["user_state"]["is_saved"] is True
    assert latest["items"][0]["user_state"]["is_later"] is True


def test_viewer_cannot_write_item_state_or_feedback(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    viewer = client.post(
        "/api/users",
        json={"username": "viewer", "password": "viewer-password", "role": "viewer"},
    ).json()["data"]
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=viewer["id"],
        job_id="job_viewer",
        payload={"generated_at": "2026-07-09T12:30:00+08:00", "items": [{"id": "rss:item:viewer"}]},
    )

    client.post("/api/auth/logout")
    _login_as(client, "viewer", "viewer-password")

    readable = client.get("/api/me/item-state?article_ids=rss:item:viewer")
    assert readable.status_code == 200

    for response in [
        client.patch("/api/me/items/rss:item:viewer/state", json={"is_read": True}),
        client.post("/api/me/items/rss:item:viewer/feedback", json={"feedback_type": "not_relevant"}),
    ]:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


def test_archive_api_uses_current_user_visible_articles_and_returns_facets(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    article_store = ArticleStore(data_dir)
    article_store.initialize()
    visible = ContentItem(
        id="rss:item:visible",
        source_type=SourceType.RSS,
        title="Visible Codex",
        url="https://example.com/visible",
        published_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        metadata={"feed_name": "Example RSS"},
    )
    visible.ai_score = 9.0
    visible.ai_channel = "AI"
    visible.ai_topics = ["Codex"]
    visible.ai_signal_strength = "strong"
    visible.ai_entities = ["OpenAI"]
    hidden = ContentItem(
        id="rss:item:hidden",
        source_type=SourceType.RSS,
        title="Hidden Codex",
        url="https://example.com/hidden",
        published_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        metadata={"feed_name": "Example RSS"},
    )
    hidden.ai_score = 9.9
    hidden.ai_channel = "AI"
    hidden.ai_topics = ["Codex"]
    hidden.ai_signal_strength = "strong"
    hidden.ai_entities = ["OpenAI"]
    article_store.upsert_articles_light([visible, hidden])
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_owner",
        payload={
            "generated_at": "2026-07-09T10:00:00+08:00",
            "items": [
                {
                    "id": "rss:item:visible",
                    "source": "Example RSS",
                    "channel": "AI",
                    "topics": ["Codex"],
                    "score": 9.0,
                    "published_at": "2026-07-08T00:00:00+00:00",
                }
            ],
        },
    )

    items = client.get(
        "/api/archive/items?channel=AI&topic=Codex&min_score=8&limit=10&offset=0&sort=score&order=desc"
    ).json()["data"]
    trends = client.get("/api/archive/trends?group_by=topic&bucket=none").json()["data"]["trends"]
    facets = client.get("/api/archive/facets").json()["data"]
    quality = client.get("/api/archive/source-quality").json()["data"]["sources"]

    assert items["page"] == {"limit": 10, "offset": 0, "total": 1, "has_more": False}
    assert [item["id"] for item in items["items"]] == ["rss:item:visible"]
    assert items["scope"]["user_id"] == owner["id"]
    assert trends == [{"key": "Codex", "count": 1}]
    assert facets["channels"] == [{"key": "AI", "count": 1}]
    assert facets["topics"] == [{"key": "Codex", "count": 1}]
    assert facets["sources"] == [{"key": "Example RSS", "count": 1}]
    assert quality[0]["source"] == "Example RSS"
    assert quality[0]["total_items"] == 1
    assert quality[0]["last_seen_at"] == "2026-07-08T00:00:00+00:00"


def test_archive_api_rejects_invalid_query_params_with_error_envelope(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)

    invalid_sort = client.get("/api/archive/items?sort=bad")
    invalid_dates = client.get("/api/archive/items?date_from=2026-07-10&date_to=2026-07-01")
    invalid_group = client.get("/api/archive/trends?group_by=bad")

    assert invalid_sort.status_code == 400
    assert invalid_sort.json()["error"]["code"] == "invalid_sort"
    assert invalid_dates.status_code == 400
    assert invalid_dates.json()["error"]["code"] == "invalid_date_range"
    assert invalid_group.status_code == 400
    assert invalid_group.json()["error"]["code"] == "invalid_group_by"


def test_archive_facets_respects_query_filters(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    article_store = ArticleStore(data_dir)
    article_store.initialize()
    ai_item = ContentItem(
        id="rss:item:ai",
        source_type=SourceType.RSS,
        title="AI item",
        url="https://example.com/ai",
        published_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        metadata={"feed_name": "Example RSS"},
    )
    ai_item.ai_score = 9.0
    ai_item.ai_channel = "AI"
    ai_item.ai_topics = ["Codex"]
    finance_item = ContentItem(
        id="rss:item:finance",
        source_type=SourceType.RSS,
        title="Finance item",
        url="https://example.com/finance",
        published_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        metadata={"feed_name": "Example RSS"},
    )
    finance_item.ai_score = 8.0
    finance_item.ai_channel = "投资"
    finance_item.ai_topics = ["Macro"]
    article_store.upsert_articles_light([ai_item, finance_item])
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_facets",
        payload={
            "generated_at": "2026-07-09T10:00:00+08:00",
            "items": [
                {"id": "rss:item:ai", "channel": "AI", "topics": ["Codex"], "source": "Example RSS"},
                {"id": "rss:item:finance", "channel": "投资", "topics": ["Macro"], "source": "Example RSS"},
            ],
        },
    )

    facets = client.get("/api/archive/facets?channel=AI").json()["data"]

    assert facets["channels"] == [{"key": "AI", "count": 1}]
    assert facets["topics"] == [{"key": "Codex", "count": 1}]


def test_feed_and_archive_facades_require_login(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    (data_dir / "site" / "radar-data.json").write_text(
        json.dumps({"items": []}),
        encoding="utf-8",
    )
    (data_dir / "site" / "history-data.json").write_text(
        json.dumps({"items": []}),
        encoding="utf-8",
    )
    (data_dir / "site" / "article-graph.json").write_text(
        json.dumps({"nodes": [], "edges": []}),
        encoding="utf-8",
    )

    for path in ["/api/feed/latest", "/api/feed/history", "/api/archive/graph"]:
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["ok"] is False
        assert response.json()["error"]["code"] == "unauthorized"


def test_api_config_requires_auth_and_returns_service_compatibility(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)

    unauthorized = client.get("/api/config")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["ok"] is False
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Subscribed Feed",
            "default_channel": "AI",
            "default_topics": ["AI Agent"],
            "config": {"name": "Subscribed Feed", "url": "https://example.com/feed.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        "/api/me/subscriptions",
        json={"source_id": source["id"], "personal_tags": ["高定"]},
    ).json()["data"]

    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["config"]["version"] == "1.0"
    assert data["service"]["current_user"]["username"] == "owner"
    assert data["service"]["sources"][0]["id"] == source["id"]
    assert data["service"]["subscriptions"][0]["id"] == subscription["id"]
    rss_entry = data["config"]["sources"]["rss"][0]
    assert rss_entry["source_id"] == source["id"]
    assert rss_entry["subscription_id"] == subscription["id"]
    assert rss_entry["scope"] == "public"
    assert rss_entry["channel"] == "AI"
    assert rss_entry["topics"] == ["AI Agent"]
    assert rss_entry["personal_tags"] == ["高定"]


def test_config_action_creates_public_catalog_source_and_subscription_for_admin(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)
    _login(client)

    response = client.post(
        "/api/config/action",
        json={
            "action": "upsert_rss",
            "payload": {
                "name": "Admin Feed",
                "url": "https://example.com/admin.xml",
                "channel": "产品创业",
                "topics": "AI Agent",
                "personal_tags": "高定",
                "enabled": True,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    rss_entry = data["config"]["sources"]["rss"][0]
    assert rss_entry["name"] == "Admin Feed"
    assert rss_entry["source_id"].startswith("src_")
    assert rss_entry["subscription_id"].startswith("sub_")

    sources = client.get("/api/catalog/sources").json()["data"]["sources"]
    assert len(sources) == 1
    assert sources[0]["scope"] == "public"
    assert sources[0]["config"]["url"] == "https://example.com/admin.xml"

    subscriptions = client.get("/api/me/subscriptions").json()["data"]["subscriptions"]
    assert len(subscriptions) == 1
    assert subscriptions[0]["source_id"] == sources[0]["id"]


def test_config_action_member_sources_are_private_and_viewer_cannot_create(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )
    client.post(
        "/api/users",
        json={"username": "viewer", "password": "viewer-password", "role": "viewer"},
    )

    client.post("/api/auth/logout")
    _login_as(client, "member", "member-password")
    created = client.post(
        "/api/config/action",
        json={
            "action": "upsert_rss",
            "payload": {
                "name": "Member Feed",
                "url": "https://example.com/member.xml",
                "enabled": True,
            },
        },
    )
    assert created.status_code == 200
    sources = client.get("/api/catalog/sources").json()["data"]["sources"]
    assert sources[0]["scope"] == "private"
    assert sources[0]["display_name"] == "Member Feed"

    client.post("/api/auth/logout")
    _login_as(client, "viewer", "viewer-password")
    forbidden = client.post(
        "/api/config/action",
        json={
            "action": "upsert_rss",
            "payload": {
                "name": "Viewer Feed",
                "url": "https://example.com/viewer.xml",
                "enabled": True,
            },
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_config_action_soft_deletes_service_source(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)
    _login(client)
    created = client.post(
        "/api/config/action",
        json={
            "action": "upsert_rss",
            "payload": {
                "name": "Delete Feed",
                "url": "https://example.com/delete.xml",
                "enabled": True,
            },
        },
    ).json()["data"]["config"]["sources"]["rss"][0]

    deleted = client.post(
        "/api/config/action",
        json={
            "action": "delete_rss",
            "payload": {"source_id": created["source_id"], "index": 0},
        },
    )

    assert deleted.status_code == 200
    assert deleted.json()["data"]["config"]["sources"]["rss"] == []
    assert client.get("/api/catalog/sources").json()["data"]["sources"] == []
    store = ServiceStore(data_dir)
    store.initialize()
    source = store.get_source(created["source_id"])
    assert source is not None
    assert source["enabled"] is False


def test_source_test_and_update_compatibility_endpoints_enqueue_jobs(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)
    _login(client)
    source_entry = client.post(
        "/api/config/action",
        json={
            "action": "upsert_rss",
            "payload": {
                "name": "Queued Feed",
                "url": "https://example.com/queued.xml",
                "enabled": True,
            },
        },
    ).json()["data"]["config"]["sources"]["rss"][0]

    test_job = client.post(
        "/api/source/test",
        json={"source_id": source_entry["source_id"]},
    )
    assert test_job.status_code == 200
    test_data = test_job.json()["data"]
    assert test_data["status"] == "queued"
    assert test_data["job_type"] == "source_test"
    assert test_data["source_id"] == source_entry["source_id"]
    assert "任务已排队" in test_data["message"]

    update_job = client.post(
        "/api/source/update",
        json={"source_id": source_entry["source_id"], "hours": 6},
    )
    assert update_job.status_code == 200
    update_data = update_job.json()["data"]
    assert update_data["status"] == "queued"
    assert update_data["job_type"] == "source_fetch"
    assert update_data["payload_json"]["hours"] == 6
