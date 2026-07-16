#!/usr/bin/env python3
"""Reset local Service content while preserving users, workspaces and global config."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from src.services.secret_store import SecretStore
from src.storage.service_store import ServiceStore


RESET_TABLES = (
    "user_source_health_applications",
    "user_source_health",
    "user_item_feedback",
    "user_item_state",
    "user_feed_items",
    "user_feed_snapshots",
    "user_subscriptions",
    "source_catalog",
    "usage_events",
    "worker_heartbeats",
    "fetch_jobs",
    "secret_refs",
)


def inspect_local_service(data_dir: Path | str) -> dict[str, Any]:
    store = ServiceStore(data_dir)
    store.initialize()
    try:
        counts = {
            table: int(store.connect().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in RESET_TABLES
        }
        return {
            "data_dir": str(Path(data_dir).resolve()),
            "counts": counts,
            "users": int(store.connect().execute("SELECT COUNT(*) FROM users").fetchone()[0]),
            "workspaces": int(store.connect().execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]),
        }
    finally:
        store.close()


def reset_local_service(data_dir: Path | str) -> dict[str, Any]:
    data_path = Path(data_dir)
    before = inspect_local_service(data_path)
    store = ServiceStore(data_path)
    store.initialize()
    conn = store.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE user_feed_schedules
            SET enabled = 0,
                interval_minutes = 360,
                next_run_at = NULL,
                last_evaluated_at = NULL,
                last_enqueued_at = NULL,
                last_job_id = NULL,
                last_skip_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            """
        )
        for table in RESET_TABLES:
            conn.execute(f"DELETE FROM {table}")
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"foreign key check failed: {len(foreign_key_errors)} row(s)")
        conn.commit()
        integrity_check = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity_check != "ok":
            raise RuntimeError(f"integrity check failed: {integrity_check}")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        store.close()

    secret_store = SecretStore(data_path)
    existing_names = set(secret_store.read())
    secret_store.path.unlink(missing_ok=True)
    for name in existing_names:
        os.environ.pop(name, None)

    return {
        **before,
        "applied": True,
        "integrity_check": integrity_check,
        "foreign_key_errors": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = reset_local_service(args.data_dir) if args.apply else {
        **inspect_local_service(args.data_dir),
        "applied": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
