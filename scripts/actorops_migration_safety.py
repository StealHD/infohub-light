"""Fail-closed offline guards shared by ActorOps migrations and repairs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def active_workers_fail_closed(
    database: Path,
    *,
    stale_seconds: float = 35.0,
    now: datetime | None = None,
) -> list[str]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'worker_heartbeats'"
        ).fetchone()
        rows = connection.execute(
            "SELECT worker_id, heartbeat_at FROM worker_heartbeats"
        ).fetchall() if exists else []
    finally:
        connection.close()
    current = now or datetime.now(timezone.utc)
    active: list[str] = []
    for row in rows:
        try:
            heartbeat = datetime.fromisoformat(
                str(row["heartbeat_at"]).replace("Z", "+00:00")
            )
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            active.append(str(row["worker_id"]))
            continue
        if (current - heartbeat.astimezone(timezone.utc)).total_seconds() < stale_seconds:
            active.append(str(row["worker_id"]))
    return active


def active_actor_work(database: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        jobs = connection.execute(
            """SELECT id, job_type, status FROM fetch_jobs
               WHERE job_type IN (
                   'apify_actor_discovery', 'apify_actor_validation',
                   'apify_actor_canary_batch', 'apify_actor_freshness_check'
               ) AND status IN ('queued', 'running')"""
        ).fetchall()
        runs = connection.execute(
            """SELECT id, 'apify_actor_run' AS job_type, status
               FROM apify_actor_runs
               WHERE status IN ('reserved', 'starting', 'running', 'aborting',
                                'start_outcome_unknown')"""
        ).fetchall()
        return [dict(row) for row in (*jobs, *runs)]
    finally:
        connection.close()


__all__ = ["active_actor_work", "active_workers_fail_closed"]
