import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts.migrate_user_feed_v2 import migrate_feed_v2
from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


def _legacy_store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    conn = store.connect()
    conn.execute("DROP INDEX IF EXISTS idx_user_feed_snapshots_job_id")
    conn.execute("DROP INDEX IF EXISTS idx_user_feed_items_snapshot_article")
    conn.execute("DELETE FROM schema_migrations WHERE version = 2")
    now = datetime.now(timezone.utc).isoformat()
    for snapshot_id in ("legacy-1", "legacy-2"):
        conn.execute(
            """
            INSERT INTO user_feed_snapshots (
                id, workspace_id, user_id, job_id, schema_version,
                generated_at, item_count, payload_json, created_at
            ) VALUES (?, ?, ?, 'legacy-job', 2, ?, 1, '{}', ?)
            """,
            (snapshot_id, workspace["id"], owner["id"], now, now),
        )
    for item_id in ("legacy-item-1", "legacy-item-2"):
        conn.execute(
            """
            INSERT INTO user_feed_items (
                id, workspace_id, user_id, snapshot_id, article_id, created_at
            ) VALUES (?, ?, ?, 'legacy-1', 'same-article', ?)
            """,
            (item_id, workspace["id"], owner["id"], now),
        )
    conn.execute(
        "CREATE TABLE user_item_feedback (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO user_item_feedback (id, payload) VALUES ('legacy-feedback', 'keep')"
    )
    conn.commit()
    queue = JobQueue(store)
    queued = queue.create_job(
        workspace_id=workspace["id"], user_id=owner["id"], job_type="user_feed_refresh"
    )
    running_job = queue.create_job(
        workspace_id=workspace["id"], user_id=owner["id"], job_type="source_fetch"
    )
    running = queue.claim_next_job(worker_id="stopped-worker")
    assert running["id"] in {queued["id"], running_job["id"]}
    store.close()
    return workspace, owner


def test_legacy_duplicates_require_explicit_migration_without_breaking_initialize(tmp_path, monkeypatch):
    _legacy_store(tmp_path, monkeypatch)

    reopened = ServiceStore(tmp_path)
    reopened.initialize()

    assert reopened.feed_v2_migration_required() is True
    versions = reopened.connect().execute(
        "SELECT DISTINCT schema_version FROM user_feed_snapshots"
    ).fetchall()
    assert [row[0] for row in versions] == [1]


def test_explicit_feed_v2_migration_backs_up_resets_and_marks_database(tmp_path, monkeypatch):
    _legacy_store(tmp_path, monkeypatch)
    backup_dir = tmp_path / "backups"

    result = migrate_feed_v2(data_dir=tmp_path, backup_dir=backup_dir, apply=True)

    assert result["applied"] is True
    assert result["deleted_snapshots"] == 2
    assert Path(result["backup_path"]).is_file()
    assert Path(result["backup_path"]).stat().st_mode & 0o777 == 0o600
    backup = sqlite3.connect(result["backup_path"])
    try:
        assert {
            row[0]
            for row in backup.execute("SELECT DISTINCT schema_version FROM user_feed_snapshots")
        } == {2}
    finally:
        backup.close()
    store = ServiceStore(tmp_path)
    store.initialize()
    assert store.feed_v2_migration_required() is False
    assert store.connect().execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0] == 0
    assert store.connect().execute("SELECT COUNT(*) FROM user_feed_items").fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT payload FROM user_item_feedback WHERE id = 'legacy-feedback'"
    ).fetchone()[0] == "keep"
    assert "deleted_feedback" not in result
    statuses = store.connect().execute(
        "SELECT DISTINCT status, error_code FROM fetch_jobs WHERE job_type IN ('source_fetch', 'user_feed_refresh')"
    ).fetchall()
    assert {(row["status"], row["error_code"]) for row in statuses} == {
        ("cancelled", "feed_v2_migration")
    }
    assert store.connect().execute("PRAGMA foreign_key_check").fetchall() == []
    indexes = {row["name"] for row in store.connect().execute("PRAGMA index_list(user_feed_snapshots)")}
    assert "idx_user_feed_snapshots_job_id" in indexes

    check = migrate_feed_v2(data_dir=tmp_path, backup_dir=backup_dir, apply=False)
    assert check["migration_required"] is False
    assert check["snapshot_count"] == 0


def test_feed_v2_migration_dry_run_does_not_mutate_legacy_database(tmp_path, monkeypatch):
    _legacy_store(tmp_path, monkeypatch)

    result = migrate_feed_v2(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        apply=False,
    )

    connection = sqlite3.connect(tmp_path / "service.db")
    try:
        versions = {
            row[0]
            for row in connection.execute("SELECT DISTINCT schema_version FROM user_feed_snapshots")
        }
    finally:
        connection.close()
    assert result["migration_required"] is True
    assert versions == {2}


def test_feed_v2_backups_are_ignored_by_git():
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")

    assert "data/backups/" in gitignore


def test_worker_refuses_feed_jobs_until_explicit_migration(tmp_path, monkeypatch):
    _legacy_store(tmp_path, monkeypatch)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="v2-worker", retry_base_seconds=0)

    assert result["status"] == "failed"
    assert result["error_code"] == "MigrationRequiredError"
    assert "migration" in result["error_message"].lower()


def test_reapplying_completed_feed_v2_migration_does_not_delete_v2_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="v2-job",
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [{"id": "rss:item:v2"}],
        },
    )
    store.close()

    result = migrate_feed_v2(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        apply=True,
    )

    reopened = ServiceStore(tmp_path)
    reopened.initialize()
    assert result["applied"] is False
    assert result["backup_path"] is None
    assert result["reason"] == "already_migrated"
    assert reopened.connect().execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0] == 1
    assert reopened.connect().execute("SELECT COUNT(*) FROM user_feed_items").fetchone()[0] == 1


def test_state_only_legacy_database_still_requires_explicit_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    now = datetime.now(timezone.utc).isoformat()
    store.connect().execute(
        """
        INSERT INTO user_item_state (
            id, workspace_id, user_id, article_id, created_at, updated_at
        ) VALUES ('legacy-state', ?, ?, 'legacy-article', ?, ?)
        """,
        (workspace["id"], owner["id"], now, now),
    )
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 2")
    store.connect().commit()
    store.close()

    dry_run = migrate_feed_v2(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        apply=False,
    )
    reopened = ServiceStore(tmp_path)
    reopened.initialize()

    assert dry_run["migration_required"] is True
    assert dry_run["state_count"] == 1
    assert reopened.feed_v2_migration_required() is True
    assert reopened.connect().execute(
        "SELECT 1 FROM schema_migrations WHERE version = 2"
    ).fetchone() is None


def test_pending_feed_job_without_snapshots_requires_migration_and_is_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 2")
    store.connect().commit()
    store.close()

    dry_run = migrate_feed_v2(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        apply=False,
    )
    applied = migrate_feed_v2(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    reopened = ServiceStore(tmp_path)
    reopened.initialize()

    assert dry_run["migration_required"] is True
    assert dry_run["pending_feed_job_count"] == 1
    assert applied["applied"] is True
    assert applied["cancelled_jobs"] == 1
    loaded = JobQueue(reopened).get_job(job["id"])
    assert loaded["status"] == "cancelled"
    assert loaded["error_code"] == "feed_v2_migration"
