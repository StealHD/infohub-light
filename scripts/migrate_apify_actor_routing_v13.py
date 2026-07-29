#!/usr/bin/env python3
"""Install the additive Apify Actor routing and alert schema with a backup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.migrate_user_feed_v2 import _active_workers
from src.storage.service_store import ServiceStore


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"database_exists": False, "migrated": False}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        has_migrations = bool(
            connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_migrations'
                """
            ).fetchone()
        )
        migrated = bool(
            has_migrations
            and connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 13"
            ).fetchone()
        )
    finally:
        connection.close()
    return {"database_exists": True, "migrated": migrated}


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-apify-routing-v13-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(target, 0o600)
    return target


def migrate_apify_actor_routing_v13(
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
        "database_exists": inspection["database_exists"],
        "migrated": inspection["migrated"],
        "backup_path": None,
    }
    if not apply:
        return result
    if inspection["migrated"]:
        result["reason"] = "already_migrated"
        return result
    if db_path.exists() and _active_workers(db_path):
        raise RuntimeError(
            "stop all horizon-worker processes before applying Apify routing v13"
        )

    data_path.mkdir(parents=True, exist_ok=True)
    backup_path = (
        _backup_database(db_path, Path(backup_dir))
        if db_path.exists()
        else None
    )
    store = ServiceStore(data_path)
    try:
        store.initialize(prepare_apify_actor_routing_v13=True)
        connection = store.connect()
        route_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM apify_actor_routes"
            ).fetchone()[0]
        )
        candidate_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM apify_actor_candidates"
            ).fetchone()[0]
        )
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity_check = str(integrity_row[0] if integrity_row else "unknown")
        if foreign_key_errors:
            raise RuntimeError(
                f"foreign key check failed: {len(foreign_key_errors)} row(s)"
            )
        if integrity_check.casefold() != "ok":
            raise RuntimeError(f"integrity check failed: {integrity_check}")
        store.mark_apify_actor_routing_v13_migrated(commit=True)
        marker = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = 13"
        ).fetchone()
        if marker is None:
            raise RuntimeError("Apify routing v13 marker was not installed")
    finally:
        store.close()

    result.update(
        {
            "applied": True,
            "migrated": True,
            "backup_path": str(backup_path) if backup_path else None,
            "route_count": route_count,
            "candidate_count": candidate_count,
            "integrity_check": integrity_check,
            "foreign_key_errors": len(foreign_key_errors),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply the additive Apify Actor routing v13 migration"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate_apify_actor_routing_v13(
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
