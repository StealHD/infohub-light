import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.auth import verify_password_hash
from src.storage.service_store import ServiceStore, UserActiveJobsError


def test_service_store_uses_an_independent_connection_per_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    barrier = threading.Barrier(8)

    def connection_identity() -> int:
        barrier.wait(timeout=5)
        return id(store.connect())

    with ThreadPoolExecutor(max_workers=8) as executor:
        identities = list(executor.map(lambda _index: connection_identity(), range(8)))

    assert len(set(identities)) == 8


def test_service_store_can_close_only_the_current_thread_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    original = store.connect()

    store.close_current()

    with pytest.raises(sqlite3.ProgrammingError):
        original.execute("SELECT 1")
    replacement = store.connect()
    assert replacement is not original
    assert replacement.execute("SELECT 1").fetchone()[0] == 1


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


def test_service_store_validates_subscription_priority_as_integer_zero_to_one_hundred(
    tmp_path, monkeypatch
):
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
        display_name="Priority Feed",
        config={"url": "https://example.com/priority.xml"},
    )

    for invalid in (-1, 101, 1.5, "10", True):
        with pytest.raises(ValueError, match="priority must be an integer between 0 and 100"):
            store.create_subscription(
                user_id=owner["id"],
                source_id=source_id,
                priority=invalid,
            )

    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id, priority=100
    )
    assert subscription["priority"] == 100

    for invalid in (-1, 101, 1.5, "10", False, None):
        with pytest.raises(ValueError, match="priority must be an integer between 0 and 100"):
            store.update_subscription(subscription["id"], priority=invalid)

    assert store.get_subscription(subscription["id"])["priority"] == 100


def test_subscription_writes_can_join_caller_transaction(tmp_path, monkeypatch):
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
        display_name="Transactional RSS",
        config={"url": "https://example.com/transactional.xml"},
    )

    conn = store.connect()
    conn.execute("BEGIN IMMEDIATE")
    created = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
        commit=False,
    )
    store.update_subscription(created["id"], enabled=False, commit=False)
    conn.rollback()

    assert store.get_user_subscription_for_source(owner["id"], source_id) is None


def test_subscription_upsert_disable_uses_lifecycle_invalidation(
    tmp_path, monkeypatch
):
    from src.services.job_queue import JobQueue
    from src.services.source_schedule import SourceScheduleService

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
        display_name="Upsert Lifecycle RSS",
        config={"url": "https://example.com/upsert-lifecycle.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
    )
    queued, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    assert created is True

    updated = store.create_subscription(
        user_id=owner["id"], source_id=source_id, enabled=False
    )

    assert updated["id"] == subscription["id"]
    assert updated["enabled"] is False
    assert store.get_source_schedule(subscription["id"])["enabled"] is False
    assert JobQueue(store).get_job(queued["id"])["status"] == "cancelled"


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


def test_service_store_initializes_user_source_health_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()

    columns = {
        row["name"]: row
        for row in store.connect().execute("PRAGMA table_info(user_source_health)").fetchall()
    }
    foreign_keys = {
        row["from"]: (row["table"], row["to"], row["on_delete"])
        for row in store.connect().execute(
            "PRAGMA foreign_key_list(user_source_health)"
        ).fetchall()
    }
    indexes = {
        row["name"]: tuple(
            column["name"]
            for column in store.connect().execute(
                f"PRAGMA index_info({row['name']})"
            ).fetchall()
        )
        for row in store.connect().execute(
            "PRAGMA index_list(user_source_health)"
        ).fetchall()
    }
    application_columns = {
        row["name"]: row
        for row in store.connect().execute(
            "PRAGMA table_info(user_source_health_applications)"
        ).fetchall()
    }
    application_foreign_keys = {
        row["from"]: (row["table"], row["to"], row["on_delete"])
        for row in store.connect().execute(
            "PRAGMA foreign_key_list(user_source_health_applications)"
        ).fetchall()
    }

    assert set(columns) == {
        "subscription_id",
        "workspace_id",
        "user_id",
        "source_id",
        "status",
        "last_attempt_at",
        "last_success_at",
        "last_failure_at",
        "consecutive_failures",
        "last_fetched_count",
        "last_issue_stage",
        "last_issue_code",
        "last_issue_message",
        "last_issue_retryable",
        "last_job_id",
        "created_at",
        "updated_at",
    }
    assert columns["subscription_id"]["pk"] == 1
    assert foreign_keys == {
        "last_job_id": ("fetch_jobs", "id", "SET NULL"),
        "source_id": ("source_catalog", "id", "CASCADE"),
        "user_id": ("users", "id", "CASCADE"),
        "workspace_id": ("workspaces", "id", "CASCADE"),
        "subscription_id": ("user_subscriptions", "id", "CASCADE"),
    }
    assert ("workspace_id", "user_id", "status") in indexes.values()
    assert ("workspace_id", "source_id") in indexes.values()
    assert set(application_columns) == {"subscription_id", "job_id", "applied_at"}
    assert application_columns["subscription_id"]["pk"] == 1
    assert application_columns["job_id"]["pk"] == 2
    assert application_foreign_keys == {
        "job_id": ("fetch_jobs", "id", "CASCADE"),
        "subscription_id": ("user_subscriptions", "id", "CASCADE"),
    }
    assert store.connect().execute("PRAGMA foreign_key_check").fetchall() == []


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


