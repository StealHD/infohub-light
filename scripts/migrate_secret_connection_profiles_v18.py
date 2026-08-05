#!/usr/bin/env python3
"""Add per-AI-key Base URL metadata with an offline SQLite backup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.migrate_user_feed_v2 import (  # noqa: E402
    _active_workers,
    _backup_database,
)


def _has_base_url_column(connection: sqlite3.Connection) -> bool:
    columns = connection.execute("PRAGMA table_info(secret_refs)").fetchall()
    return any(str(column[1]) == "base_url" for column in columns)


def _active_jobs(connection: sqlite3.Connection) -> list[str]:
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'fetch_jobs'"
    ).fetchall()
    if not tables:
        return []
    rows = connection.execute(
        "SELECT id FROM fetch_jobs WHERE status = 'running' ORDER BY id"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _restore_database(*, backup: Path, database: Path, original_mode: int) -> None:
    source = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    destination = sqlite3.connect(database)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(database, original_mode)


def migrate(
    data_dir: Path,
    *,
    apply: bool,
    backup_dir: Path | None = None,
) -> dict[str, object]:
    database = data_dir / "service.db"
    if not database.exists():
        raise RuntimeError("service database does not exist")

    connection = sqlite3.connect(database)
    try:
        required = not _has_base_url_column(connection)
        if not apply:
            return {"required": required, "database": str(database)}
        if not required:
            return {"required": False, "applied": False, "database": str(database)}
        workers = _active_workers(database)
        jobs = _active_jobs(connection)
        if workers:
            raise RuntimeError("active workers must be stopped before migration")
        if jobs:
            raise RuntimeError("running jobs must finish before migration")
    finally:
        connection.close()

    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(
        raw_backup.name.replace("service-", "service-secret-connection-profiles-v18-", 1)
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    try:
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "ALTER TABLE secret_refs ADD COLUMN base_url TEXT NOT NULL DEFAULT ''"
            )
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity.casefold() != "ok" or foreign_keys:
                raise RuntimeError("post-migration integrity checks failed")
            connection.commit()
        finally:
            connection.close()
    except Exception:
        _restore_database(
            backup=backup,
            database=database,
            original_mode=original_mode,
        )
        raise

    os.chmod(backup, 0o600)
    return {
        "required": False,
        "applied": True,
        "backup": str(backup),
        "backup_mode": oct(backup.stat().st_mode & 0o777),
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, apply=args.apply, backup_dir=args.backup_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
