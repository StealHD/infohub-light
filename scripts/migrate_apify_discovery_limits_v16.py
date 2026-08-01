#!/usr/bin/env python3
"""Install Discovery AI token measurement fields with an offline backup."""

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

from scripts.migrate_apify_actor_ops_v15 import (  # noqa: E402
    _active_actor_ops_jobs,
    _backup_database,
    _restore_database,
    _v15_schema_ready,
)
from scripts.migrate_user_feed_v2 import _active_workers  # noqa: E402
from src.storage.service_store import (  # noqa: E402
    ServiceStore,
    apify_discovery_limits_v16_schema_shapes_valid,
)


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
        if not _v15_schema_ready(connection, require_marker=True):
            raise RuntimeError("apify_actor_ops_v15 migration is required first")
        already_ready = apify_discovery_limits_v16_schema_shapes_valid(connection)
        if not apply:
            return {"required": not already_ready, "database": str(database)}
        workers = _active_workers(database)
        jobs = _active_actor_ops_jobs(database)
        if workers:
            raise RuntimeError("active workers must be stopped before migration")
        if jobs:
            raise RuntimeError("active discovery/canary jobs must finish before migration")
    finally:
        connection.close()

    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(
        raw_backup.name.replace(
            "service-apify-actor-ops-v15-",
            "service-apify-discovery-limits-v16-",
            1,
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    try:
        store = ServiceStore(data_dir)
        store.initialize(prepare_apify_discovery_limits_v16=True)
        connection = store.connect()
        if not apify_discovery_limits_v16_schema_shapes_valid(connection):
            raise RuntimeError("v16 schema validation failed")
        store.mark_apify_discovery_limits_v16_migrated(commit=False)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("post-migration integrity checks failed")
        connection.commit()
        store.close()
    except Exception:
        _restore_database(
            backup_path=backup,
            db_path=database,
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