def test_service_store_upsert_source_serializes_concurrent_same_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    barrier = threading.Barrier(6)

    def upsert(index: int) -> str:
        barrier.wait(timeout=5)
        source = store.upsert_source(
            workspace_id=workspace["id"],
            scope="public",
            owner_user_id=owner["id"],
            source_type="rss",
            display_name=f"Concurrent Feed {index}",
            config={"name": "Concurrent Feed", "url": "https://example.com/concurrent.xml"},
            source_key="rss:https://example.com/concurrent.xml",
        )
        return source["id"]

    with ThreadPoolExecutor(max_workers=6) as executor:
        source_ids = list(executor.map(upsert, range(6)))

    assert len(set(source_ids)) == 1
    matching = store.connect().execute(
        "SELECT COUNT(*) FROM source_catalog WHERE workspace_id = ? AND source_key = ?",
        (workspace["id"], "rss:https://example.com/concurrent.xml"),
    ).fetchone()[0]
    assert matching == 1


def test_service_store_upsert_source_does_not_take_over_another_users_private_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    alice = store.create_user(
        workspace_id=workspace["id"], username="alice", password="alice-password", role="member"
    )
    bob = store.create_user(
        workspace_id=workspace["id"], username="bob", password="bob-password", role="member"
    )
    source_key = "rss:https://example.com/private-shared-key.xml"
    alice_source = store.upsert_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=alice["id"],
        source_type="rss",
        display_name="Alice Private Feed",
        config={"url": "https://example.com/private-shared-key.xml"},
        source_key=source_key,
    )

    with pytest.raises(ValueError, match="source_key") as caught:
        store.upsert_source(
            workspace_id=workspace["id"],
            scope="private",
            owner_user_id=bob["id"],
            source_type="rss",
            display_name="Bob Private Feed",
            config={"url": "https://example.com/private-shared-key.xml"},
            source_key=source_key,
        )

    assert "source_key" in str(caught.value)
    assert store.get_source(alice_source["id"])["owner_user_id"] == alice["id"]


def test_service_store_initializes_item_state_without_feedback_table(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()

    state_columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(user_item_state)").fetchall()
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
    assert store.connect().execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_item_feedback'"
    ).fetchone() is None


def test_service_store_initialize_preserves_legacy_feedback_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    db_path = tmp_path / "service.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE user_item_feedback (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO user_item_feedback (id, payload) VALUES ('legacy-1', 'keep')"
    )
    connection.commit()
    connection.close()

    store = ServiceStore(tmp_path)
    store.initialize()

    row = store.connect().execute(
        "SELECT id, payload FROM user_item_feedback WHERE id = 'legacy-1'"
    ).fetchone()
    assert dict(row) == {"id": "legacy-1", "payload": "keep"}


