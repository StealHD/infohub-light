#!/usr/bin/env python3
"""Offline normalization for the three standard Actor Route price caps."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.migrate_apify_actor_ops_v15 import (  # noqa: E402
    _backup_database,
    _restore_database,
)
from scripts.actorops_migration_safety import (  # noqa: E402
    active_actor_work,
    active_workers_fail_closed,
)
from src.services.apify_actor_ops import ApifyActorOpsService  # noqa: E402
from src.storage.apify_actor_pool_management_schema import (  # noqa: E402
    migration_required as actor_pool_management_migration_required,
)
from src.storage.service_store import (  # noqa: E402
    APIFY_ACTOR_RESILIENCE_MIGRATION_CHECKSUM,
    APIFY_ACTOR_RESILIENCE_MIGRATION_NAME,
    APIFY_ACTOR_RESILIENCE_MIGRATION_VERSION,
    ServiceStore,
)


STANDARD_ROUTE_TARGETS = {
    "youtube/channel/items": 0.10,
    "instagram/profile/items": 0.10,
}
X_ROUTE_KEY = "x/profile"
MAX_ROUTE_CAP_USD = 0.10


def _connect_read_only(database: Path, *, immutable: bool) -> sqlite3.Connection:
    suffix = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    connection = sqlite3.connect(f"{database.resolve().as_uri()}{suffix}", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _target_cap(route_key: str, current_cap: float) -> float | None:
    if route_key in STANDARD_ROUTE_TARGETS:
        return STANDARD_ROUTE_TARGETS[route_key]
    if route_key == X_ROUTE_KEY and current_cap > MAX_ROUTE_CAP_USD:
        return MAX_ROUTE_CAP_USD
    return None


def _immutable_read_safe(database: Path) -> bool:
    wal = Path(f"{database}-wal")
    return not wal.exists() or wal.stat().st_size == 0


def _inspect(database: Path, *, immutable: bool) -> list[dict[str, Any]]:
    connection = _connect_read_only(database, immutable=immutable)
    try:
        resilience_marker = connection.execute(
            """SELECT 1 FROM schema_migrations
               WHERE version = ? AND name = ? AND checksum = ?""",
            (
                APIFY_ACTOR_RESILIENCE_MIGRATION_VERSION,
                APIFY_ACTOR_RESILIENCE_MIGRATION_NAME,
                APIFY_ACTOR_RESILIENCE_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
        if not resilience_marker or actor_pool_management_migration_required(
            connection
        ):
            raise RuntimeError("current ActorOps global schema 24 is required")
        rows = connection.execute(
            """SELECT workspace_id, route_id, route_key, generation,
                      per_run_cap_usd
               FROM apify_actor_route_profiles
               WHERE route_key IN (?, ?, ?)
               ORDER BY workspace_id, route_key""",
            (*sorted(STANDARD_ROUTE_TARGETS), X_ROUTE_KEY),
        ).fetchall()
    finally:
        connection.close()
    changes: list[dict[str, Any]] = []
    for row in rows:
        current_cap = float(row["per_run_cap_usd"])
        if not math.isfinite(current_cap) or current_cap <= 0:
            raise RuntimeError(
                f"invalid stored Actor Route cap for {row['route_key']}"
            )
        target_cap = _target_cap(str(row["route_key"]), current_cap)
        changes.append(
            {
                "workspace_id": str(row["workspace_id"]),
                "route_key": str(row["route_key"]),
                "route_id": str(row["route_id"]),
                "generation": int(row["generation"]),
                "current_cap_usd": current_cap,
                "target_cap_usd": target_cap or current_cap,
                "action": (
                    "unchanged"
                    if target_cap is None
                    or current_cap == target_cap
                    else "would_update"
                ),
            }
        )
    return changes


def _backup(database: Path, destination: Path) -> Path:
    raw = _backup_database(database, destination)
    backup = raw.with_name(
        raw.name.replace(
            "service-apify-actor-ops-v15-",
            "service-route-price-caps-",
            1,
        )
    )
    raw.replace(backup)
    os.chmod(backup, 0o600)
    return backup


def migrate(
    data_dir: Path,
    *,
    apply: bool,
    backup_dir: Path | None = None,
    confirmed_stopped: bool = False,
) -> dict[str, Any]:
    database = data_dir / "service.db"
    if not database.is_file():
        raise RuntimeError("service database does not exist")
    routes = _inspect(database, immutable=not apply and _immutable_read_safe(database))
    result: dict[str, Any] = {
        "apply": bool(apply),
        "applied": False,
        "database": str(database),
        "backup": None,
        "routes": routes,
    }
    pending = [route for route in routes if route["action"] == "would_update"]
    if not apply or not pending:
        return result
    if not confirmed_stopped:
        raise RuntimeError(
            "confirm API and Worker are stopped before applying Route price caps"
        )
    if active_workers_fail_closed(database):
        raise RuntimeError(
            "active workers must stop and cross the heartbeat safety window"
        )
    if active_actor_work(database):
        raise RuntimeError("active ActorOps jobs must finish before applying caps")

    original_mode = database.stat().st_mode & 0o777
    backup = _backup(database, backup_dir or data_dir / "backups")
    store = ServiceStore(data_dir)
    connection = store.connect()
    committed = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        for route in pending:
            ops = ApifyActorOpsService(
                store,
                workspace_id=str(route["workspace_id"]),
            )
            updated = ops.set_route_price_cap(
                str(route["route_id"]),
                per_run_cap_usd=float(route["target_cap_usd"]),
                expected_generation=int(route["generation"]),
            )
            route["action"] = "updated"
            route["new_cap_usd"] = float(updated["per_run_cap_usd"])
            route["new_generation"] = int(updated["generation"])
        connection.commit()
        committed = True
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("post-update SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("post-update foreign key check failed")
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        store.close()
        if committed:
            _restore_database(
                backup_path=backup,
                db_path=database,
                original_mode=original_mode,
            )
        raise
    store.close()
    os.chmod(backup, 0o600)
    result.update(
        applied=True,
        backup=str(backup),
        backup_mode=oct(backup.stat().st_mode & 0o777),
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-stopped",
        action="store_true",
        help="Confirm horizon-api and horizon-worker are stopped",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            migrate(
                args.data_dir,
                apply=args.apply,
                backup_dir=args.backup_dir,
                confirmed_stopped=args.confirm_stopped,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
