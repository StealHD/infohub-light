#!/usr/bin/env python3
"""Create a sanitized, self-contained Service database deployment artifact."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare_deployment_database(
    *,
    source: Path | str,
    output: Path | str,
) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise ValueError("deployment output must differ from the source database")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if output_path.exists():
        raise FileExistsError(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.name}.{uuid.uuid4().hex}.tmp"
    )
    now = _now_iso()
    try:
        source_db = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        target_db = sqlite3.connect(temporary_path)
        try:
            source_db.backup(target_db)
        finally:
            source_db.close()
            target_db.close()

        connection = sqlite3.connect(temporary_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            if not connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 2"
            ).fetchone():
                raise RuntimeError("source database is missing the Feed v2 migration")
            connection.execute("BEGIN IMMEDIATE")
            sessions_removed = connection.execute("DELETE FROM sessions").rowcount
            has_agent_delegations = bool(
                connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'agent_delegations'
                    """
                ).fetchone()
            )
            has_agent_change_proposals = bool(
                connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'agent_change_proposals'
                    """
                ).fetchone()
            )
            agent_change_proposals_removed = (
                connection.execute("DELETE FROM agent_change_proposals").rowcount
                if has_agent_change_proposals
                else 0
            )
            agent_delegations_removed = (
                connection.execute("DELETE FROM agent_delegations").rowcount
                if has_agent_delegations
                else 0
            )
            heartbeats_removed = connection.execute(
                "DELETE FROM worker_heartbeats"
            ).rowcount
            jobs_cancelled = connection.execute(
                """
                UPDATE fetch_jobs
                SET status = 'cancelled',
                    worker_id = NULL,
                    claim_token = NULL,
                    locked_until = NULL,
                    error_code = 'rc1_deployment',
                    error_message = 'Job cancelled while preparing the RC1 deployment database',
                    cancelled_at = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (now, now, now),
            ).rowcount
            foreign_key_errors = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if foreign_key_errors:
                raise RuntimeError(
                    f"foreign key check failed: {len(foreign_key_errors)} row(s)"
                )
            connection.commit()
            connection.execute("PRAGMA journal_mode = DELETE")
            integrity_check = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
            if integrity_check != "ok":
                raise RuntimeError(f"integrity check failed: {integrity_check}")
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, output_path)
        for suffix in ("-wal", "-shm"):
            Path(str(output_path) + suffix).unlink(missing_ok=True)
        return {
            "output": str(output_path),
            "size_bytes": output_path.stat().st_size,
            "sessions_removed": sessions_removed,
            "agent_change_proposals_removed": agent_change_proposals_removed,
            "agent_delegations_removed": agent_delegations_removed,
            "heartbeats_removed": heartbeats_removed,
            "jobs_cancelled": jobs_cancelled,
            "integrity_check": integrity_check,
            "foreign_key_errors": 0,
            "feed_v2_migrated": True,
        }
    except Exception:
        temporary_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(temporary_path) + suffix).unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a sanitized Service database for an RC deployment."
    )
    parser.add_argument("--source", default="data/service.db")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare_deployment_database(source=args.source, output=args.output),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
