"""Actor maintenance work that runs before the Worker claims a job."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .job_queue import JobQueue
from ..storage.service_store import ServiceStore


def promote_due_actor_revisions(store: ServiceStore) -> dict[str, int]:
    """Re-evaluate the 48-hour certification window without paid retries."""

    from .apify_actor_ops import ApifyActorOpsService

    promoted = 0
    pending = 0
    workspaces = store.connect().execute(
        "SELECT id FROM workspaces ORDER BY created_at, id"
    ).fetchall()
    for workspace in workspaces:
        result = ApifyActorOpsService(
            store,
            workspace_id=str(workspace["id"]),
        ).promote_eligible_revisions()
        promoted += int(result["promoted"])
        pending += int(result["pending"])
    return {"promoted": promoted, "pending": pending}


def reconcile_and_enqueue_actor_discoveries(
    store: ServiceStore,
    queue: JobQueue,
) -> dict[str, int]:
    """Recover free discovery work without replaying any paid Canary."""

    from .apify_actor_capability_matrix import reconcile_registered_route_policies
    from .youtube_actor_source import provision_youtube_actor_sources

    policy_updates = {"routes": 0, "bindings": 0, "deferred": 0}
    now = datetime.now(timezone.utc).isoformat()
    connection = store.connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        for workspace in connection.execute(
            "SELECT id FROM workspaces ORDER BY created_at, id"
        ).fetchall():
            outcome = reconcile_registered_route_policies(
                connection,
                workspace_id=str(workspace["id"]),
                now=now,
            )
            for key in policy_updates:
                policy_updates[key] += int(outcome[key])
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    provision_youtube_actor_sources(store)
    enqueued = 0
    failed = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        interrupted = connection.execute(
            """
            SELECT run.run_id
            FROM apify_actor_discovery_runs AS run
            WHERE run.stage IN (
                'searching', 'metadata', 'ranking',
                'static_validation', 'input_validation'
            )
              AND NOT EXISTS (
                  SELECT 1 FROM fetch_jobs AS job
                  WHERE job.workspace_id = run.workspace_id
                    AND job.job_type = 'apify_actor_discovery'
                    AND job.status IN ('queued', 'running')
                    AND json_extract(job.payload_json, '$.run_id') = run.run_id
              )
            """
        ).fetchall()
        for row in interrupted:
            connection.execute(
                """
                UPDATE apify_actor_discovery_runs
                SET stage = 'failed', error_code = 'discovery_interrupted',
                    updated_at = ?
                WHERE run_id = ? AND stage IN (
                    'searching', 'metadata', 'ranking',
                    'static_validation', 'input_validation'
                )
                """,
                (now, row["run_id"]),
            )
            failed += 1
        queued_runs = connection.execute(
            """
            SELECT run.run_id, run.workspace_id
            FROM apify_actor_discovery_runs AS run
            WHERE run.stage = 'queued'
              AND NOT EXISTS (
                  SELECT 1 FROM fetch_jobs AS job
                  WHERE job.workspace_id = run.workspace_id
                    AND job.job_type = 'apify_actor_discovery'
                    AND job.status IN ('queued', 'running')
                    AND json_extract(job.payload_json, '$.run_id') = run.run_id
              )
            ORDER BY run.created_at, run.run_id
            """
        ).fetchall()
        for run in queued_runs:
            actor = connection.execute(
                """
                SELECT id FROM users
                WHERE workspace_id = ? AND enabled = 1
                  AND role IN ('owner', 'admin')
                ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END,
                         created_at, id
                LIMIT 1
                """,
                (run["workspace_id"],),
            ).fetchone()
            if actor is None:
                connection.execute(
                    """
                    UPDATE apify_actor_discovery_runs
                    SET stage = 'failed',
                        error_code = 'discovery_admin_unavailable',
                        updated_at = ?
                    WHERE run_id = ? AND stage = 'queued'
                    """,
                    (now, run["run_id"]),
                )
                failed += 1
                continue
            queue.create_job(
                workspace_id=str(run["workspace_id"]),
                user_id=str(actor["id"]),
                job_type="apify_actor_discovery",
                payload={"run_id": str(run["run_id"])},
                priority=50,
                max_attempts=1,
                retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
                commit=False,
            )
            enqueued += 1
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return {
        "enqueued": enqueued,
        "failed": failed,
        "policy_routes": policy_updates["routes"],
        "policy_bindings": policy_updates["bindings"],
        "policy_deferred": policy_updates["deferred"],
    }


def enqueue_due_actor_freshness_checks(
    store: ServiceStore,
    queue: JobQueue,
) -> dict[str, int]:
    """Queue only explicitly enabled standing-authorized freshness work."""

    from .apify_actor_resilience import (
        ActorResilienceError,
        ApifyActorResilienceService,
    )

    enqueued = 0
    blocked = 0
    workspaces = store.connect().execute(
        "SELECT id FROM workspaces ORDER BY created_at, id"
    ).fetchall()
    for workspace in workspaces:
        workspace_id = str(workspace["id"])
        service = ApifyActorResilienceService(store, workspace_id=workspace_id)
        for route_id in service.due_routes():
            actor = store.connect().execute(
                """
                SELECT id FROM users
                WHERE workspace_id = ? AND enabled = 1
                  AND role IN ('owner', 'admin')
                ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END,
                         created_at, id
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            if actor is None:
                blocked += 1
                continue
            check: dict[str, Any] | None = None
            try:
                check = service.create_freshness_check(
                    route_id,
                    trigger_kind="automatic",
                    actor_user_id=str(actor["id"]),
                    cost_confirmed=True,
                )
                job = queue.create_job(
                    workspace_id=workspace_id,
                    user_id=str(actor["id"]),
                    job_type="apify_actor_freshness_check",
                    payload={"check_id": str(check["check_id"])},
                    priority=100,
                    max_attempts=1,
                    retention_days=int(
                        os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")
                    ),
                )
                service.attach_freshness_job(
                    str(check["check_id"]), str(job["id"])
                )
            except ActorResilienceError as exc:
                service.emit_event(
                    route_id=route_id,
                    phase="freshness_schedule",
                    outcome="blocked",
                    reason_code=exc.code,
                )
                blocked += 1
                continue
            except Exception:
                if check is not None:
                    service.fail_freshness_check(
                        str(check["check_id"]),
                        reason_code="freshness_job_queue_failed",
                    )
                blocked += 1
                continue
            enqueued += 1
    return {"enqueued": enqueued, "blocked": blocked}
