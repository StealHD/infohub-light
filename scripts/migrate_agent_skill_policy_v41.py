#!/usr/bin/env python3
"""Explicit offline installer for global 41 workspace Skill authorization."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database, _restore_database
from src.storage.agent_skill_policy_schema import (
    MIGRATION_CHECKSUM, MIGRATION_NAME, MIGRATION_VERSION, TABLES,
    apply_migration, migration_marker_exists, prerequisite_ready, schema_shapes_valid,
)


def _connect(path: Path, *, read_only: bool):
    target = f"file:{path}?mode=ro" if read_only else path
    connection = sqlite3.connect(target, uri=read_only)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _state(connection):
    row = connection.execute("SELECT name,checksum FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)).fetchone()
    if row:
        if tuple(row) != (MIGRATION_NAME, MIGRATION_CHECKSUM) or not schema_shapes_valid(connection):
            raise RuntimeError("global 41 is occupied or invalid")
        return "ready"
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 40 is required")
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if existing & set(TABLES):
        raise RuntimeError("partial agent Skill policy schema must be restored")
    return "required"


def preview(data_dir: Path):
    database = data_dir / "service.db"
    if not database.is_file():
        raise RuntimeError("service database does not exist")
    connection = _connect(database, read_only=True)
    try:
        state = _state(connection)
        workspaces = connection.execute("SELECT count(*) FROM workspaces").fetchone()[0]
        bindings = connection.execute("SELECT count(*) FROM agent_connections WHERE state<>'revoked'").fetchone()[0]
    finally:
        connection.close()
    workers = active_workers_fail_closed(database)
    return {"status": "already_migrated" if state == "ready" else "blocked" if workers else "migration_required",
            "required": state != "ready", "workspaces": workspaces, "bindings": bindings,
            "blocker_counts": {"workers": len(workers)} if workers else {}}


def migrate(data_dir: Path, *, apply: bool, backup_dir: Path | None = None):
    database = data_dir / "service.db"
    result = preview(data_dir)
    if not apply or result["status"] == "already_migrated":
        return result
    if result["status"] == "blocked":
        raise RuntimeError("API and Worker must stop before global 41 migration")
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, backup_dir or data_dir / "backups")
    backup = raw_backup.with_name(raw_backup.name.replace("service-apify-actor-ops-v15-", "service-agent-skill-policy-v41-", 1))
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection = None
    try:
        connection = _connect(database, read_only=False)
        _state(connection)
        if active_workers_fail_closed(database):
            raise RuntimeError("API and Worker must stop before global 41 migration")
        changes = apply_migration(connection)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok" or connection.execute("PRAGMA foreign_key_check").fetchone() or not migration_marker_exists(connection):
            raise RuntimeError("post-migration checks failed")
        connection.close()
        connection = None
    except Exception:
        if connection is not None:
            connection.close()
        _restore_database(backup_path=backup, db_path=database, original_mode=original_mode)
        raise
    return {"status": "applied", "required": False, "backup": str(backup),
            "backup_mode": "0o600", "integrity_check": "ok", "foreign_key_violations": 0, **changes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = migrate(args.data_dir, apply=args.apply, backup_dir=args.backup_dir)
    except (RuntimeError, OSError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
