from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.migrate_feed_storage_v3 import migrate_feed_storage_v3
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


def _legacy_v3_store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.delenv("HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED", raising=False)
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="legacy-v3-current-job",
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [
                {
                    "id": "legacy-v3-current",
                    "title": "Legacy body must not be rewritten",
                    "url": "https://example.com/legacy-v3?keep=query",
                }
            ],
        },
    )
    original_payload = store.connect().execute(
        "SELECT payload_json FROM user_feed_snapshots WHERE id = ?",
        (snapshot["id"],),
    ).fetchone()["payload_json"]
    store.connect().execute(
        "UPDATE user_feed_snapshots SET content_hash = NULL WHERE id = ?",
        (snapshot["id"],),
    )
    old = datetime.now(timezone.utc) - timedelta(days=120)
    store.connect().execute(
        """
        INSERT INTO user_feed_snapshots (
            id, workspace_id, user_id, schema_version, storage_version,
            content_hash, generated_at, item_count, payload_json, created_at
        ) VALUES ('legacy-v3-old', ?, ?, 2, 1, NULL, ?, 1, ?, ?)
        """,
        (
            workspace["id"],
            owner["id"],
            old.isoformat(),
            json.dumps(
                {
                    "schema_version": 2,
                    "items": [{"id": "legacy-v3-old-item", "title": "Old"}],
                }
            ),
            old.isoformat(),
        ),
    )
    store.connect().commit()
    store.close()
    return snapshot["id"], original_payload


def test_feed_storage_v3_dry_run_is_read_only_and_apply_backs_up_and_backfills(
    tmp_path, monkeypatch
):
    snapshot_id, original_payload = _legacy_v3_store(tmp_path, monkeypatch)
    backup_dir = tmp_path / "backups"

    dry_run = migrate_feed_storage_v3(
        data_dir=tmp_path,
        backup_dir=backup_dir,
        apply=False,
    )
    connection = sqlite3.connect(tmp_path / "service.db")
    connection.row_factory = sqlite3.Row
    try:
        dry_row = connection.execute(
            "SELECT content_hash, payload_json FROM user_feed_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
    finally:
        connection.close()

    assert dry_run["applied"] is False
    assert dry_run["null_content_hashes"] == 2
    assert dry_run["backup_path"] is None
    assert dry_row["content_hash"] is None
    assert dry_row["payload_json"] == original_payload
    assert not backup_dir.exists()

    applied = migrate_feed_storage_v3(
        data_dir=tmp_path,
        backup_dir=backup_dir,
        apply=True,
    )
    backup_path = Path(applied["backup_path"])
    reopened = ServiceStore(tmp_path)
    reopened.initialize()
    current = reopened.connect().execute(
        "SELECT content_hash, storage_version, payload_json FROM user_feed_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()

    assert applied["applied"] is True
    assert applied["backfilled_content_hashes"] == 2
    assert applied["retention_deleted"]["feed_snapshots"] == 1
    assert applied["integrity_check"] == "ok"
    assert applied["foreign_key_errors"] == 0
    assert backup_path.is_file()
    assert backup_path.name.endswith("Z.db")
    assert backup_path.stat().st_mode & 0o777 == 0o600
    assert len(current["content_hash"]) == 64
    assert current["storage_version"] == 1
    assert current["payload_json"] == original_payload
    assert reopened.connect().execute(
        "SELECT 1 FROM user_feed_snapshots WHERE id = 'legacy-v3-old'"
    ).fetchone() is None
    assert reopened.connect().execute(
        "SELECT 1 FROM schema_migrations WHERE version = 3"
    ).fetchone() is not None
    assert reopened.connect().execute("PRAGMA foreign_key_check").fetchall() == []
