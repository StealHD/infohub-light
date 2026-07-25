import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import src.services.media_cache as media_cache_module
from src.api.server import create_app
from src.models import ContentItem, SourceType
from src.services.feed_archive import FeedArchiveService
from src.services.job_queue import JobQueue
from src.services.notification_email_transport import (
    WorkspaceEmailTransportService,
)
from src.services.quota import QuotaService
from src.services.secret_store import SecretStore
from src.services.subscription_mutation import SubscriptionMutationService
from src.services.user_feed_store import UserFeedStore
from src.services.user_item_state import UserItemStateStore
from src.storage.article_store import ArticleStore
from src.storage.service_store import ServiceStore
from src.ui.site import serialize_item


SAFE_DISABLED_GRAPH = {
    "nodes": [],
    "edges": [],
    "scope": "user",
    "capability": "disabled",
    "degraded": True,
    "reason": "user_scoped_graph_not_available",
}


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


def _assert_notification_destination_is_write_only(
    response,
    *destinations: str,
) -> dict:
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    rendered = json.dumps(payload, ensure_ascii=False)
    for destination in destinations:
        assert destination not in rendered
    return payload["data"]


def _seed_ready_workspace_email_transport(data_dir) -> None:
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    assert workspace is not None
    workspace_id = str(workspace["id"])
    credential = "test-only-email-credential"
    env_name = WorkspaceEmailTransportService.credential_env_name(
        workspace_id=workspace_id
    )
    SecretStore(data_dir).set(env_name, credential)
    store.upsert_workspace_email_transport(
        workspace_id=workspace_id,
        provider="resend",
        sender_email="notice@example.com",
        sender_name="InfoHub",
        region=None,
        smtp_username=None,
        enabled=True,
        credential_env_name=env_name,
        credential_secret_digest=hashlib.sha256(
            credential.encode("utf-8")
        ).hexdigest(),
        generation=1,
        last_test_status="sent",
        last_test_generation=1,
        last_test_attempted_at="2026-07-24T00:00:00+00:00",
        last_tested_at="2026-07-24T00:00:00+00:00",
        last_test_error_code=None,
    )


def test_api_request_transaction_boundary_releases_stale_sqlite_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_REQUIRE_WORKER_FOR_READINESS", "true")
    initial_client, data_dir = _client(tmp_path, monkeypatch)
    app = initial_client.app
    initial_client.close()
    api_store = app.state.service_store

    @app.get("/api/_test/leak-read-transaction")
    async def leak_read_transaction():
        conn = api_store.connect()
        conn.execute("BEGIN")
        conn.execute("SELECT * FROM worker_heartbeats").fetchall()
        return {"leaked": True}

    leak_route = app.router.routes.pop()
    catch_all_index = next(
        index
        for index, route in enumerate(app.router.routes)
        if getattr(route, "name", "") == "api_not_found"
    )
    app.router.routes.insert(catch_all_index, leak_route)

    external_store = ServiceStore(data_dir)
    external_store.initialize()
    external_store.upsert_worker_heartbeat(
        "external-worker",
        "running",
        now=datetime.now(timezone.utc) - timedelta(minutes=2),
    )

    with TestClient(app) as client:
        leaked = client.get("/api/_test/leak-read-transaction")
        assert leaked.status_code == 500
        assert leaked.json()["error"]["code"] == "database_transaction_leak"

        external_store.upsert_worker_heartbeat(
            "external-worker",
            "running",
            now=datetime.now(timezone.utc),
        )
        ready = client.get("/api/health/ready")

    assert ready.status_code == 200
    assert ready.json()["data"]["worker_status"] == "ready"


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


def test_catalog_source_post_is_idempotent_by_workspace_source_key(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    first_payload = {
        "type": "rss",
        "display_name": "First display name",
        "description": "first request",
        "config": {"name": "Stable Feed", "url": "https://example.com/stable.xml"},
    }
    second_payload = {
        **first_payload,
        "display_name": "Updated display name",
        "description": "safe retry",
    }

    first = client.post("/api/catalog/sources", json=first_payload)
    second = client.post("/api/catalog/sources", json=second_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["content-type"].startswith("application/json")
    assert second.json()["ok"] is True
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert second.json()["data"]["display_name"] == "Updated display name"
    sources = client.get("/api/catalog/sources").json()["data"]["sources"]
    matching = [source for source in sources if source["source_key"] == "rss:https://example.com/stable.xml"]
    assert len(matching) == 1


def test_private_source_share_reuses_content_and_keeps_subscribers_isolated(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    owner = client.get("/api/auth/status").json()["data"]["user"]
    member = client.post(
        "/api/users",
        json={"username": "share-member", "password": "member-password", "role": "member"},
    ).json()["data"]
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Owner private feed",
            "config": {"url": "https://example.com/private-share.xml"},
        },
    ).json()["data"]
    owner_subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    donor = ContentItem(
        id="rss:shared-existing",
        source_type=SourceType.RSS,
        title="Already fetched once",
        url="https://example.com/private-share/article",
        content="Already fetched once",
        published_at=datetime.now(timezone.utc),
        metadata={
            "source_id": source["id"],
            "source_ids": [source["id"]],
            "subscription_id": owner_subscription["id"],
            "subscription_ids": [owner_subscription["id"]],
            "source_display_name": "Owner private feed",
            "catalog_source_type": "rss",
            "analysis_mode": "full",
        },
    )
    UserFeedStore(client.app.state.service_store).save_snapshot(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [serialize_item(donor, featured_threshold=8.0)],
        },
    )
    owner_feed = client.get("/api/feed/latest").json()["data"]
    assert "_source_native_title" not in json.dumps(owner_feed, sort_keys=True)
    assert client.patch(
        "/api/me/items/rss:shared-existing/state",
        json={"is_saved": True},
    ).status_code == 200
    assert "_source_native_title" not in json.dumps(
        client.get("/api/feed/saved").json()["data"],
        sort_keys=True,
    )
    assert "_source_native_title" not in json.dumps(
        client.get("/api/feed/items/rss:shared-existing").json()["data"],
        sort_keys=True,
    )

    shared = client.post(
        f"/api/catalog/sources/{source['id']}/share",
        json={"scope": "workspace"},
    )
    assert shared.status_code == 200
    assert shared.json()["data"]["source"]["scope"] == "workspace"
    assert shared.json()["data"]["source"]["owner_user_id"] is None
    assert shared.json()["data"]["management_transferred"] is True
    assert client.get(f"/api/catalog/sources/{source['id']}/usage").json()["data"] == {
        "source_id": source["id"],
        "subscriber_count": 1,
        "enabled_subscriber_count": 1,
    }

    _login_as(client, "share-member", "member-password")
    subscribed = client.post(f"/api/catalog/sources/{source['id']}/subscribe")
    assert subscribed.status_code == 200
    assert subscribed.json()["data"]["subscription"]["reused_item_count"] == 1
    member_feed = client.get("/api/feed/latest").json()["data"]
    assert [item["id"] for item in member_feed["items"]] == ["rss:shared-existing"]
    reused_item = member_feed["items"][0]
    assert reused_item["subscription_id"] == subscribed.json()["data"]["subscription"]["id"]
    assert reused_item["analysis_mode"] == "full"
    assert reused_item["score"] == 0
    assert reused_item["summary_zh"] == "Already fetched once"
    assert reused_item["presentation"]["analysis"]["status"] == "fallback"
    assert reused_item["presentation"]["analysis"]["score"] == 0
    assert reused_item["image_url"] == ""
    assert reused_item["media_urls"] == []

    usage = client.get(f"/api/catalog/sources/{source['id']}/usage").json()["data"]
    assert usage["subscriber_count"] == 2
    assert client.delete(f"/api/catalog/sources/{source['id']}/subscription").status_code == 200
    assert client.app.state.service_store.get_source(source["id"])["enabled"] is True

    _login(client)
    assert client.get(f"/api/catalog/sources/{source['id']}/usage").json()["data"]["subscriber_count"] == 1
    assert client.get("/api/feed/latest").json()["data"]["items"][0]["id"] == "rss:shared-existing"
    assert member["id"] != owner["id"]
    client.app.state.service_store.close()
    client.close()


def test_subscription_disable_can_save_or_dismiss_existing_source_content(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    owner = client.get("/api/auth/status").json()["data"]["user"]
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "rss",
            "display_name": "Lifecycle source",
            "config": {"url": "https://example.com/lifecycle-choice.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    lifecycle_item = ContentItem(
        id="rss:lifecycle-item",
        source_type=SourceType.RSS,
        title="Lifecycle item",
        url="https://example.com/lifecycle-choice/article",
        content="Lifecycle item",
        published_at=datetime.now(timezone.utc),
        metadata={
            "source_id": source["id"],
            "subscription_id": subscription["id"],
            "source_display_name": "Lifecycle source",
            "catalog_source_type": "rss",
            "analysis_mode": "full",
        },
    )
    UserFeedStore(client.app.state.service_store).save_snapshot(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [serialize_item(lifecycle_item, featured_threshold=8.0)],
        },
    )

    saved = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": False, "on_disable": "save"},
    )
    assert saved.status_code == 200
    assert client.get("/api/feed/latest").json()["data"]["items"] == []
    assert [item["id"] for item in client.get("/api/feed/saved").json()["data"]["items"]] == [
        "rss:lifecycle-item"
    ]

    enabled = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["data"]["reused_item_count"] == 1
    dismissed = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": False, "on_disable": "dismiss"},
    )
    assert dismissed.status_code == 200
    state = client.get("/api/me/item-state?article_ids=rss:lifecycle-item").json()["data"]["states"]
    assert state["rss:lifecycle-item"]["dismissed"] is True
    client.app.state.service_store.close()
    client.close()


def test_unsubscribing_last_private_source_disables_orphan(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Temporary private source",
            "config": {"url": "https://example.com/private-orphan.xml"},
        },
    ).json()["data"]
    assert client.post(f"/api/catalog/sources/{source['id']}/subscribe").status_code == 200
    assert client.delete(f"/api/catalog/sources/{source['id']}/subscription").status_code == 200
    assert client.app.state.service_store.get_source(source["id"])["enabled"] is False


