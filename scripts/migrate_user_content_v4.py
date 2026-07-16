#!/usr/bin/env python3
"""Backfill the stable user content index with a consistent SQLite backup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.migrate_user_feed_v2 import _active_workers
from src.services.user_content_store import UserContentStore
from src.storage.service_store import ServiceStore


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"database_exists": False, "missing_content_items": 0, "migrated": False}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not _table_exists(connection, "user_feed_items"):
            missing = 0
        elif not _table_exists(connection, "user_content_items"):
            missing = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT snapshot.workspace_id || ':' || snapshot.user_id || ':' || feed_item.article_id) FROM user_feed_items AS feed_item JOIN user_feed_snapshots AS snapshot ON snapshot.id = feed_item.snapshot_id"
                ).fetchone()[0]
            )
        else:
            missing = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                      SELECT snapshot.workspace_id, snapshot.user_id, feed_item.article_id
                      FROM user_feed_items AS feed_item
                      JOIN user_feed_snapshots AS snapshot ON snapshot.id = feed_item.snapshot_id
                      LEFT JOIN user_content_items AS content
                        ON content.workspace_id = snapshot.workspace_id
                       AND content.user_id = snapshot.user_id
                       AND content.article_id = feed_item.article_id
                      WHERE content.id IS NULL
                      GROUP BY snapshot.workspace_id, snapshot.user_id, feed_item.article_id
                    )
                    """
                ).fetchone()[0]
            )
        migrated = bool(
            _table_exists(connection, "schema_migrations")
            and connection.execute("SELECT 1 FROM schema_migrations WHERE version = 4").fetchone()
        )
    finally:
        connection.close()
    return {"database_exists": True, "missing_content_items": missing, "migrated": migrated}


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-user-content-v4-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(target, 0o600)
    return target


def _item_from_row(row: sqlite3.Row) -> dict[str, Any] | None:
    try:
        item = json.loads(row["item_json"] or "null")
    except json.JSONDecodeError:
        item = None
    if isinstance(item, dict):
        return item
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        return None
    for candidate in payload.get("items", []):
        if isinstance(candidate, dict) and str(candidate.get("id")) == str(row["article_id"]):
            return candidate
    return None


def migrate_user_content_v4(
    *, data_dir: Path | str, backup_dir: Path | str, apply: bool
) -> dict[str, Any]:
    data_path = Path(data_dir)
    db_path = data_path / "service.db"
    inspection = _inspect(db_path)
    result: dict[str, Any] = {
        "applied": False,
        "missing_content_items": inspection["missing_content_items"],
        "backup_path": None,
    }
    if not apply:
        return result
    if inspection["migrated"] and inspection["missing_content_items"] == 0:
        result["reason"] = "already_migrated"
        return result
    if _active_workers(db_path):
        raise RuntimeError("stop all horizon-worker processes before applying user content v4 migration")

    data_path.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        bootstrap = ServiceStore(data_path)
        try:
            bootstrap.initialize()
        finally:
            bootstrap.close()
    backup_path = _backup_database(db_path, Path(backup_dir))
    store = ServiceStore(data_path)
    store.initialize()
    conn = store.connect()
    content_store = UserContentStore(store)
    backfilled_keys: set[tuple[str, str, str]] = set()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT snapshot.workspace_id, snapshot.user_id, snapshot.generated_at,
                   snapshot.created_at, snapshot.payload_json,
                   feed_item.article_id, feed_item.item_json
            FROM user_feed_items AS feed_item
            JOIN user_feed_snapshots AS snapshot ON snapshot.id = feed_item.snapshot_id
            ORDER BY snapshot.created_at, snapshot.id, feed_item.position, feed_item.id
            """
        ).fetchall()
        for row in rows:
            item = _item_from_row(row)
            if item is None:
                continue
            content_store.upsert_items(
                workspace_id=str(row["workspace_id"]),
                user_id=str(row["user_id"]),
                items=[item],
                seen_at=str(row["generated_at"] or row["created_at"]),
            )
            backfilled_keys.add((str(row["workspace_id"]), str(row["user_id"]), str(row["article_id"])))
        store.mark_content_index_v4_migrated(commit=False)
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity_check = str(integrity_row[0] if integrity_row else "unknown")
        if foreign_key_errors:
            raise RuntimeError(f"foreign key check failed: {len(foreign_key_errors)} row(s)")
        if integrity_check.lower() != "ok":
            raise RuntimeError(f"integrity check failed: {integrity_check}")
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        store.close()

    result.update({
        "applied": True,
        "backup_path": str(backup_path),
        "backfilled_items": len(backfilled_keys),
        "integrity_check": integrity_check,
        "foreign_key_errors": len(foreign_key_errors),
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run or apply the additive user content v4 migration")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate_user_content_v4(data_dir=args.data_dir, backup_dir=args.backup_dir, apply=args.apply), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
