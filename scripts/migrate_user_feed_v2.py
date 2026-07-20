#!/usr/bin/env python3
"""Explicit destructive reset required before enabling user-feed schema v2."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.storage.service_store import ServiceStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _inspect_database(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "database_exists": False,
            "migrated": False,
            "migration_required": False,
            "snapshot_count": 0,
            "item_count": 0,
            "state_count": 0,
            "feedback_count": 0,
            "pending_feed_job_count": 0,
        }
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        snapshot_count = (
            int(connection.execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0])
            if _table_exists(connection, "user_feed_snapshots")
            else 0
        )
        item_count = (
            int(connection.execute("SELECT COUNT(*) FROM user_feed_items").fetchone()[0])
            if _table_exists(connection, "user_feed_items")
            else 0
        )
        state_count = (
            int(connection.execute("SELECT COUNT(*) FROM user_item_state").fetchone()[0])
            if _table_exists(connection, "user_item_state")
            else 0
        )
        feedback_count = (
            int(connection.execute("SELECT COUNT(*) FROM user_item_feedback").fetchone()[0])
            if _table_exists(connection, "user_item_feedback")
            else 0
        )
        pending_feed_job_count = (
            int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM fetch_jobs
                    WHERE job_type IN ('source_fetch', 'user_feed_refresh')
                      AND status IN ('queued', 'running')
                    """
                ).fetchone()[0]
            )
            if _table_exists(connection, "fetch_jobs")
            else 0
        )
        migrated = bool(
            _table_exists(connection, "schema_migrations")
            and connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 2"
            ).fetchone()
        )
    finally:
        connection.close()
    return {
        "database_exists": True,
        "migrated": migrated,
        "migration_required": bool(
            not migrated
            and any(
                (
                    snapshot_count,
                    item_count,
                    state_count,
                    feedback_count,
                    pending_feed_job_count,
                )
            )
        ),
        "snapshot_count": snapshot_count,
        "item_count": item_count,
        "state_count": state_count,
        "feedback_count": feedback_count,
        "pending_feed_job_count": pending_feed_job_count,
    }


def _active_workers(db_path: Path, *, stale_seconds: float = 35.0) -> list[str]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if not _table_exists(connection, "worker_heartbeats"):
            return []
        rows = connection.execute(
            "SELECT worker_id, state, heartbeat_at FROM worker_heartbeats"
        ).fetchall()
    finally:
        connection.close()
    now = datetime.now(timezone.utc)
    active: list[str] = []
    for row in rows:
        try:
            heartbeat_at = datetime.fromisoformat(str(row["heartbeat_at"]).replace("Z", "+00:00"))
            if heartbeat_at.tzinfo is None:
                heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if row["state"] != "stopping" and (now - heartbeat_at.astimezone(timezone.utc)).total_seconds() < stale_seconds:
            active.append(str(row["worker_id"]))
    return active


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(target, 0o600)
    return target


def migrate_feed_v2(
    *,
    data_dir: Path | str,
    backup_dir: Path | str,
    apply: bool,
) -> dict[str, Any]:
    data_path = Path(data_dir)
    db_path = data_path / "service.db"
    inspection = _inspect_database(db_path)
    result: dict[str, Any] = {
        "applied": False,
        "migration_required": inspection["migration_required"],
        "snapshot_count": inspection["snapshot_count"],
        "item_count": inspection["item_count"],
        "state_count": inspection["state_count"],
        "feedback_count": inspection["feedback_count"],
        "pending_feed_job_count": inspection["pending_feed_job_count"],
        "backup_path": None,
    }
    if not apply:
        return result
    if not inspection["migration_required"]:
        result["reason"] = "already_migrated" if inspection["migrated"] else "no_legacy_feed_data"
        return result

    active_workers = _active_workers(db_path)
    if active_workers:
        raise RuntimeError("stop all horizon-worker processes before applying feed v2 migration")

    backup_path = _backup_database(db_path, Path(backup_dir))
    store = ServiceStore(data_path)
    store.initialize()
    conn = store.connect()
    now = _now_iso()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cancelled = conn.execute(
            """
            UPDATE fetch_jobs
            SET status = 'cancelled',
                worker_id = NULL,
                claim_token = NULL,
                locked_until = NULL,
                error_code = 'feed_v2_migration',
                error_message = 'Job cancelled by user feed v2 migration',
                cancelled_at = ?,
                finished_at = ?,
                updated_at = ?
            WHERE job_type IN ('source_fetch', 'user_feed_refresh')
              AND status IN ('queued', 'running')
            """,
            (now, now, now),
        ).rowcount
        deleted_feedback = conn.execute("DELETE FROM user_item_feedback").rowcount
        deleted_state = conn.execute("DELETE FROM user_item_state").rowcount
        deleted_items = conn.execute("DELETE FROM user_feed_items").rowcount
        deleted_snapshots = conn.execute("DELETE FROM user_feed_snapshots").rowcount
        conn.execute("DROP INDEX IF EXISTS idx_user_feed_snapshots_job_id")
        conn.execute("DROP INDEX IF EXISTS idx_user_feed_items_snapshot_article")
        conn.execute(
            """
            CREATE UNIQUE INDEX idx_user_feed_snapshots_job_id
                ON user_feed_snapshots(job_id)
                WHERE job_id IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX idx_user_feed_items_snapshot_article
                ON user_feed_items(snapshot_id, article_id)
            """
        )
        store.mark_feed_v2_migrated(commit=False)
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"foreign key check failed: {len(foreign_key_errors)} row(s)")
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise

    result.update(
        {
            "applied": True,
            "migration_required": False,
            "backup_path": str(backup_path),
            "cancelled_jobs": cancelled,
            "deleted_feedback": deleted_feedback,
            "deleted_state": deleted_state,
            "deleted_items": deleted_items,
            "deleted_snapshots": deleted_snapshots,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or apply the user feed v2 reset migration")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate_feed_v2(
                data_dir=args.data_dir,
                backup_dir=args.backup_dir,
                apply=args.apply,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