def test_ignored_collection_restores_items_and_user_can_change_own_password(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    owner = client.get("/api/auth/status").json()["data"]["user"]
    UserFeedStore(client.app.state.service_store).save_snapshot(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [{"id": "rss:ignored-settings", "title": "Restore me"}],
        },
    )
    ignored = client.patch(
        "/api/me/items/rss:ignored-settings/state",
        json={"dismissed": True},
    )
    assert ignored.status_code == 200
    collection = client.get("/api/feed/ignored").json()["data"]
    assert collection["item_count"] == 1
    assert collection["items"][0]["id"] == "rss:ignored-settings"

    restored = client.patch(
        "/api/me/items/rss:ignored-settings/state",
        json={"dismissed": False},
    )
    assert restored.status_code == 200
    assert client.get("/api/feed/ignored").json()["data"]["items"] == []

    wrong = client.post(
        "/api/me/password",
        json={"current_password": "wrong-password", "new_password": "new-secret-password"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "invalid_current_password"
    changed = client.post(
        "/api/me/password",
        json={"current_password": "secret-password", "new_password": "new-secret-password"},
    )
    assert changed.status_code == 200
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "new-secret-password"},
    ).status_code == 200


def test_rest_subscription_mutations_use_shared_service_without_exposing_network_marker(
    tmp_path, monkeypatch
):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    service = client.app.state.subscription_mutations
    assert isinstance(service, SubscriptionMutationService)

    source_response = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Shared boundary",
            "config": {"url": "https://example.com/shared-boundary.xml"},
        },
    )
    source = source_response.json()["data"]
    assert "enforce_public_network" not in source

    calls = []
    original = service.rest_create_subscription

    def tracked_create(actor, *, source_id, values):
        calls.append((actor.user_id, source_id, dict(values)))
        return original(actor, source_id=source_id, values=values)

    monkeypatch.setattr(service, "rest_create_subscription", tracked_create)
    response = client.post(
        "/api/me/subscriptions",
        json={"source_id": source["id"], "priority": 33},
    )

    assert response.status_code == 200
    assert response.json()["data"]["priority"] == 33
    assert len(calls) == 1
    assert calls[0][1] == source["id"]


def test_rest_source_identity_commit_removes_avatar_file_without_exposing_path(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Avatar identity source",
            "config": {"url": "https://example.com/avatar-before.xml"},
        },
    ).json()["data"]
    avatar_path = data_dir / "media" / "identity-avatar.png"
    avatar_path.parent.mkdir(parents=True, exist_ok=True)
    avatar_path.write_bytes(b"\x89PNG\r\n\x1a\nidentity-avatar")
    store = client.app.state.service_store
    now = "2026-07-17T00:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, source_id, asset_kind, remote_url, local_path,
            mime_type, byte_size, checksum, visibility_scope, status,
            created_at, updated_at
        ) VALUES ('med_identity_avatar', ?, ?, 'source_avatar', '',
                  'media/identity-avatar.png', 'image/png', 23, 'checksum',
                  'private', 'ready', ?, ?)
        """,
        (source["workspace_id"], source["id"], now, now),
    )
    store.connect().commit()
    cleanup_run_transaction_states = []
    original_cleanup_run = media_cache_module.PostCommitMediaCleanup.run

    def tracked_cleanup_run(cleanup):
        cleanup_run_transaction_states.append(store.connect().in_transaction)
        return original_cleanup_run(cleanup)

    monkeypatch.setattr(
        media_cache_module.PostCommitMediaCleanup, "run", tracked_cleanup_run
    )

    response = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"config": {"url": "https://example.com/avatar-after.xml"}},
    )

    assert response.status_code == 200
    assert cleanup_run_transaction_states == [False]
    assert not avatar_path.exists()
    assert store.connect().execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'med_identity_avatar'"
    ).fetchone()[0] == 0
    assert "local_path" not in repr(response.json())
    assert "identity-avatar.png" not in repr(response.json())


def test_catalog_source_patch_key_collision_returns_structured_conflict(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    first = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "First Feed",
            "config": {"url": "https://example.com/first.xml"},
        },
    ).json()["data"]
    second = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Second Feed",
            "config": {"url": "https://example.com/second.xml"},
        },
    ).json()["data"]

    response = client.patch(
        f"/api/catalog/sources/{second['id']}",
        json={"config": {"url": first["config"]["url"]}},
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "source_key_conflict",
            "message": "source_key already belongs to another catalog source",
            "retryable": False,
            "action": "Keep the current source configuration or choose a different source.",
        },
    }


def test_source_and_subscription_patch_distinguish_omitted_fields_from_explicit_clears(
    tmp_path, monkeypatch
):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Editable Feed",
            "description": "keep me",
            "default_channel": "AI",
            "default_topics": ["Codex"],
            "config": {"name": "Editable Feed", "url": "https://example.com/edit.xml"},
            "secret_env": "RSS_TOKEN",
        },
    ).json()["data"]
    subscription = client.post(
        "/api/me/subscriptions",
        json={
            "source_id": source["id"],
            "override_channel": "产品机会",
            "override_topics": ["AI Agent"],
            "personal_tags": ["高定"],
            "analysis_mode": "personal_only",
            "priority": 42,
        },
    ).json()["data"]

    source_omitted = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"display_name": "Renamed Feed"},
    )
    assert source_omitted.status_code == 200
    assert source_omitted.json()["data"] | {
        "default_channel": "AI",
        "default_topics": ["Codex"],
        "secret_env": "RSS_TOKEN",
    } == source_omitted.json()["data"]

    source_cleared = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"default_channel": None, "default_topics": [], "secret_env": None},
    )
    assert source_cleared.status_code == 200
    assert source_cleared.json()["data"]["default_channel"] is None
    assert source_cleared.json()["data"]["default_topics"] == []
    assert source_cleared.json()["data"]["secret_env"] is None
    assert source_cleared.json()["data"]["description"] == "keep me"
    assert source_cleared.json()["data"]["type"] == "rss"

    subscription_omitted = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": False},
    )
    assert subscription_omitted.status_code == 200
    assert subscription_omitted.json()["data"] | {
        "override_channel": "产品机会",
        "override_topics": ["AI Agent"],
        "personal_tags": ["高定"],
        "analysis_mode": "personal_only",
        "priority": 42,
    } == subscription_omitted.json()["data"]

    subscription_cleared = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={
            "override_channel": None,
            "override_topics": [],
            "personal_tags": [],
            "priority": 0,
        },
    )
    assert subscription_cleared.status_code == 200
    assert subscription_cleared.json()["data"]["override_channel"] is None
    assert subscription_cleared.json()["data"]["override_topics"] == []
    assert subscription_cleared.json()["data"]["personal_tags"] == []
    assert subscription_cleared.json()["data"]["analysis_mode"] == "personal_only"
    assert subscription_cleared.json()["data"]["priority"] == 0


def test_subscription_priority_api_rejects_non_integer_and_out_of_range_values(
    tmp_path, monkeypatch
):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Priority Feed",
            "config": {"url": "https://example.com/priority-api.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        "/api/me/subscriptions",
        json={"source_id": source["id"]},
    ).json()["data"]
    assert subscription["priority"] == 0

    for invalid in (-1, 101, 1.5, "10", True, None):
        response = client.patch(
            f"/api/me/subscriptions/{subscription['id']}",
            json={"priority": invalid},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    updated = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"priority": 100},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["priority"] == 100


def test_subscription_notification_preference_round_trip_and_personal_only_guard(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Notification Preference Feed",
            "config": {"url": "https://example.com/notification-preference.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        "/api/me/subscriptions",
        json={"source_id": source["id"]},
    ).json()["data"]

    assert subscription["notify_on_new_items"] is False
    assert subscription["notification_enabled_at"] is None

    enabled = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"notify_on_new_items": True},
    )
    assert enabled.status_code == 200
    enabled_data = enabled.json()["data"]
    assert enabled_data["notify_on_new_items"] is True
    assert datetime.fromisoformat(
        enabled_data["notification_enabled_at"].replace("Z", "+00:00")
    ).tzinfo is not None
    enabled_at = enabled_data["notification_enabled_at"]

    idempotent_patch = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"notify_on_new_items": True},
    )
    assert idempotent_patch.status_code == 200
    assert idempotent_patch.json()["data"]["notification_enabled_at"] == enabled_at

    idempotent_post = client.post(
        "/api/me/subscriptions",
        json={
            "source_id": source["id"],
            "enabled": True,
            "analysis_mode": "full",
        },
    )
    assert idempotent_post.status_code == 200
    assert idempotent_post.json()["data"]["id"] == subscription["id"]
    assert idempotent_post.json()["data"]["notify_on_new_items"] is True
    assert (
        idempotent_post.json()["data"]["notification_enabled_at"]
        == enabled_at
    )
    verification_store = ServiceStore(data_dir)
    stored_subscription = verification_store.get_subscription(subscription["id"])
    assert stored_subscription is not None
    assert stored_subscription["notify_on_new_items"] is True
    assert stored_subscription["notification_enabled_at"] == enabled_at
    verification_store.close()

    unrelated_patch = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"priority": 73},
    )
    assert unrelated_patch.status_code == 200
    assert unrelated_patch.json()["data"]["notify_on_new_items"] is True
    assert unrelated_patch.json()["data"]["notification_enabled_at"] == enabled_at

    listed = client.get("/api/me/subscriptions")
    listed_subscription = next(
        item
        for item in listed.json()["data"]["subscriptions"]
        if item["id"] == subscription["id"]
    )
    assert listed_subscription["notify_on_new_items"] is True
    assert listed_subscription["notification_enabled_at"] == enabled_at

    invalid_disable_and_notify = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": False, "notify_on_new_items": True},
    )
    assert invalid_disable_and_notify.status_code == 400
    assert (
        invalid_disable_and_notify.json()["error"]["code"]
        == "invalid_subscription_notification"
    )

    disabled = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["enabled"] is False
    assert disabled.json()["data"]["notify_on_new_items"] is False
    assert disabled.json()["data"]["notification_enabled_at"] is None

    reenabled = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": True},
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["data"]["notify_on_new_items"] is False
    assert reenabled.json()["data"]["notification_enabled_at"] is None

    disabled_notification = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": False},
    )
    assert disabled_notification.status_code == 200
    invalid_disabled_notification = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"notify_on_new_items": True},
    )
    assert invalid_disabled_notification.status_code == 400
    assert (
        invalid_disabled_notification.json()["error"]["code"]
        == "invalid_subscription_notification"
    )

    restored = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={"enabled": True},
    )
    assert restored.status_code == 200

    invalid_combination = client.patch(
        f"/api/me/subscriptions/{subscription['id']}",
        json={
            "analysis_mode": "personal_only",
            "notify_on_new_items": True,
        },
    )
    assert invalid_combination.status_code == 400
    assert invalid_combination.json()["ok"] is False

    unchanged = client.get("/api/me/subscriptions").json()["data"]["subscriptions"]
    unchanged_subscription = next(
        item for item in unchanged if item["id"] == subscription["id"]
    )
    assert unchanged_subscription["analysis_mode"] == "full"
    assert unchanged_subscription["notify_on_new_items"] is False
    assert unchanged_subscription["notification_enabled_at"] is None

    second_source = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Personal-only Notification Feed",
            "config": {"url": "https://example.com/personal-only-notification.xml"},
        },
    ).json()["data"]
    personal_only = client.post(
        "/api/me/subscriptions",
        json={
            "source_id": second_source["id"],
            "analysis_mode": "personal_only",
            "notify_on_new_items": True,
        },
    )
    assert personal_only.status_code == 400
    assert personal_only.json()["ok"] is False


def test_source_fetch_identity_changes_reset_all_subscriber_health_but_metadata_does_not(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    member = client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    ).json()["data"]
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Shared Health Feed",
            "default_channel": "AI",
            "config": {"url": "https://example.com/health-old.xml"},
            "secret_env": "RSS_TOKEN_A",
        },
    ).json()["data"]

    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    subscriptions = [
        store.create_subscription(user_id=owner["id"], source_id=source["id"]),
        store.create_subscription(user_id=member["id"], source_id=source["id"]),
    ]

    def seed_health() -> None:
        now = "2026-07-12T01:00:00+00:00"
        for subscription, user in zip(subscriptions, (owner, member)):
            store.connect().execute(
                """
                INSERT OR REPLACE INTO user_source_health (
                    subscription_id, workspace_id, user_id, source_id, status,
                    last_attempt_at, last_success_at, consecutive_failures,
                    last_fetched_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'healthy', ?, ?, 0, 1, ?, ?)
                """,
                (
                    subscription["id"],
                    user["workspace_id"],
                    user["id"],
                    source["id"],
                    now,
                    now,
                    now,
                    now,
                ),
            )
        store.connect().commit()

    seed_health()
    metadata_only = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"display_name": "Renamed Shared Feed", "default_channel": "产品机会"},
    )
    assert metadata_only.status_code == 200
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE source_id = ?", (source["id"],)
    ).fetchone()[0] == 2

    subscription_only = client.patch(
        f"/api/me/subscriptions/{subscriptions[0]['id']}",
        json={
            "override_channel": "AI",
            "override_topics": ["Codex"],
            "personal_tags": ["高定"],
            "analysis_mode": "personal_only",
            "priority": 75,
        },
    )
    assert subscription_only.status_code == 200
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE source_id = ?", (source["id"],)
    ).fetchone()[0] == 2

    same_identity = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={
            "config": {"url": "https://example.com/health-old.xml"},
            "secret_env": "RSS_TOKEN_A",
        },
    )
    assert same_identity.status_code == 200
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE source_id = ?", (source["id"],)
    ).fetchone()[0] == 2

    config_changed = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"config": {"url": "https://example.com/health-new.xml"}},
    )
    assert config_changed.status_code == 200
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE source_id = ?", (source["id"],)
    ).fetchone()[0] == 0

    seed_health()
    secret_changed = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={"secret_env": None},
    )
    assert secret_changed.status_code == 200
    assert secret_changed.json()["data"]["secret_env"] is None
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE source_id = ?", (source["id"],)
    ).fetchone()[0] == 0


def test_source_update_rolls_back_when_health_reset_fails(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "type": "rss",
            "display_name": "Atomic Feed",
            "config": {"url": "https://example.com/atomic-old.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        "/api/me/subscriptions", json={"source_id": source["id"]}
    ).json()["data"]
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    now = "2026-07-12T01:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO user_source_health (
            subscription_id, workspace_id, user_id, source_id, status,
            last_attempt_at, last_success_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'healthy', ?, ?, ?, ?)
        """,
        (
            subscription["id"],
            owner["workspace_id"],
            owner["id"],
            source["id"],
            now,
            now,
            now,
            now,
        ),
    )
    store.connect().execute(
        f"""
        CREATE TRIGGER block_health_reset
        BEFORE DELETE ON user_source_health
        WHEN OLD.source_id = '{source['id']}'
        BEGIN
            SELECT RAISE(ABORT, 'health reset blocked');
        END
        """
    )
    store.connect().commit()

    with pytest.raises(Exception, match="health reset blocked"):
        client.patch(
            f"/api/catalog/sources/{source['id']}",
            json={"config": {"url": "https://example.com/atomic-new.xml"}},
        )

    reloaded = store.get_source(source["id"])
    assert reloaded["config"]["url"] == "https://example.com/atomic-old.xml"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE source_id = ?", (source["id"],)
    ).fetchone()[0] == 1


