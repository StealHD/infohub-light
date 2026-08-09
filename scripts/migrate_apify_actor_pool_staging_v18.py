#!/usr/bin/env python3
"""Install ActorOps staged-pool workflow tables as global schema 20."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.migrate_apify_actor_canary_batches_v17 import _active_jobs  # noqa: E402
from scripts.migrate_apify_actor_ops_v15 import (  # noqa: E402
    _backup_database,
    _restore_database,
)
from scripts.migrate_user_feed_v2 import _active_workers  # noqa: E402
from src.storage.service_store import (  # noqa: E402
    APIFY_ACTOR_POOL_STAGING_MIGRATION_CHECKSUM,
    ServiceStore,
    apify_actor_canary_batches_v17_schema_shapes_valid,
    apify_actor_pool_staging_v18_schema_shapes_valid,
)


def migrate(
    data_dir: Path,
    *,
    apply: bool,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    database = data_dir / "service.db"
    if not database.exists():
        raise RuntimeError("service database does not exist")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        if not apify_actor_canary_batches_v17_schema_shapes_valid(connection):
            raise RuntimeError(
                "apify_actor_canary_batches_v17 migration is required first"
            )
        marker = connection.execute(
            """
            SELECT 1 FROM schema_migrations
            WHERE version = 20
              AND name = 'apify_actor_pool_staging_v18'
              AND checksum = ?
            """,
            (APIFY_ACTOR_POOL_STAGING_MIGRATION_CHECKSUM,),
        ).fetchone()
        already_ready = bool(
            marker and apify_actor_pool_staging_v18_schema_shapes_valid(connection)
        )
        if not apply:
            return {"required": not already_ready, "database": str(database)}
        workers = _active_workers(database)
        jobs = _active_jobs(database)
        if workers:
            raise RuntimeError("active workers must be stopped before migration")
        if jobs:
            raise RuntimeError("active ActorOps jobs must finish before migration")
        if already_ready:
            return {
                "required": False,
                "applied": False,
                "already_migrated": True,
                "database": str(database),
            }
    finally:
        connection.close()

    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(
        raw_backup.name.replace(
            "service-apify-actor-ops-v15-",
            "service-apify-actor-pool-staging-v18-",
            1,
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    store: ServiceStore | None = None
    connection = None
    try:
        store = ServiceStore(data_dir)
        store.initialize(prepare_apify_actor_pool_staging_v18=True)
        connection = store.connect()
        if not apify_actor_pool_staging_v18_schema_shapes_valid(connection):
            raise RuntimeError("v18 pool staging schema validation failed")
        store.mark_apify_actor_pool_staging_v18_migrated(commit=False)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("post-migration integrity checks failed")
        connection.commit()
        store.close()
    except Exception:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        if store is not None:
            store.close()
        try:
            _restore_database(
                backup_path=backup,
                db_path=database,
                original_mode=original_mode,
            )
        except Exception as restore_error:
            raise RuntimeError(
                "v18 pool staging migration failed and the pre-migration "
                "database could not be restored"
            ) from restore_error
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
