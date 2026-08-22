#!/usr/bin/env python3
"""Install provider-aware Service Webhook settings with a safe backup."""

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

from scripts.migrate_user_feed_v2 import _active_workers
from src.storage.service_store import (
    ServiceStore,
    WEBHOOK_PROVIDERS,
    WEBHOOK_PROVIDER_TRIGGER_NAMES,
)


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "database_exists": False,
            "v13_migrated": False,
            "migrated": False,
        }
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    schema_ready = False
    try:
        has_migrations = bool(
            connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_migrations'
                """
            ).fetchone()
        )
        versions = (
            {
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            if has_migrations
            else set()
        )
        if 14 in versions:
            try:
                _validate_rows(
                    connection,
                    "user_notification_settings",
                )
                _validate_rows(
                    connection,
                    "apify_actor_alert_settings",
                )
                installed_triggers = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type = 'trigger'
                        """
                    ).fetchall()
                }
                schema_ready = bool(
                    WEBHOOK_PROVIDER_TRIGGER_NAMES
                    <= installed_triggers
                )
            except (RuntimeError, sqlite3.DatabaseError):
                schema_ready = False
    finally:
        connection.close()
    return {
        "database_exists": True,
        "v13_migrated": 13 in versions,
        "migrated": 14 in versions,
        "schema_ready": schema_ready,
    }


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-webhook-providers-v14-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(target, 0o600)
    return target


def _validate_rows(connection: sqlite3.Connection, table: str) -> int:
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }
    required = {
        "webhook_provider",
        "webhook_signing_env_name",
        "webhook_signing_secret_digest",
    }
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(
            f"{table} is missing webhook provider columns: {', '.join(missing)}"
        )
    placeholders = ",".join("?" for _value in WEBHOOK_PROVIDERS)
    invalid_provider = connection.execute(
        f"""
        SELECT COUNT(*) FROM {table}
        WHERE webhook_provider NOT IN ({placeholders})
        """,
        tuple(sorted(WEBHOOK_PROVIDERS)),
    ).fetchone()
    invalid_pairs = connection.execute(
        f"""
        SELECT COUNT(*) FROM {table}
        WHERE
            (webhook_signing_env_name IS NULL)
            != (webhook_signing_secret_digest IS NULL)
        """
    ).fetchone()
    invalid_count = int(invalid_provider[0] if invalid_provider else 0)
    invalid_count += int(invalid_pairs[0] if invalid_pairs else 0)
    invalid_signing = connection.execute(
        f"""
        SELECT COUNT(*) FROM {table}
        WHERE webhook_signing_env_name IS NOT NULL
          AND (
              webhook_provider NOT IN ('feishu_lark_v2', 'dingtalk')
              OR length(webhook_signing_secret_digest) != 64
              OR webhook_signing_secret_digest GLOB '*[^0-9a-f]*'
          )
        """
    ).fetchone()
    invalid_count += int(invalid_signing[0] if invalid_signing else 0)
    if invalid_count:
        raise RuntimeError(
            f"{table} contains {invalid_count} invalid provider row(s)"
        )
    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0] if row else 0)


def migrate_webhook_providers_v14(
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
        "v13_migrated": inspection["v13_migrated"],
        "migrated": inspection["migrated"],
        "schema_ready": inspection.get("schema_ready", False),
        "backup_path": None,
    }
    if not apply:
        return result
    if inspection["migrated"] and inspection.get("schema_ready"):
        result["reason"] = "already_migrated"
        return result
    if db_path.exists() and _active_workers(db_path):
        raise RuntimeError(
            "stop all horizon-worker processes before applying Webhook providers v14"
        )

    data_path.mkdir(parents=True, exist_ok=True)
    backup_path = (
        _backup_database(db_path, Path(backup_dir))
        if db_path.exists()
        else None
    )
    store = ServiceStore(data_path)
    try:
        store.initialize(prepare_webhook_providers_v14=True)
        connection = store.connect()
        connection.execute("BEGIN IMMEDIATE")
        user_setting_count = _validate_rows(
            connection,
            "user_notification_settings",
        )
        apify_setting_count = _validate_rows(
            connection,
            "apify_actor_alert_settings",
        )
        connection.execute(
            """
            UPDATE user_notification_settings
            SET last_test_status = NULL,
                last_tested_at = NULL,
                last_test_error_code = NULL
            WHERE channel = 'webhook'
            """
        )
        connection.execute(
            """
            UPDATE apify_actor_alert_settings
            SET last_test_status = NULL,
                last_test_generation = NULL,
                last_tested_at = NULL,
                last_test_error_code = NULL
            WHERE channel = 'webhook'
            """
        )
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        integrity_row = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()
        integrity_check = str(
            integrity_row[0] if integrity_row else "unknown"
        )
        if foreign_key_errors:
            raise RuntimeError(
                f"foreign key check failed: {len(foreign_key_errors)} row(s)"
            )
        if integrity_check.casefold() != "ok":
            raise RuntimeError(
                f"integrity check failed: {integrity_check}"
            )
        store.mark_webhook_providers_v14_migrated(commit=False)
        connection.commit()
        marker = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = 14"
        ).fetchone()
        if marker is None:
            raise RuntimeError("Webhook providers v14 marker was not installed")
        if store.webhook_providers_v14_migration_required():
            raise RuntimeError(
                "Webhook providers v14 schema verification failed"
            )
    except Exception:
        if store.connect().in_transaction:
            store.connect().rollback()
        raise
    finally:
        store.close()

    result.update(
        {
            "applied": True,
            "migrated": True,
            "schema_ready": True,
            "backup_path": str(backup_path) if backup_path else None,
            "user_setting_count": user_setting_count,
            "apify_setting_count": apify_setting_count,
            "integrity_check": integrity_check,
            "foreign_key_errors": len(foreign_key_errors),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply the additive Webhook providers v14 migration"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate_webhook_providers_v14(
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