def test_idempotent_source_post_resets_health_when_fetch_identity_changes(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    payload = {
        "type": "reddit_subreddit",
        "display_name": "Mutable Reddit Feed",
        "config": {"subreddit": "LocalLLaMA", "fetch_limit": 25},
        "secret_env": None,
    }
    source = client.post("/api/catalog/sources", json=payload).json()["data"]
    subscription = client.post(
        "/api/me/subscriptions", json={"source_id": source["id"]}
    ).json()["data"]
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    now = "2026-07-12T01:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO user_source_health (
            subscription_id, workspace_id, user_id, source_id, status,
            last_attempt_at, last_success_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'healthy', ?, ?, ?, ?)
        """,
        (
            subscription["id"],
            owner["workspace_id"],
            owner["id"],
            source["id"],
            now,
            now,
            now,
            now,
        ),
    )
    store.connect().commit()

    payload["config"]["fetch_limit"] = 50
    response = client.post("/api/catalog/sources", json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["id"] == source["id"]
    assert response.json()["data"]["config"]["fetch_limit"] == 50
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE source_id = ?", (source["id"],)
    ).fetchone()[0] == 0


def test_catalog_source_concurrent_post_is_idempotent_for_same_actor(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    barrier = threading.Barrier(4)

    def create(index):
        barrier.wait(timeout=5)
        return client.post(
            "/api/catalog/sources",
            json={
                "type": "rss",
                "display_name": f"Concurrent API Feed {index}",
                "config": {"url": "https://example.com/concurrent-api.xml"},
            },
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(create, range(4)))

    assert {response.status_code for response in responses} == {200}
    assert all(response.json()["ok"] is True for response in responses)
    assert len({response.json()["data"]["id"] for response in responses}) == 1


def test_private_source_key_collision_does_not_expose_or_take_over_another_member_source(
    tmp_path,
    monkeypatch,
):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    for username in ("alice", "bob"):
        created = client.post(
            "/api/users",
            json={"username": username, "password": f"{username}-password", "role": "member"},
        )
        assert created.status_code == 200
    client.post("/api/auth/logout")
    _login_as(client, "alice", "alice-password")
    alice_source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Alice Private Feed",
            "config": {"url": "https://example.com/member-private.xml"},
        },
    ).json()["data"]
    client.post("/api/auth/logout")
    _login_as(client, "bob", "bob-password")

    collision = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Bob Private Feed",
            "config": {"url": "https://example.com/member-private.xml"},
        },
    )

    assert collision.status_code == 409
    assert collision.json()["ok"] is False
    assert collision.json()["error"]["code"] == "source_key_conflict"
    assert alice_source["id"] not in collision.text
    bob_sources = client.get("/api/catalog/sources").json()["data"]["sources"]
    assert all(source["id"] != alice_source["id"] for source in bob_sources)


def test_admin_can_patch_user_role_enabled_display_name_and_password(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _login(client)
    created = client.post(
        "/api/users",
        json={
            "username": "member",
            "password": "member-password",
            "role": "member",
            "display_name": "Member",
        },
    ).json()["data"]

    patched = client.patch(
        f"/api/users/{created['id']}",
        json={
            "role": "viewer",
            "enabled": True,
            "display_name": "Renamed Member",
            "password": "new-member-password",
        },
    )
    assert patched.status_code == 200
    patched_data = patched.json()["data"]
    assert patched_data["role"] == "viewer"
    assert patched_data["display_name"] == "Renamed Member"
    assert patched_data["enabled"] is True
    assert "password_hash" not in patched_data

    invalid = client.patch(f"/api/users/{created['id']}", json={"role": "superadmin"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_role"

    client.post("/api/auth/logout")
    old_login = client.post(
        "/api/auth/login",
        json={"username": "member", "password": "member-password"},
    )
    assert old_login.status_code == 401
    assert old_login.json()["error"]["code"] == "invalid_credentials"
    assert client.post(
        "/api/auth/login",
        json={"username": "member", "password": "new-member-password"},
    ).status_code == 200

    client.post("/api/auth/logout")
    _login(client)
    unchanged = client.patch(
        f"/api/users/{created['id']}",
        json={"password": "", "role": "member"},
    )
    assert unchanged.status_code == 200
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login",
        json={"username": "member", "password": "new-member-password"},
    ).status_code == 200


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


def test_subscription_creation_enforces_enabled_source_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("INFOHUB_MAX_SOURCES_PER_USER", "1")
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    sources = [
        client.post(
            "/api/catalog/sources",
            json={
                "scope": "public",
                "type": "rss",
                "display_name": f"Quota Feed {index}",
                "config": {"url": f"https://example.com/quota-{index}.xml"},
            },
        ).json()["data"]
        for index in range(2)
    ]

    first = client.post(f"/api/catalog/sources/{sources[0]['id']}/subscribe")
    rejected = client.post(f"/api/catalog/sources/{sources[1]['id']}/subscribe")

    assert first.status_code == 200
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "quota_exceeded"
    assert len(client.get("/api/me/subscriptions").json()["data"]["subscriptions"]) == 1
    runtime = client.get("/api/ops/runtime").json()["data"]
    assert runtime["operational_counts"]["quota_rejects"] == 1


def test_disabled_source_subscription_enable_is_quota_neutral_but_source_reenable_is_admitted(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("INFOHUB_MAX_SOURCES_PER_USER", "1")
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)

    def create_source(name, suffix):
        return client.post(
            "/api/catalog/sources",
            json={
                "scope": "public",
                "type": "rss",
                "display_name": name,
                "config": {"url": f"https://example.com/{suffix}.xml"},
            },
        ).json()["data"]

    disabled_source = create_source("Disabled target", "quota-disabled-target")
    disabled_subscription = client.post(
        f"/api/catalog/sources/{disabled_source['id']}/subscribe"
    ).json()["data"]["subscription"]
    assert client.patch(
        f"/api/catalog/sources/{disabled_source['id']}",
        json={"enabled": False},
    ).status_code == 200
    assert client.patch(
        f"/api/me/subscriptions/{disabled_subscription['id']}",
        json={"enabled": False},
    ).status_code == 200

    active_source = create_source("Active target", "quota-active-target")
    assert client.post(
        f"/api/catalog/sources/{active_source['id']}/subscribe"
    ).status_code == 200

    quota_neutral_enable = client.patch(
        f"/api/me/subscriptions/{disabled_subscription['id']}",
        json={"enabled": True},
    )
    rejected_reenable = client.patch(
        f"/api/catalog/sources/{disabled_source['id']}",
        json={"enabled": True},
    )

    assert quota_neutral_enable.status_code == 200
    assert quota_neutral_enable.json()["data"]["enabled"] is True
    assert rejected_reenable.status_code == 429
    assert rejected_reenable.json()["error"]["code"] == "quota_exceeded"
    store = ServiceStore(data_dir)
    store.initialize()
    assert store.get_source(disabled_source["id"])["enabled"] is False


def test_concurrent_subscription_creation_enforces_quota_atomically(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("INFOHUB_MAX_SOURCES_PER_USER", "1")
    original_ensure = QuotaService.ensure_source_allowed

    def slow_ensure(self, **kwargs):
        original_ensure(self, **kwargs)
        time.sleep(0.1)

    monkeypatch.setattr(QuotaService, "ensure_source_allowed", slow_ensure)
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    sources = [
        client.post(
            "/api/catalog/sources",
            json={
                "scope": "public",
                "type": "rss",
                "display_name": f"Concurrent Quota Feed {index}",
                "config": {"url": f"https://example.com/concurrent-quota-{index}.xml"},
            },
        ).json()["data"]
        for index in range(2)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda source: client.post(
                    f"/api/catalog/sources/{source['id']}/subscribe"
                ),
                sources,
            )
        )

    assert sorted(response.status_code for response in responses) == [200, 429]
    assert len(client.get("/api/me/subscriptions").json()["data"]["subscriptions"]) == 1


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


def test_catalog_import_skips_member_private_source_key_collision(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    config = _minimal_config()
    config["sources"]["rss"] = [
        {
            "name": "Global Import Candidate",
            "url": "https://example.com/private-collision.xml",
            "topics": ["Global Topic"],
        }
    ]
    _write_config(data_dir, config)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )
    client.post("/api/auth/logout")
    _login_as(client, "member", "member-password")
    private_source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Member Private Source",
            "config": {"url": "https://example.com/private-collision.xml"},
        },
    ).json()["data"]
    client.post("/api/auth/logout")
    _login(client)

    imported = client.post("/api/catalog/import-config-sources", json={})

    assert imported.status_code == 200
    result = imported.json()["data"]
    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["skipped"] == 1
    assert result["errors"][0]["code"] == "source_key_conflict"
    store = ServiceStore(data_dir)
    store.initialize()
    preserved = store.get_source(private_source["id"])
    assert preserved["scope"] == "private"
    assert preserved["display_name"] == "Member Private Source"
    assert preserved["secret_env"] is None
    assert preserved["config"]["url"] == "https://example.com/private-collision.xml"


def test_admin_can_list_and_reenable_disabled_source_but_members_cannot_expand_visibility(
    tmp_path, monkeypatch
):
    client, _data_dir = _client(tmp_path, monkeypatch)
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
            "display_name": "Recoverable Feed",
            "config": {"url": "https://example.com/recoverable.xml"},
        },
    ).json()["data"]

    disabled = client.patch(
        f"/api/catalog/sources/{source['id']}", json={"enabled": False}
    )

    assert disabled.status_code == 200
    assert client.get("/api/catalog/sources").json()["data"]["sources"] == []
    manager_sources = client.get(
        "/api/catalog/sources?include_disabled=true"
    ).json()["data"]["sources"]
    assert [(item["id"], item["enabled"]) for item in manager_sources] == [
        (source["id"], False)
    ]
    reenabled = client.patch(
        f"/api/catalog/sources/{source['id']}", json={"enabled": True}
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["data"]["enabled"] is True

    client.post("/api/auth/logout")
    _login_as(client, "member", "member-password")
    forbidden = client.get("/api/catalog/sources?include_disabled=true")
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
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    job = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]

    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"

    retried = client.post(f"/api/jobs/{job['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "queued"
    assert retried.json()["data"]["attempts"] == 0
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM usage_events
        WHERE user_id = ? AND event_type = 'user_feed_refresh'
        """,
        (owner["id"],),
    ).fetchone()
    assert int(usage["total"]) == 2


