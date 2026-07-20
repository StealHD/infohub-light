#!/usr/bin/env python3
"""Backfill Feed hashes and apply v3 retention with a UTC SQLite backup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.migrate_user_feed_v2 import _active_workers
from src.services.maintenance import MaintenanceService
from src.services.user_feed_store import UserFeedStore, feed_content_hash
from src.storage.service_store import ServiceStore


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(connection, table):
        return False
    return column in {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "database_exists": False,
            "snapshot_count": 0,
            "null_content_hashes": 0,
            "migrated": False,
        }
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        snapshot_count = (
            int(connection.execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0])
            if _table_exists(connection, "user_feed_snapshots")
            else 0
        )
        if _column_exists(
            connection, "user_feed_snapshots", "content_hash"
        ):
            null_content_hashes = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM user_feed_snapshots
                    WHERE content_hash IS NULL OR content_hash = ''
                    """
                ).fetchone()[0]
            )
        else:
            null_content_hashes = snapshot_count
        migrated = bool(
            _table_exists(connection, "schema_migrations")
            and connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 3"
            ).fetchone()
        )
    finally:
        connection.close()
    return {
        "database_exists": True,
        "snapshot_count": snapshot_count,
        "null_content_hashes": null_content_hashes,
        "migrated": migrated,
    }


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-feed-v3-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(target, 0o600)
    return target


def migrate_feed_storage_v3(
    *,
    data_dir: Path | str,
    backup_dir: Path | str,
    apply: bool,
) -> dict[str, Any]:
    data_path = Path(data_dir)
    db_path = data_path / "service.db"
    inspection = _inspect(db_path)
    result: dict[str, Any] = {
        "applied": False,
        "snapshot_count": inspection["snapshot_count"],
        "null_content_hashes": inspection["null_content_hashes"],
        "backup_path": None,
    }
    if not apply:
        return result
    if inspection["migrated"] and inspection["null_content_hashes"] == 0:
        result["reason"] = "already_migrated"
        return result

    active_workers = _active_workers(db_path)
    if active_workers:
        raise RuntimeError(
            "stop all horizon-worker processes before applying feed storage v3 migration"
        )

    data_path.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        bootstrap_store = ServiceStore(data_path)
        try:
            bootstrap_store.initialize()
        finally:
            bootstrap_store.close()
    backup_path = _backup_database(db_path, Path(backup_dir))
    store = ServiceStore(data_path)
    store.initialize()
    conn = store.connect()
    feed_store = UserFeedStore(store)
    backfilled = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT * FROM user_feed_snapshots
            WHERE content_hash IS NULL OR content_hash = ''
            ORDER BY created_at, id
            """
        ).fetchall()
        for row in rows:
            snapshot = feed_store._snapshot(row)
            if snapshot is None:
                continue
            payload = snapshot.get("payload") or {}
            content_hash = feed_content_hash(
                payload,
                [item for item in payload.get("items", []) if isinstance(item, dict)],
            )
            conn.execute(
                "UPDATE user_feed_snapshots SET content_hash = ? WHERE id = ?",
                (content_hash, snapshot["id"]),
            )
            backfilled += 1
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise

    retention = MaintenanceService(store).run_if_due(force=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR REPLACE INTO schema_migrations (
                version, name, checksum, applied_at
            ) VALUES (3, 'feed_storage_v3', 'feed-storage-v3-hash-retention', ?)
            """,
            (now,),
        )
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity_check = str(integrity_row[0] if integrity_row else "unknown")
        if foreign_key_errors:
            raise RuntimeError(
                f"foreign key check failed: {len(foreign_key_errors)} row(s)"
            )
        if integrity_check.lower() != "ok":
            raise RuntimeError(f"integrity check failed: {integrity_check}")
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        store.close()

    result.update(
        {
            "applied": True,
            "backup_path": str(backup_path),
            "backfilled_content_hashes": backfilled,
            "retention_deleted": retention["deleted"],
            "integrity_check": integrity_check,
            "foreign_key_errors": len(foreign_key_errors),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply the additive Feed storage v3 migration"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate_feed_storage_v3(
                data_dir=args.data_dir,
                backup_dir=args.backup_dir,
                apply=bool(args.apply),
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
