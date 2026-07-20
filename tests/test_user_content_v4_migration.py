from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrate_user_content_v4 import migrate_user_content_v4
from src.services.user_content_store import UserContentStore
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


def _legacy_content_store(tmp_path, monkeypatch) -> tuple[str, str]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="legacy-content-job",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-14T08:00:00+00:00",
            "items": [{
                "id": "legacy-saved-item",
                "title": "Legacy captured summary",
                "url": "https://example.com/legacy",
                "summary_zh": "旧快照摘要",
            }],
        },
    )
    store.connect().execute("DELETE FROM user_content_items")
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 4")
    store.connect().commit()
    store.close()
    return workspace["id"], owner["id"]


def test_user_content_v4_dry_run_is_read_only_and_apply_backfills_with_backup(
    tmp_path, monkeypatch
):
    workspace_id, user_id = _legacy_content_store(tmp_path, monkeypatch)
    backup_dir = tmp_path / "backups"

    dry_run = migrate_user_content_v4(
        data_dir=tmp_path, backup_dir=backup_dir, apply=False
    )
    assert dry_run["applied"] is False
    assert dry_run["missing_content_items"] == 1
    assert dry_run["backup_path"] is None
    assert not backup_dir.exists()

    applied = migrate_user_content_v4(
        data_dir=tmp_path, backup_dir=backup_dir, apply=True
    )
    backup_path = Path(applied["backup_path"])
    reopened = ServiceStore(tmp_path)
    reopened.initialize()
    stored = reopened.connect().execute(
        """
        SELECT item_json, body_text, body_completeness
        FROM user_content_items
        WHERE workspace_id = ? AND user_id = ? AND article_id = ?
        """,
        (workspace_id, user_id, "legacy-saved-item"),
    ).fetchone()

    assert applied["applied"] is True
    assert applied["backfilled_items"] == 1
    assert applied["integrity_check"] == "ok"
    assert applied["foreign_key_errors"] == 0
    assert backup_path.is_file()
    assert backup_path.stat().st_mode & 0o777 == 0o600
    assert "Legacy captured summary" in stored["item_json"]
    assert stored["body_text"] == "旧快照摘要"
    assert stored["body_completeness"] == "excerpt_only"
    assert reopened.content_index_v4_migration_required() is False
    assert reopened.connect().execute(
        "SELECT 1 FROM schema_migrations WHERE version = 4"
    ).fetchone() is not None


def test_user_content_v4_migration_required_when_old_feed_items_are_unindexed(
    tmp_path, monkeypatch
):
    _legacy_content_store(tmp_path, monkeypatch)
    store = ServiceStore(tmp_path)
    store.initialize()
    assert store.content_index_v4_migration_required() is True
    connection = sqlite3.connect(tmp_path / "service.db")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM user_content_items"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_user_content_v4_detail_rebuilds_complete_presentation(tmp_path, monkeypatch):
    workspace_id, user_id = _legacy_content_store(tmp_path, monkeypatch)
    migrate_user_content_v4(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    try:
        detail = UserContentStore(store).detail_item(
            workspace_id=workspace_id,
            user_id=user_id,
            article_id="legacy-saved-item",
        )
    finally:
        store.close()

    assert detail is not None
    presentation = detail["presentation"]
    assert presentation["version"] == 2
    assert {
        "source",
        "author",
        "timing",
        "links",
        "content",
        "taxonomy",
        "engagement",
        "analysis",
        "media",
    } <= presentation.keys()
    assert presentation["links"] == {
        "canonical_url": "https://example.com/legacy",
        "source_url": "https://example.com/legacy",
    }
    assert presentation["content"]["title"] == "Legacy captured summary"
    assert presentation["analysis"]["summary_zh"] == "旧快照摘要"