def test_job_retry_rolls_back_requeue_when_usage_write_fails(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    job = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]
    client.post(f"/api/jobs/{job['id']}/cancel")

    def fail_usage(*_args, **_kwargs):
        raise RuntimeError("forced usage write failure")

    monkeypatch.setattr(QuotaService, "record_job_usage", fail_usage)
    with pytest.raises(RuntimeError, match="forced usage write failure"):
        client.post(f"/api/jobs/{job['id']}/retry")

    store = ServiceStore(data_dir)
    store.initialize()
    assert JobQueue(store).get_job(job["id"])["status"] == "cancelled"


def test_job_retry_rejects_currently_ineligible_source_without_charging(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Retry Eligibility Feed",
            "config": {"url": "https://example.com/retry-eligibility.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    job = client.post(
        "/api/jobs/source-fetch",
        json={
            "source_id": source["id"],
            "subscription_id": subscription["id"],
        },
    ).json()["data"]
    store = ServiceStore(data_dir)
    store.initialize()
    store.connect().execute(
        "UPDATE fetch_jobs SET status = 'failed' WHERE id = ?",
        (job["id"],),
    )
    store.connect().commit()
    client.delete(f"/api/catalog/sources/{source['id']}")

    response = client.post(f"/api/jobs/{job['id']}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_retryable"
    assert JobQueue(store).get_job(job["id"])["status"] == "failed"
    usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM usage_events
        WHERE event_type = 'source_fetch'
        """
    ).fetchone()
    assert int(usage["total"]) == 1


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
        payload={
            "items": [{"id": "rss:item:summary:1"}, {"id": "rss:item:summary:2"}],
            "generated_at": "2026-07-09T00:00:00+08:00",
        },
    )
    item_states = UserItemStateStore(store)
    item_states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:summary:1",
        is_read=True,
        is_saved=True,
        is_later=True,
    )
    item_states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:summary:2",
        dismissed=True,
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
    assert data["item_state_counts"] == {
        "read_count": 1,
        "saved_count": 1,
        "later_count": 1,
        "dismissed_count": 1,
    }
    assert data["current_user"]["username"] == "owner"
    assert "password_hash" not in data["current_user"]


def test_health_runtime_and_job_api_never_expose_claim_token(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_REQUIRE_WORKER_FOR_READINESS", "true")
    client, data_dir = _client(tmp_path, monkeypatch)

    live = client.get("/api/health/live")
    assert live.status_code == 200
    assert live.json()["data"]["status"] == "live"

    missing = client.get("/api/health/ready")
    assert missing.status_code == 503
    assert missing.json()["error"]["code"] == "worker_unavailable"

    store = ServiceStore(data_dir)
    store.initialize()
    store.upsert_worker_heartbeat("worker-ready", "idle")
    ready = client.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json()["data"]["worker_status"] == "ready"

    _login(client)
    created = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]
    claimed = JobQueue(store).claim_next_job(worker_id="worker-ready")
    assert claimed["id"] == created["id"]
    assert claimed["claim_token"]

    returned = client.get(f"/api/jobs/{created['id']}").json()["data"]
    listed = client.get("/api/jobs").json()["data"]["jobs"]
    runtime = client.get("/api/ops/runtime")

    assert "claim_token" not in returned
    assert all("claim_token" not in job for job in listed)
    assert runtime.status_code == 200
    assert runtime.json()["data"]["job_counts"]["running"] == 1
    assert runtime.json()["data"]["worker_status"] == "ready"


def test_ops_runtime_aggregates_only_safe_acquisition_and_invalidation_counts(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    queue = JobQueue(store)
    acquisition_job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )
    invalidated_job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_fetch",
        payload={},
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'succeeded', result_json = ?
        WHERE id = ?
        """,
        (
            json.dumps(
                {
                    "acquisition_usage": {
                        "cache_hits": 2,
                        "cache_misses": 1,
                        "upstream_attempts": 1,
                        "waits": 3,
                    },
                    "source_id": "must-not-be-projected",
                }
            ),
            acquisition_job["id"],
        ),
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'cancelled', error_code = 'job_invalidated'
        WHERE id = ?
        """,
        (invalidated_job["id"],),
    )
    store.connect().commit()

    response = client.get("/api/ops/runtime")

    assert response.status_code == 200
    assert response.json()["data"]["operational_counts"] == {
        "acquisition_cache_hits": 2,
        "acquisition_cache_misses": 1,
        "acquisition_upstream_attempts": 1,
        "acquisition_waits": 3,
        "invalidated_jobs": 1,
        "quota_rejects": 0,
    }


def test_liveness_exposes_release_identity_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("INTELISCOPE_VERSION", "1.5.0-rc1")
    monkeypatch.setenv("INTELISCOPE_BUILD_REVISION", "abc123def456")
    monkeypatch.setenv("INTELISCOPE_BUILT_AT", "2026-07-12T04:00:00Z")
    client, _ = _client(tmp_path, monkeypatch)

    response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "live",
        "version": "1.5.0-rc1",
        "revision": "abc123def456",
        "built_at": "2026-07-12T04:00:00Z",
    }


def test_service_login_honors_secure_cookie_and_session_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_SECURE_COOKIE", "true")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_TTL_SECONDS", "900")
    client, data_dir = _client(tmp_path, monkeypatch)

    response = client.post(
        "https://testserver/api/auth/login",
        json={"username": "owner", "password": "secret-password"},
    )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "Max-Age=900" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie

    store = ServiceStore(data_dir)
    store.initialize()
    row = store.connect().execute(
        "SELECT created_at, expires_at FROM sessions ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    created_at = datetime.fromisoformat(row["created_at"])
    expires_at = datetime.fromisoformat(row["expires_at"])
    assert 895 <= (expires_at - created_at).total_seconds() <= 905

    logout = client.post("https://testserver/api/auth/logout")
    assert logout.status_code == 200
    assert "Secure" in logout.headers["set-cookie"]


def test_readiness_requires_an_enabled_user_but_liveness_stays_live(tmp_path, monkeypatch):
    monkeypatch.delenv("HORIZON_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("HORIZON_AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("HORIZON_REQUIRE_WORKER_FOR_READINESS", "false")
    data_dir = tmp_path / "fresh-data"
    static_dir = tmp_path / "fresh-static"
    (data_dir / "site").mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))

    live = client.get("/api/health/live")
    ready = client.get("/api/health/ready")

    assert live.status_code == 200
    assert live.json() == {
        "ok": True,
        "data": {
            "status": "live",
            "version": "1.5.0",
            "revision": "unknown",
            "built_at": "unknown",
        },
    }
    assert ready.status_code == 503
    assert ready.json()["ok"] is False
    assert ready.json()["error"]["code"] == "auth_not_configured"
    assert "HORIZON_AUTH_PASSWORD" in ready.json()["error"]["action"]
    assert "HORIZON_AUTH_PASSWORD_HASH" in ready.json()["error"]["action"]


def test_readiness_uses_persisted_enabled_user_after_bootstrap_env_is_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.delenv("HORIZON_AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("HORIZON_REQUIRE_WORKER_FOR_READINESS", "false")
    data_dir = tmp_path / "configured-data"
    static_dir = tmp_path / "configured-static"
    (data_dir / "site").mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")

    configured = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    assert configured.get("/api/health/ready").status_code == 200

    monkeypatch.delenv("HORIZON_AUTH_PASSWORD")
    restarted = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))

    ready = restarted.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"


def test_api_jobs_feed_and_archive_facades(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)

    latest_payload = {"items": [{"id": "rss:item:archive", "channel": "AI"}], "generated_at": "now"}
    graph_payload = {"nodes": [{"id": "global-article"}], "edges": []}
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
        "generated_at": "now",
        "schema_version": 2,
        "snapshots": [
            {
                "snapshot_id": snapshot["id"],
                "generated_at": "now",
                "item_count": 1,
                "job_id": "job_latest",
            }
        ],
        "scope": "user",
        "items": [],
        "featured_items": [],
        "item_count": 0,
        "sources": [],
        "channels": [],
        "categories": [],
        "tags": [],
        "topics": [],
        "personal_tags": [],
    }
    assert client.get("/api/archive/graph").json()["data"] == SAFE_DISABLED_GRAPH

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


def test_archive_graph_never_reads_global_graph_for_authenticated_users(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    for username, role in (("admin", "admin"), ("member", "member"), ("viewer", "viewer")):
        created = client.post(
            "/api/users",
            json={"username": username, "password": f"{username}-password", "role": role},
        )
        assert created.status_code == 200
    (data_dir / "site" / "article-graph.json").write_text(
        json.dumps({"nodes": [{"id": "global-secret"}], "edges": [{"source": "global-secret"}]}),
        encoding="utf-8",
    )

    site_reads = []
    original_read_site_json = FeedArchiveService._read_site_json

    def track_site_reads(service, name, fallback):
        site_reads.append(name)
        return original_read_site_json(service, name, fallback)

    monkeypatch.setattr(FeedArchiveService, "_read_site_json", track_site_reads)
    responses = [client.get("/api/archive/graph")]
    client.post("/api/auth/logout")
    for username in ("admin", "member", "viewer"):
        _login_as(client, username, f"{username}-password")
        responses.append(client.get("/api/archive/graph"))
        client.post("/api/auth/logout")

    assert "article-graph.json" not in site_reads
    for response in responses:
        assert response.status_code == 200
        assert response.json() == {"ok": True, "data": SAFE_DISABLED_GRAPH}


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
    assert history.json()["data"] == {
        "schema_version": 2,
        "scope": "user",
        "snapshots": [],
        "items": [],
        "featured_items": [],
        "item_count": 0,
    }


def test_feed_history_is_user_isolated_and_admin_can_query_member(tmp_path, monkeypatch):
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
    feeds = UserFeedStore(store)
    for user, prefix in ((owner, "owner"), (member, "member")):
        feeds.save_snapshot(
            workspace_id=workspace["id"],
            user_id=user["id"],
            job_id=f"job_{prefix}_old",
            payload={
                "generated_at": "2026-07-09T10:00:00+08:00",
                "items": [{"id": f"rss:item:{prefix}:history"}],
            },
        )
        feeds.save_snapshot(
            workspace_id=workspace["id"],
            user_id=user["id"],
            job_id=f"job_{prefix}_current",
            payload={
                "generated_at": "2026-07-10T10:00:00+08:00",
                "items": [{"id": f"rss:item:{prefix}:current"}],
            },
        )

    admin_view = client.get(f"/api/feed/latest?user_id={member['id']}")
    admin_history = client.get(f"/api/feed/history?user_id={member['id']}")
    client.post("/api/auth/logout")
    _login_as(client, "member", "member-password")
    member_history = client.get("/api/feed/history")
    forbidden = client.get(f"/api/feed/history?user_id={owner['id']}")

    assert admin_view.status_code == 200
    assert admin_view.json()["data"]["items"][0]["id"] == "rss:item:member:current"
    assert admin_view.json()["data"]["scope"] == "user"
    assert admin_history.status_code == 200
    assert [item["id"] for item in admin_history.json()["data"]["items"]] == [
        "rss:item:member:history"
    ]
    assert member_history.status_code == 200
    assert [item["id"] for item in member_history.json()["data"]["items"]] == [
        "rss:item:member:history"
    ]
    assert all(
        "owner" not in item["id"]
        for item in member_history.json()["data"]["items"]
    )
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


def test_feed_latest_applies_current_user_state_filters_and_sorting(tmp_path, monkeypatch):
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
    payload = {
        "schema_version": 2,
        "generated_at": "2026-07-09T12:30:00+08:00",
        "items": [
            {"id": "rss:item:read", "title": "Read item"},
            {"id": "rss:item:dismissed", "title": "Dismissed item"},
            {"id": "rss:item:saved", "title": "Saved item"},
            {"id": "rss:item:plain", "title": "Plain item"},
        ],
    }
    payload["today_items"] = list(payload["items"])
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_owner",
        payload=payload,
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_id="job_member",
        payload=payload,
    )
    states = UserItemStateStore(store)
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:read",
        is_read=True,
    )
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:dismissed",
        dismissed=True,
    )
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:saved",
        is_saved=True,
    )

    default_feed = client.get("/api/feed/latest").json()["data"]
    hidden_feed = client.get("/api/feed/latest?hide_dismissed=true").json()["data"]
    default_ids = [item["id"] for item in default_feed["items"]]
    hidden_ids = [item["id"] for item in hidden_feed["items"]]
    unread_ids = [item["id"] for item in client.get("/api/feed/latest?unread_first=true").json()["data"]["items"]]
    saved_ids = [item["id"] for item in client.get("/api/feed/latest?saved_first=true").json()["data"]["items"]]
    member_ids = [
        item["id"]
        for item in client.get(f"/api/feed/latest?user_id={member['id']}&hide_dismissed=true").json()["data"]["items"]
    ]

    assert default_ids == ["rss:item:read", "rss:item:dismissed", "rss:item:saved", "rss:item:plain"]
    assert hidden_ids == ["rss:item:read", "rss:item:saved", "rss:item:plain"]
    assert unread_ids == ["rss:item:dismissed", "rss:item:saved", "rss:item:plain", "rss:item:read"]
    assert saved_ids == ["rss:item:saved", "rss:item:read", "rss:item:dismissed", "rss:item:plain"]
    assert member_ids == ["rss:item:read", "rss:item:dismissed", "rss:item:saved", "rss:item:plain"]
    assert default_feed["today_items"] == default_feed["items"]
    assert hidden_feed["today_items"] == hidden_feed["items"]


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


def test_saved_feed_and_item_detail_survive_later_snapshots_and_are_user_isolated(
    tmp_path, monkeypatch
):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    owner = store.get_user_by_username("owner")
    workspace_id = owner["workspace_id"]
    store.create_user(
        workspace_id=workspace_id,
        username="saved-member",
        password="member-password",
        role="member",
    )
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=workspace_id,
        user_id=owner["id"],
        job_id="job_saved_original",
        payload={
            "generated_at": "2026-07-14T01:00:00+00:00",
            "items": [
                {
                    "id": "rss:saved:stable",
                    "title": "Stable saved item",
                    "summary_zh": "Stable summary",
                    "presentation": {
                        "version": 1,
                        "content": {
                            "excerpt": "Old snapshot excerpt",
                            "excerpt_truncated": True,
                        },
                    },
                }
            ],
        },
    )
    UserItemStateStore(store).update_state(
        workspace_id=workspace_id,
        user_id=owner["id"],
        article_id="rss:saved:stable",
        is_saved=True,
    )
    feeds.save_snapshot(
        workspace_id=workspace_id,
        user_id=owner["id"],
        job_id="job_saved_replaced",
        payload={
            "generated_at": "2026-07-14T02:00:00+00:00",
            "items": [],
        },
    )

    saved = client.get("/api/feed/saved?limit=200&offset=0")
    detail = client.get("/api/feed/items/rss:saved:stable")

    assert saved.status_code == 200
    assert saved.json()["data"]["item_count"] == 1
    assert saved.json()["data"]["items"][0]["id"] == "rss:saved:stable"
    assert saved.json()["data"]["items"][0]["user_state"]["is_saved"] is True
    assert detail.status_code == 200
    presentation = detail.json()["data"]["presentation"]
    assert presentation["version"] == 2
    assert presentation["source"]["avatar_url"] == ""
    assert presentation["content"]["body_text"] == "Old snapshot excerpt"
    assert presentation["content"]["body_truncated"] is True
    assert presentation["content"]["body_completeness"] == "excerpt_only"
    assert presentation["media"] == {
        "images": [],
        "count": 0,
        "total_image_count": 0,
        "truncated": False,
    }

    _login_as(client, "saved-member", "member-password")
    assert client.get("/api/feed/saved").json()["data"]["items"] == []
    hidden = client.get("/api/feed/items/rss:saved:stable")
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "not_found"


def test_saved_feed_orders_by_saved_time_and_supports_pagination(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    owner = store.get_user_by_username("owner")
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        job_id="job_saved_order",
        payload={
            "generated_at": "2026-07-14T01:00:00+00:00",
            "items": [
                {"id": "rss:saved:first", "title": "First"},
                {"id": "rss:saved:second", "title": "Second"},
            ],
        },
    )
    states = UserItemStateStore(store)
    for article_id, saved_at in [
        ("rss:saved:first", "2026-07-14T01:00:00+00:00"),
        ("rss:saved:second", "2026-07-14T02:00:00+00:00"),
    ]:
        states.update_state(
            workspace_id=owner["workspace_id"],
            user_id=owner["id"],
            article_id=article_id,
            is_saved=True,
        )
        store.connect().execute(
            "UPDATE user_item_state SET saved_at = ? WHERE user_id = ? AND article_id = ?",
            (saved_at, owner["id"], article_id),
        )
    store.connect().commit()

    page = client.get("/api/feed/saved?limit=1&offset=1").json()["data"]

    assert page["item_count"] == 2
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert [item["id"] for item in page["items"]] == ["rss:saved:first"]


def test_media_api_and_catalog_avatar_enforce_user_and_source_scope(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=owner["workspace_id"],
        username="media-member",
        password="member-password",
        role="member",
    )
    workspace_source_id = store.create_source(
        workspace_id=owner["workspace_id"],
        scope="workspace",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Avatar source",
        config={"url": "https://example.com/avatar.xml"},
    )
    private_source_id = store.create_source(
        workspace_id=owner["workspace_id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Private avatar source",
        config={"url": "https://example.com/private-avatar.xml"},
    )
    media_dir = data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "workspace.png").write_bytes(b"\x89PNG\r\n\x1a\nworkspace")
    (media_dir / "private.png").write_bytes(b"\x89PNG\r\n\x1a\nprivate")
    (media_dir / "content.png").write_bytes(b"\x89PNG\r\n\x1a\ncontent")
    now = "2026-07-14T05:00:00+00:00"
    for values in [
        (
            "med_workspace",
            None,
            workspace_source_id,
            None,
            "source_avatar",
            "media/workspace.png",
            "workspace",
        ),
        (
            "med_private",
            None,
            private_source_id,
            None,
            "source_avatar",
            "media/private.png",
            "private",
        ),
        (
            "med_content",
            owner["id"],
            workspace_source_id,
            "rss:media:owner",
            "content_image",
            "media/content.png",
            "private",
        ),
    ]:
        store.connect().execute(
            """
            INSERT INTO media_assets (
                id, workspace_id, user_id, source_id, article_id,
                asset_kind, local_path, mime_type, byte_size, checksum,
                visibility_scope, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'image/png', 16, ?, ?, 'ready', ?, ?)
            """,
            (
                values[0],
                owner["workspace_id"],
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[0],
                values[6],
                now,
                now,
            ),
        )
    store.connect().commit()

    sources = client.get("/api/catalog/sources").json()["data"]["sources"]
    workspace_source = next(item for item in sources if item["id"] == workspace_source_id)
    assert workspace_source["avatar_url"] == "/api/media/med_workspace"
    assert client.get("/api/media/med_workspace").status_code == 200
    assert client.get("/api/media/med_content").status_code == 200

    _login_as(client, "media-member", "member-password")
    assert client.get("/api/media/med_workspace").status_code == 200
    assert client.get("/api/media/med_private").status_code == 404
    assert client.get("/api/media/med_content").status_code == 404


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
    assert data["taxonomy"]["channels"] == [
        "AI",
        "投资",
        "产品机会",
        "工作/项目",
        "朋友动态",
        "生活",
        "政策/风险",
        "其他",
    ]
    assert data["taxonomy"]["topics"] == data["config"]["tags"]
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


def test_api_config_projects_reddit_user_catalog_sources(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "reddit_user",
            "display_name": "Reddit User",
            "config": {"username": "spez", "sort": "new", "fetch_limit": 5},
        },
    ).json()["data"]
    client.post(f"/api/catalog/sources/{source['id']}/subscribe")

    config = client.get("/api/config").json()["data"]["config"]

    users = config["sources"]["reddit"]["users"]
    assert len(users) == 1
    assert users[0]["username"] == "spez"
    assert users[0]["source_id"] == source["id"]


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


def test_member_source_action_keeps_topics_user_scoped_and_conflicts_are_structured(
    tmp_path,
    monkeypatch,
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _write_config(data_dir)
    _login(client)
    for username in ("alice", "bob"):
        client.post(
            "/api/users",
            json={"username": username, "password": f"{username}-password", "role": "member"},
        )
    baseline = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))

    client.post("/api/auth/logout")
    _login_as(client, "alice", "alice-password")
    created = client.post(
        "/api/config/action",
        json={
            "action": "upsert_rss",
            "payload": {
                "name": "Alice Feed",
                "url": "https://example.com/member-action-collision.xml",
                "topics": "Alice Scoped Topic",
                "personal_tags": "Alice Scoped Personal",
                "enabled": True,
            },
        },
    )
    assert created.status_code == 200
    after_alice = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert after_alice["tags"] == baseline["tags"]
    assert after_alice["personal_tags"] == baseline["personal_tags"]
    alice_subscription = client.get("/api/me/subscriptions").json()["data"]["subscriptions"][0]
    assert alice_subscription["personal_tags"] == ["Alice Scoped Personal"]

    client.post("/api/auth/logout")
    _login_as(client, "bob", "bob-password")
    conflict = client.post(
        "/api/config/action",
        json={
            "action": "upsert_rss",
            "payload": {
                "name": "Bob Feed",
                "url": "https://example.com/member-action-collision.xml",
                "topics": "Bob Global Injection",
                "personal_tags": "Bob Personal Injection",
                "enabled": True,
            },
        },
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "source_key_conflict"
    after_conflict = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert after_conflict["tags"] == baseline["tags"]
    assert after_conflict["personal_tags"] == baseline["personal_tags"]


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


def test_member_cannot_queue_an_unscoped_source_payload(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "member", "password": "member-password", "role": "member"},
    )
    client.post("/api/auth/logout")
    _login_as(client, "member", "member-password")

    response = client.post(
        "/api/jobs/source-test",
        json={
            "payload": {
                "source_type": "rss",
                "url": "http://127.0.0.1:8080/private",
            }
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_notification_settings_are_write_only_and_user_scoped(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={
            "username": "notification-member",
            "password": "member-password",
            "role": "member",
        },
    )
    _seed_ready_workspace_email_transport(data_dir)
    webhook_url = "https://hooks.example.com/services/owner?token=owner-private"
    email_address = "notification-member@example.com"
    projection_keys = {
        "schema_version",
        "enabled",
        "channel",
        "email_configured",
        "email_transport_ready",
        "webhook_configured",
        "last_test_status",
        "last_tested_at",
        "last_test_error_code",
        "updated_at",
    }

    default_response = client.get("/api/me/notification-settings")
    default_data = _assert_notification_destination_is_write_only(default_response)
    assert set(default_data) == projection_keys
    assert default_data["schema_version"] == 1
    assert default_data["enabled"] is False
    assert default_data["email_configured"] is False
    assert default_data["email_transport_ready"] is True
    assert default_data["webhook_configured"] is False

    owner_update = client.patch(
        "/api/me/notification-settings",
        json={
            "enabled": True,
            "channel": "webhook",
            "webhook_url": webhook_url,
        },
    )
    owner_data = _assert_notification_destination_is_write_only(
        owner_update,
        webhook_url,
        "owner-private",
    )
    assert set(owner_data) == projection_keys
    assert owner_data["enabled"] is True
    assert owner_data["channel"] == "webhook"
    assert owner_data["webhook_configured"] is True
    assert owner_data["email_configured"] is False

    owner_read = _assert_notification_destination_is_write_only(
        client.get("/api/me/notification-settings"),
        webhook_url,
        "owner-private",
    )
    assert owner_read == owner_data

    client.post("/api/auth/logout")
    _login_as(client, "notification-member", "member-password")
    member_default = _assert_notification_destination_is_write_only(
        client.get("/api/me/notification-settings"),
        webhook_url,
        email_address,
    )
    assert member_default["enabled"] is False
    assert member_default["email_configured"] is False
    assert member_default["webhook_configured"] is False

    member_update = client.patch(
        "/api/me/notification-settings",
        json={
            "enabled": True,
            "channel": "email",
            "email_address": email_address,
        },
    )
    member_data = _assert_notification_destination_is_write_only(
        member_update,
        webhook_url,
        email_address,
    )
    assert member_data["enabled"] is True
    assert member_data["channel"] == "email"
    assert member_data["email_configured"] is True
    assert member_data["webhook_configured"] is False

    client.post("/api/auth/logout")
    _login(client)
    owner_after_member_update = _assert_notification_destination_is_write_only(
        client.get("/api/me/notification-settings"),
        webhook_url,
        email_address,
    )
    assert owner_after_member_update == owner_data


def test_admin_email_transport_requires_test_and_never_returns_secret(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={
            "username": "email-member",
            "password": "member-password",
            "role": "member",
        },
    )
    unavailable = client.patch(
        "/api/me/notification-settings",
        json={
            "enabled": True,
            "channel": "email",
            "email_address": "owner@example.com",
        },
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == (
        "notification_channel_unavailable"
    )

    default = client.get(
        "/api/admin/notification-email-transport"
    )
    assert default.status_code == 200
    default_data = default.json()["data"]
    assert default_data["configured"] is False
    assert default_data["ready"] is False
    assert [
        provider["provider"] for provider in default_data["providers"]
    ] == ["qq", "netease", "gmail", "resend", "amazon_ses"]

    client.post("/api/auth/logout")
    _login_as(client, "email-member", "member-password")
    assert client.get(
        "/api/admin/notification-email-transport"
    ).status_code == 403
    assert client.patch(
        "/api/admin/notification-email-transport",
        json={"enabled": False},
    ).status_code == 403
    client.post("/api/auth/logout")
    _login(client)

    credential = "test-only-qq-authorization-code"
    rejected_host = client.patch(
        "/api/admin/notification-email-transport",
        json={
            "provider": "qq",
            "sender_email": "notice@qq.com",
            "sender_name": "InfoHub",
            "credential": credential,
            "smtp_host": "127.0.0.1",
        },
    )
    assert rejected_host.status_code == 400

    saved = client.patch(
        "/api/admin/notification-email-transport",
        json={
            "provider": "qq",
            "sender_email": "notice@qq.com",
            "sender_name": "InfoHub",
            "credential": credential,
            "enabled": True,
        },
    )
    assert saved.status_code == 200
    saved_payload = saved.json()
    saved_data = saved_payload["data"]
    assert saved_data["enabled"] is False
    assert saved_data["can_enable"] is False
    assert saved_data["credential_configured"] is True
    assert saved_data["connection"]["smtp_host"] == "smtp.qq.com"
    assert credential not in json.dumps(saved_payload)
    assert credential.encode() not in (data_dir / "service.db").read_bytes()

    premature_enable = client.patch(
        "/api/admin/notification-email-transport",
        json={"enabled": True},
    )
    assert premature_enable.status_code == 409
    assert premature_enable.json()["error"]["code"] == (
        "email_transport_test_required"
    )

    sent_messages = []

    class FakeSMTP:
        def __init__(
            self,
            host,
            port,
            *,
            timeout,
            context,
        ):
            assert (host, port, timeout) == ("smtp.qq.com", 465, 20)
            assert context is not None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def login(self, username, password):
            assert username == "notice@qq.com"
            assert password == credential

        def send_message(self, message):
            sent_messages.append(message)

    client.app.state.workspace_email_transport.smtp_factory = FakeSMTP
    client.app.state.workspace_email_transport.ssl_context_factory = (
        lambda: object()
    )
    recipient = "test-recipient@example.com"
    tested = client.post(
        "/api/admin/notification-email-transport/test",
        json={"recipient_email": recipient},
    )
    assert tested.status_code == 200
    assert tested.json()["data"]["sent"] is True
    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == recipient
    assert recipient.encode() not in (data_dir / "service.db").read_bytes()

    enabled = client.patch(
        "/api/admin/notification-email-transport",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["data"]["ready"] is True
    me = client.get("/api/me/notification-settings")
    assert me.status_code == 200
    assert me.json()["data"]["email_transport_ready"] is True

    deleted = client.delete(
        "/api/admin/notification-email-transport"
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
    assert client.get(
        "/api/me/notification-settings"
    ).json()["data"]["email_transport_ready"] is False


def test_notification_test_push_does_not_create_delivery_snapshot_or_job(
    tmp_path, monkeypatch
):
    from src.services.preferred_source_notifications import (
        PreferredSourceNotificationService,
    )

    calls = []

    def fake_send_test(self, *, workspace_id, user_id):
        calls.append(
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
            }
        )
        return {"sent": True, "channel": "webhook"}

    monkeypatch.setattr(
        PreferredSourceNotificationService,
        "send_test",
        fake_send_test,
    )
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    webhook_url = "https://hooks.example.com/services/test?token=test-private"
    configured = client.patch(
        "/api/me/notification-settings",
        json={
            "enabled": True,
            "channel": "webhook",
            "webhook_url": webhook_url,
        },
    )
    assert configured.status_code == 200

    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")

    def counts() -> tuple[int, int, int]:
        connection = store.connect()
        return (
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM preferred_source_notification_deliveries"
                ).fetchone()[0]
            ),
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM user_feed_snapshots"
                ).fetchone()[0]
            ),
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM fetch_jobs"
                ).fetchone()[0]
            ),
        )

    before = counts()
    tested = client.post("/api/me/notification-settings/test")

    assert tested.status_code == 200
    tested_data = tested.json()["data"]
    assert tested_data == {"sent": True, "channel": "webhook"}
    assert calls == [
        {
            "workspace_id": owner["workspace_id"],
            "user_id": owner["id"],
        }
    ]
    assert counts() == before == (0, 0, 0)
    settings = _assert_notification_destination_is_write_only(
        client.get("/api/me/notification-settings"),
        webhook_url,
        "test-private",
    )
    assert set(settings) == {
        "schema_version",
        "enabled",
        "channel",
        "email_configured",
        "email_transport_ready",
        "webhook_configured",
        "last_test_status",
        "last_tested_at",
        "last_test_error_code",
        "updated_at",
    }


def test_subscription_notification_preference_is_isolated_per_user(
    tmp_path, monkeypatch
):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={
            "username": "notification-peer",
            "password": "peer-password",
            "role": "member",
        },
    )
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "public",
            "type": "rss",
            "display_name": "Shared Notification Feed",
            "config": {"url": "https://example.com/shared-notification.xml"},
        },
    ).json()["data"]
    owner_subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    owner_enabled = client.patch(
        f"/api/me/subscriptions/{owner_subscription['id']}",
        json={"notify_on_new_items": True},
    )
    assert owner_enabled.status_code == 200
    assert owner_enabled.json()["data"]["notify_on_new_items"] is True

    client.post("/api/auth/logout")
    _login_as(client, "notification-peer", "peer-password")
    peer_subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    assert peer_subscription["id"] != owner_subscription["id"]
    assert peer_subscription["notify_on_new_items"] is False
    assert peer_subscription["notification_enabled_at"] is None

    peer_list = client.get("/api/me/subscriptions").json()["data"]["subscriptions"]
    assert [item["id"] for item in peer_list] == [peer_subscription["id"]]
    assert peer_list[0]["notify_on_new_items"] is False

    other_user_patch = client.patch(
        f"/api/me/subscriptions/{owner_subscription['id']}",
        json={"notify_on_new_items": False},
    )
    assert other_user_patch.status_code == 404

    client.post("/api/auth/logout")
    _login(client)
    owner_list = client.get("/api/me/subscriptions").json()["data"]["subscriptions"]
    owner_projection = next(
        item for item in owner_list if item["id"] == owner_subscription["id"]
    )
    assert owner_projection["notify_on_new_items"] is True
    assert owner_projection["notification_enabled_at"] is not None


def test_feed_schedule_get_defaults_and_patch_round_trip(tmp_path, monkeypatch):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)

    default_response = client.get("/api/me/feed-schedule")
    assert default_response.status_code == 200
    default_data = default_response.json()["data"]
    assert default_data == {
        "schema_version": 1,
        "enabled": False,
        "interval_minutes": 360,
        "allowed_intervals": [60, 180, 360, 720, 1440],
        "next_run_at": None,
        "last_evaluated_at": None,
        "last_enqueued_at": None,
        "last_skip_reason": None,
        "last_job": None,
        "active_job": None,
        "worker_status": "missing",
    }

    empty = client.patch("/api/me/feed-schedule", json={})
    invalid = client.patch("/api/me/feed-schedule", json={"interval_minutes": 61})
    no_subscriptions = client.patch("/api/me/feed-schedule", json={"enabled": True})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "invalid_feed_schedule"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_feed_schedule"
    assert no_subscriptions.status_code == 409
    assert no_subscriptions.json()["error"]["code"] == "no_enabled_subscriptions"

    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Scheduled Feed",
            "config": {"url": "https://example.com/scheduled.xml"},
        },
    ).json()["data"]
    assert client.post(f"/api/catalog/sources/{source['id']}/subscribe").status_code == 200

    patched = client.patch(
        "/api/me/feed-schedule",
        json={"enabled": True, "interval_minutes": 180},
    )
    fetched = client.get("/api/me/feed-schedule")
    assert patched.status_code == fetched.status_code == 200
    assert patched.json()["data"]["enabled"] is True
    assert patched.json()["data"]["interval_minutes"] == 180
    assert patched.json()["data"]["next_run_at"] is not None
    assert fetched.json()["data"] == patched.json()["data"]


def test_source_schedule_get_defaults_patch_round_trip_and_runtime_counts(
    tmp_path, monkeypatch
):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Frequent Feed",
            "config": {"url": "https://example.com/frequent.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    route = f"/api/me/subscriptions/{subscription['id']}/schedule"

    default_response = client.get(route)
    patched = client.patch(
        route,
        json={"enabled": True, "interval_minutes": 30},
    )
    runtime = client.get("/api/ops/runtime")

    assert default_response.status_code == 200
    assert default_response.json()["data"] == {
        "schema_version": 1,
        "subscription_id": subscription["id"],
        "source_id": source["id"],
        "enabled": False,
        "interval_minutes": 60,
        "allowed_intervals": [30, 60, 180, 360, 720, 1440],
        "next_run_at": None,
        "last_evaluated_at": None,
        "last_enqueued_at": None,
        "last_skip_reason": None,
        "last_job": None,
        "active_job": None,
        "worker_status": "missing",
    }
    assert patched.status_code == 200
    assert patched.json()["data"]["enabled"] is True
    assert patched.json()["data"]["interval_minutes"] == 30
    assert patched.json()["data"]["next_run_at"] is not None
    assert runtime.status_code == 200
    assert runtime.json()["data"]["source_schedule_count"] == 1
    assert runtime.json()["data"]["overdue_source_schedule_count"] == 1


def test_source_schedule_patch_preserves_omission_and_explicit_null_compatibility(
    tmp_path,
    monkeypatch,
):
    client, _data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Schedule patch compatibility",
            "config": {"url": "https://example.com/schedule-patch.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    route = f"/api/me/subscriptions/{subscription['id']}/schedule"
    client.patch(route, json={"enabled": True, "interval_minutes": 30})

    omitted_enabled = client.patch(route, json={"interval_minutes": 180})
    explicit_null_enabled = client.patch(
        route,
        json={"enabled": None, "interval_minutes": 360},
    )
    null_only = client.patch(route, json={"enabled": None})
    omitted_only = client.patch(route, json={})

    assert omitted_enabled.status_code == 200
    assert omitted_enabled.json()["data"]["enabled"] is True
    assert omitted_enabled.json()["data"]["interval_minutes"] == 180
    assert explicit_null_enabled.status_code == 200
    assert explicit_null_enabled.json()["data"]["enabled"] is True
    assert explicit_null_enabled.json()["data"]["interval_minutes"] == 360
    for rejected in (null_only, omitted_only):
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "invalid_source_schedule"


def test_source_schedule_is_current_user_only_and_viewer_is_read_only(
    tmp_path, monkeypatch
):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={"username": "viewer", "password": "viewer-password", "role": "viewer"},
    )
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "rss",
            "display_name": "Shared Scheduled Feed",
            "config": {"url": "https://example.com/shared-scheduled.xml"},
        },
    ).json()["data"]
    owner_subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    client.post("/api/auth/logout")
    _login_as(client, "viewer", "viewer-password")
    store = ServiceStore(data_dir)
    store.initialize()
    viewer = store.get_user_by_username("viewer")
    viewer_subscription = store.create_subscription(
        user_id=viewer["id"], source_id=source["id"]
    )

    own_get = client.get(
        f"/api/me/subscriptions/{viewer_subscription['id']}/schedule"
    )
    own_patch = client.patch(
        f"/api/me/subscriptions/{viewer_subscription['id']}/schedule",
        json={"enabled": True, "interval_minutes": 30},
    )
    other_get = client.get(
        f"/api/me/subscriptions/{owner_subscription['id']}/schedule"
    )

    assert own_get.status_code == 200
    assert own_patch.status_code == 403
    assert own_patch.json()["error"]["code"] == "forbidden"
    assert other_get.status_code == 404


def test_manual_source_fetch_is_deduplicated_per_subscription(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Deduplicated Feed",
            "config": {"url": "https://example.com/deduplicated.xml"},
        },
    ).json()["data"]
    subscription = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    ).json()["data"]["subscription"]
    payload = {
        "source_id": source["id"],
        "subscription_id": subscription["id"],
    }

    first = client.post("/api/jobs/source-fetch", json=payload)
    second = client.post("/api/jobs/source-fetch", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert first.json()["data"]["deduplicated"] is False
    assert second.json()["data"]["deduplicated"] is True
    store = ServiceStore(data_dir)
    store.initialize()
    usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM usage_events
        WHERE user_id = ? AND event_type = 'source_fetch'
        """,
        (store.get_user_by_username("owner")["id"],),
    ).fetchone()
    assert int(usage["total"]) == 1


def test_manual_feed_refresh_deduplicates_and_records_usage_once(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)

    first = client.post("/api/jobs/user-feed-refresh", json={})
    second = client.post("/api/jobs/user-feed-refresh", json={})

    assert first.status_code == second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert first_data["id"] == second_data["id"]
    assert first_data["deduplicated"] is False
    assert second_data["deduplicated"] is True

    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM usage_events
        WHERE user_id = ? AND event_type = 'user_feed_refresh'
        """,
        (owner["id"],),
    ).fetchone()
    jobs = store.connect().execute(
        """
        SELECT COUNT(*) AS count FROM fetch_jobs
        WHERE user_id = ? AND job_type = 'user_feed_refresh'
          AND status IN ('queued', 'running')
        """,
        (owner["id"],),
    ).fetchone()
    assert usage["total"] == 1
    assert jobs["count"] == 1


def test_ops_runtime_includes_schedule_metrics(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="runtime-member",
        password="member-password",
    )
    now = datetime.now(timezone.utc)
    overdue_at = now.replace(year=now.year - 1).isoformat()
    future_at = now.replace(year=now.year + 1).isoformat()
    store.connect().executemany(
        """
        INSERT INTO user_feed_schedules (
            user_id, workspace_id, enabled, interval_minutes, next_run_at,
            created_at, updated_at
        ) VALUES (?, ?, ?, 360, ?, ?, ?)
        """,
        [
            (owner["id"], workspace["id"], 1, overdue_at, now.isoformat(), now.isoformat()),
            (member["id"], workspace["id"], 1, future_at, now.isoformat(), now.isoformat()),
        ],
    )
    store.connect().commit()

    response = client.get("/api/ops/runtime")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["enabled_schedule_count"] == 2
    assert data["overdue_schedule_count"] == 1
    assert data["next_scheduled_at"] == overdue_at
    assert set(data["schedule_stats"]) == {
        "last_evaluated_at",
        "last_enqueued_at",
        "last_skip_reasons",
    }


def test_feed_schedule_public_jobs_hide_claim_token_and_keep_user_scope(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    source = client.post(
        "/api/catalog/sources",
        json={
            "scope": "private",
            "type": "rss",
            "display_name": "Claimed Schedule Feed",
            "config": {"url": "https://example.com/claimed-schedule.xml"},
        },
    ).json()["data"]
    client.post(f"/api/catalog/sources/{source['id']}/subscribe")
    client.patch(
        "/api/me/feed-schedule",
        json={"enabled": True, "interval_minutes": 360},
    )
    created = client.post("/api/jobs/user-feed-refresh", json={}).json()["data"]

    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    workspace = store.get_default_workspace()
    claimed = JobQueue(store).claim_next_job(worker_id="schedule-api-worker")
    assert claimed["id"] == created["id"]
    assert claimed["claim_token"]
    store.connect().execute(
        "UPDATE user_feed_schedules SET last_job_id = ? WHERE user_id = ?",
        (claimed["id"], owner["id"]),
    )
    store.connect().commit()

    response = client.get("/api/me/feed-schedule")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["last_job"]["id"] == claimed["id"]
    assert data["active_job"]["id"] == claimed["id"]
    for job in (data["last_job"], data["active_job"]):
        assert job["workspace_id"] == workspace["id"]
        assert job["user_id"] == owner["id"]
        assert job["status"] == "running"
        assert "claim_token" not in job


def test_manual_feed_refresh_quota_failure_rolls_back_job_and_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("INFOHUB_MAX_FETCH_JOBS_PER_DAY", "0")
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)

    response = client.post("/api/jobs/user-feed-refresh", json={})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exceeded"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    refresh_jobs = store.connect().execute(
        """
        SELECT COUNT(*) AS count FROM fetch_jobs
        WHERE user_id = ? AND job_type = 'user_feed_refresh'
        """,
        (owner["id"],),
    ).fetchone()
    refresh_usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total FROM usage_events
        WHERE user_id = ? AND event_type = 'user_feed_refresh'
        """,
        (owner["id"],),
    ).fetchone()
    assert refresh_jobs["count"] == 0
    assert refresh_usage["total"] == 0


def test_concurrent_manual_feed_refresh_api_deduplicates_and_charges_once(tmp_path, monkeypatch):
    client, data_dir = _client(tmp_path, monkeypatch)
    _login(client)
    barrier = threading.Barrier(2)

    def submit_refresh(_index):
        barrier.wait()
        return client.post("/api/jobs/user-feed-refresh", json={})

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit_refresh, range(2)))

    assert all(response.status_code == 200 for response in responses)
    jobs = [response.json()["data"] for response in responses]
    assert jobs[0]["id"] == jobs[1]["id"]
    assert sorted(job["deduplicated"] for job in jobs) == [False, True]

    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    active = store.connect().execute(
        """
        SELECT COUNT(*) AS count FROM fetch_jobs
        WHERE user_id = ? AND job_type = 'user_feed_refresh'
          AND status IN ('queued', 'running')
        """,
        (owner["id"],),
    ).fetchone()
    usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total FROM usage_events
        WHERE user_id = ? AND event_type = 'user_feed_refresh'
        """,
        (owner["id"],),
    ).fetchone()
    assert active["count"] == 1
    assert usage["total"] == 1
