#!/usr/bin/env python3
"""Backfill stable content time/search fields with a pre-change SQLite backup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.migrate_user_feed_v2 import _active_workers
from src.services.content_timeline import build_search_text, resolve_effective_at
from src.services.user_content_store import UserContentStore
from src.storage.service_store import ServiceStore


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "database_exists": False,
            "content_count": 0,
            "pending_count": 0,
            "migrated": False,
        }
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        columns = _columns(connection, "user_content_items")
        content_count = (
            int(connection.execute("SELECT COUNT(*) FROM user_content_items").fetchone()[0])
            if columns
            else 0
        )
        if {"effective_at", "search_text"} <= columns:
            pending_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM user_content_items
                    WHERE effective_at = '' OR search_text = ''
                    """
                ).fetchone()[0]
            )
        else:
            pending_count = content_count
        migrated = bool(
            _table_exists(connection, "schema_migrations")
            and connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 11"
            ).fetchone()
        )
    finally:
        connection.close()
    return {
        "database_exists": True,
        "content_count": content_count,
        "pending_count": pending_count,
        "migrated": migrated,
    }


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-content-v11-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(target, 0o600)
    return target


def migrate_content_timeline_v11(
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
        "content_count": inspection["content_count"],
        "pending_count": inspection["pending_count"],
        "backup_path": None,
    }
    if not apply:
        return result
    if inspection["migrated"] and inspection["pending_count"] == 0:
        result["reason"] = "already_migrated"
        return result
    if db_path.exists() and _active_workers(db_path):
        raise RuntimeError(
            "stop all horizon-worker processes before applying content timeline v11"
        )

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
    backfilled = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT * FROM user_content_items
            WHERE effective_at = '' OR search_text = ''
            ORDER BY created_at, id
            """
        ).fetchall()
        migration_now = datetime.now(timezone.utc)
        for row in rows:
            try:
                item = json.loads(str(row["item_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                item = {}
            item = item if isinstance(item, dict) else {}
            effective_at = (
                str(row["effective_at"] or "")
                or resolve_effective_at(
                    item,
                    first_seen_at=row["first_seen_at"],
                    now=migration_now,
                )
            )
            search_text = build_search_text(
                item,
                body_text=row["body_text"],
                source_native_title=row["source_native_title"],
                include_body=not bool(row["archived_at"]),
            )
            conn.execute(
                """
                UPDATE user_content_items
                SET effective_at = ?, search_text = ?, updated_at = updated_at
                WHERE id = ?
                """,
                (effective_at, search_text, row["id"]),
            )
            backfilled += 1
        indexed = UserContentStore(store).rebuild_search_index()
        store.mark_content_timeline_v11_migrated(commit=False)
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        integrity_check = str(integrity_row[0] if integrity_row else "unknown")
        if foreign_key_errors:
            raise RuntimeError(
                f"foreign key check failed: {len(foreign_key_errors)} row(s)"
            )
        if integrity_check.casefold() != "ok":
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
            "backfilled_count": backfilled,
            "indexed_count": indexed,
            "integrity_check": integrity_check,
            "foreign_key_errors": len(foreign_key_errors),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply the content timeline/search v11 migration"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate_content_timeline_v11(
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