def test_service_store_initializes_stable_content_and_media_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)

    store.initialize()

    tables = {
        row["name"]
        for row in store.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    content_column_rows = store.connect().execute(
        "PRAGMA table_info(user_content_items)"
    ).fetchall()
    content_columns = {row["name"] for row in content_column_rows}
    media_columns = {
        row["name"]
        for row in store.connect().execute(
            "PRAGMA table_info(media_assets)"
        ).fetchall()
    }

    assert {"user_content_items", "media_assets"} <= tables
    assert {
        "workspace_id",
        "user_id",
        "article_id",
        "item_json",
        "body_text",
        "body_truncated",
        "body_completeness",
        "analysis_input_hash",
        "unresolved_reason",
        "first_seen_at",
        "last_seen_at",
    } <= content_columns
    unresolved_reason = next(
        row for row in content_column_rows if row["name"] == "unresolved_reason"
    )
    assert unresolved_reason["notnull"] == 0
    assert {
        "workspace_id",
        "user_id",
        "source_id",
        "article_id",
        "asset_kind",
        "local_path",
        "mime_type",
        "byte_size",
        "checksum",
        "status",
    } <= media_columns


def test_update_user_rolls_back_role_and_schedule_when_viewer_cleanup_fails(
    tmp_path, monkeypatch
):
    from src.services.feed_schedule import FeedScheduleService
    from src.services.job_queue import JobQueue

    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Rollback Feed",
        config={"name": "Rollback Feed", "url": "https://example.com/rollback.xml"},
        source_key="rss:https://example.com/rollback.xml",
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)
    FeedScheduleService(store).update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True
    )
    queued, created = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "scheduled_service_refresh"},
        priority=-10,
    )
    assert created is True
    store.connect().execute(
        """
        CREATE TRIGGER reject_user_job_cancel
        BEFORE UPDATE OF status ON fetch_jobs
        WHEN NEW.status = 'cancelled'
        BEGIN
            SELECT RAISE(ABORT, 'forced cleanup failure');
        END
        """
    )
    store.connect().commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced cleanup failure"):
        store.update_user(owner["id"], role="viewer")

    assert store.connect().in_transaction is False
    assert store.get_user(owner["id"])["role"] == "owner"
    schedule = FeedScheduleService(store).get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )
    assert schedule["enabled"] is True
    assert JobQueue(store).get_job(queued["id"])["status"] == "queued"


def test_delete_user_rolls_back_while_a_job_is_running(tmp_path, monkeypatch):
    from src.services.job_queue import JobQueue

    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="running-member",
        password="member-password",
    )
    job, created = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=member["id"],
        payload={"reason": "manual"},
    )
    assert created is True
    store.connect().execute(
        "UPDATE fetch_jobs SET status = 'running' WHERE id = ?",
        (job["id"],),
    )
    store.connect().commit()

    with pytest.raises(UserActiveJobsError):
        store.delete_user(member["id"], reassigned_user_id=owner["id"])

    assert store.get_user(member["id"]) is not None
    assert JobQueue(store).get_job(job["id"])["status"] == "running"


def test_update_source_rolls_back_lifecycle_when_feed_reconciliation_fails(
    tmp_path, monkeypatch
):
    from src.services.job_queue import JobQueue
    from src.services.source_schedule import SourceScheduleService

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
        display_name="Rollback Source",
        config={"url": "https://example.com/rollback-source.xml"},
        source_key="rss:https://example.com/rollback-source.xml",
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
    )
    queued, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    assert created is True

    def fail_reconciliation(_user_id):
        raise RuntimeError("forced feed reconciliation failure")

    monkeypatch.setattr(store, "_reconcile_user_feed_locked", fail_reconciliation)

    with pytest.raises(RuntimeError, match="forced feed reconciliation failure"):
        store.update_source(source_id, enabled=False)

    assert store.connect().in_transaction is False
    assert store.get_source(source_id)["enabled"] is True
    assert store.get_source_schedule(subscription["id"])["enabled"] is True
    assert JobQueue(store).get_job(queued["id"])["status"] == "queued"


def test_source_upsert_disable_uses_lifecycle_invalidation(tmp_path, monkeypatch):
    from src.services.job_queue import JobQueue
    from src.services.source_schedule import SourceScheduleService

    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_key = "rss:https://example.com/upsert-source.xml"
    source = store.upsert_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Upsert Source",
        config={"url": "https://example.com/upsert-source.xml"},
        source_key=source_key,
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source["id"]
    )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
    )
    queued, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source["id"],
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    assert created is True

    updated = store.upsert_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Upsert Source",
        config={"url": "https://example.com/upsert-source.xml"},
        source_key=source_key,
        enabled=False,
    )

    assert updated["id"] == source["id"]
    assert updated["enabled"] is False
    assert store.get_source_schedule(subscription["id"])["enabled"] is False
    assert JobQueue(store).get_job(queued["id"])["status"] == "cancelled"
