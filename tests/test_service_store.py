import os

from src.storage.service_store import ServiceStore
from src.ui.auth import verify_password_hash


def test_service_store_initializes_schema_and_bootstrap_admin_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.delenv("HORIZON_AUTH_PASSWORD_HASH", raising=False)

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()

    workspace = store.get_default_workspace()
    users = store.list_users(workspace_id=workspace["id"])

    assert workspace["name"] == "Default Workspace"
    assert len(users) == 1
    assert users[0]["username"] == "owner"
    assert users[0]["role"] == "owner"
    assert users[0]["enabled"] is True
    assert users[0]["password_hash"] != "secret-password"
    assert verify_password_hash("secret-password", users[0]["password_hash"])


def test_service_store_catalog_visibility_hides_other_users_private_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    alice = store.create_user(
        workspace_id=workspace["id"],
        username="alice",
        password="alice-password",
        role="member",
    )
    bob = store.create_user(
        workspace_id=workspace["id"],
        username="bob",
        password="bob-password",
        role="member",
    )

    public_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Public Feed",
        config={"name": "Public Feed", "url": "https://example.com/feed.xml"},
    )
    alice_private_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=alice["id"],
        source_type="rss",
        display_name="Alice Feed",
        config={"name": "Alice Feed", "url": "https://example.com/alice.xml"},
    )
    store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=bob["id"],
        source_type="rss",
        display_name="Bob Feed",
        config={"name": "Bob Feed", "url": "https://example.com/bob.xml"},
    )

    visible_ids = {source["id"] for source in store.list_visible_sources(alice)}

    assert public_id in visible_ids
    assert alice_private_id in visible_ids
    assert len(visible_ids) == 2


def test_service_store_sanitizes_secret_env_without_returning_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("RSS_PRIVATE_TOKEN", "real-token-value")

    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")

    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Secret Feed",
        config={"name": "Secret Feed", "url": "https://example.com/feed.xml"},
        secret_env="RSS_PRIVATE_TOKEN",
    )

    source = store.get_source(source_id)

    assert source["secret_env"] == "RSS_PRIVATE_TOKEN"
    assert "real-token-value" not in repr(source)


def test_service_store_get_user_subscription_for_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Subscribed Feed",
        config={"name": "Subscribed Feed", "url": "https://example.com/feed.xml"},
    )
    created = store.create_subscription(user_id=owner["id"], source_id=source_id)

    found = store.get_user_subscription_for_source(owner["id"], source_id)

    assert found["id"] == created["id"]
    assert found["source_id"] == source_id
    assert store.get_user_subscription_for_source(owner["id"], "src_missing") is None


def test_service_store_migrates_fetch_jobs_for_worker_hardening(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()

    columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(fetch_jobs)").fetchall()
    }

    assert "max_attempts" in columns
    assert "next_run_at" in columns
    assert "locked_until" in columns
    assert "cancelled_at" in columns
    assert "expires_at" in columns


def test_service_store_initializes_user_feed_snapshot_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()

    snapshot_columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(user_feed_snapshots)").fetchall()
    }
    item_columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(user_feed_items)").fetchall()
    }

    assert {
        "id",
        "workspace_id",
        "user_id",
        "job_id",
        "generated_at",
        "item_count",
        "payload_json",
    }.issubset(snapshot_columns)
    assert {
        "snapshot_id",
        "user_id",
        "article_id",
        "source",
        "channel",
        "topics_json",
        "score",
        "published_at",
    }.issubset(item_columns)


def test_service_store_source_key_schema_and_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(source_catalog)").fetchall()
    }

    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="github_release",
        display_name="OpenAI Codex Releases",
        config={"owner": "OpenAI", "repo": "Codex", "type": "repo_releases"},
        source_key="github_release:openai/codex",
    )
    found = store.get_source_by_key(workspace_id=workspace["id"], source_key="github_release:openai/codex")
    updated = store.update_source(source_id, source_key="github_release:openai/codex-v2")

    assert "source_key" in columns
    assert found["id"] == source_id
    assert found["source_key"] == "github_release:openai/codex"
    assert updated["source_key"] == "github_release:openai/codex-v2"
    assert store.get_source_by_key(workspace_id=workspace["id"], source_key="github_release:openai/codex") is None


def test_service_store_initializes_user_item_behavior_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()

    state_columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(user_item_state)").fetchall()
    }
    feedback_columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(user_item_feedback)").fetchall()
    }

    assert {
        "workspace_id",
        "user_id",
        "article_id",
        "is_read",
        "is_saved",
        "is_later",
        "dismissed_at",
        "updated_at",
    }.issubset(state_columns)
    assert {
        "workspace_id",
        "user_id",
        "article_id",
        "feedback_type",
        "reason",
        "metadata_json",
        "created_at",
    }.issubset(feedback_columns)
