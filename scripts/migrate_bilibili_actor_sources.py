#!/usr/bin/env python3
"""Preview or apply the Bilibili data-only ActorOps cutover to one Service DB."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from src.storage.bilibili_actor_cutover import apply_cutover, cutover_counts
from src.storage.service_store import ServiceStore
from src.services.actorops.readiness import require_actorops_v2_schema
from scripts.bilibili_release_receipt import write as write_release_receipt


def _blockers(connection, database):
    jobs = connection.execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE status IN ('queued','running')"
    ).fetchone()[0]
    runs = connection.execute(
        """SELECT COUNT(*) FROM apify_actor_runs WHERE status IN (
             'reserved','starting','running','aborting','start_outcome_unknown')"""
    ).fetchone()[0]
    attempts = connection.execute(
        """SELECT COUNT(*) FROM actor_attempts_v2 WHERE status IN (
             'created','starting','registered','running','start_unknown')"""
    ).fetchone()[0]
    return {"workers": len(active_workers_fail_closed(database)), "jobs": int(jobs),
            "runs": int(runs), "attempts": int(attempts)}


def _backup(database, destination):
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = destination / f"service-bilibili-apify-{stamp}.db"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    target = sqlite3.connect(path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return path


def migrate(data_dir, *, apply=False, services_stopped=False, backup_dir=None,
            release_revision=None, release_receipt=None):
    database = Path(data_dir) / "service.db"
    if not database.is_file():
        raise RuntimeError("service database does not exist")
    preview = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    preview.row_factory = sqlite3.Row
    try:
        counts = cutover_counts(preview)
        blockers = _blockers(preview, database)
    finally:
        preview.close()
    if not (counts["bindings_required"] or counts["routes_required"]):
        return {"status": "already_applied", **counts}
    if not apply:
        return {"status": "blocked" if any(blockers.values()) else "preview", **counts, "blockers": blockers}
    if not services_stopped or any(blockers.values()):
        raise RuntimeError("stop API/Worker and drain the queue before Bilibili cutover")
    if bool(release_revision) != bool(release_receipt):
        raise ValueError("release revision and receipt must be provided together")
    if release_receipt and (not re.fullmatch('[0-9a-f]{40}', release_revision)
            or Path(release_receipt).parent != Path(data_dir).resolve() / 'backups'
            or Path(release_receipt).exists() or Path(release_receipt).is_symlink()):
        raise ValueError("new managed receipt and full release revision required")
    backup = _backup(database, Path(backup_dir) if backup_dir else Path(data_dir) / "backups")
    store = ServiceStore(data_dir)
    try:
        require_actorops_v2_schema(store)
        connection = store.connect()
        connection.execute("BEGIN IMMEDIATE")
        if any(_blockers(connection, database).values()):
            raise RuntimeError("Bilibili cutover state changed; stop services and retry")
        changes = apply_cutover(store)
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Bilibili cutover postcheck failed")
        connection.commit()
    except Exception:
        if store.connect().in_transaction:
            store.connect().rollback()
        raise
    finally:
        store.close()
    result = {"status": "applied", **changes, "backup_path": str(backup.resolve())}
    if release_receipt:
        write_release_receipt(Path(data_dir).resolve().parent, Path(release_receipt),
                              release_revision, backup.resolve())
        result["release_receipt"] = str(release_receipt)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--release-revision")
    parser.add_argument("--release-receipt", type=Path)
    args = parser.parse_args()
    try:
        result = migrate(args.data_dir, apply=args.apply, services_stopped=args.services_stopped,
                         backup_dir=args.backup_dir, release_revision=args.release_revision,
                         release_receipt=args.release_receipt)
    except (RuntimeError, ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
