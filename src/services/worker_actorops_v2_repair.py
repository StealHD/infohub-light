"""Low-priority coordinator for durable ActorOps route repair facts."""

from __future__ import annotations

from typing import Any

from ..storage.service_store import ServiceStore
from .actorops.readiness import require_actorops_v2_schema
from .actorops.repository import ActorOpsRepository
from .job_queue import JobQueue
from .system_settings import resolve_system_setting


def run_actorops_v2_repair(
    job: dict[str, Any], *, data_dir: str, store: ServiceStore,
) -> dict[str, Any]:
    del data_dir
    require_actorops_v2_schema(store)
    payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}
    repair_id = str(payload.get("repair_id") or "").strip()
    if set(payload) != {"repair_id"} or not repair_id:
        raise ValueError("ActorOps v2 repair job metadata is invalid")
    repository = ActorOpsRepository(store.connect(), str(job["workspace_id"]))
    repair = repository.resilience.advance_repair(repair_id)
    repository.resilience.emit(
        root_job_id=repair.get("origin_job_id"), job_id=str(job["id"]),
        route_id=str(repair["route_id"]), source_id=str(repair["source_id"]),
        candidate_id=repair.get("candidate_id"), repair_id=repair_id,
        phase="route_repair", outcome=str(repair["status"]),
        reason_code=repair.get("error_code"),
    )
    ok = str(repair["status"]) not in {"blocked", "failed", "cancelled"}
    return {
        "ok": ok,
        "_job_status": "succeeded" if ok else "failed",
        "job_type": "actorops_v2_repair", "repair_id": repair_id,
        "status": str(repair["status"]), "error_code": repair.get("error_code"),
    }


def enqueue_due_actorops_v2_repairs(
    store: ServiceStore, queue: JobQueue, *, limit: int = 10,
) -> dict[str, int]:
    """Queue bounded repair coordination; it never starts an Actor itself."""

    require_actorops_v2_schema(store)
    connection = store.connect()
    enqueued = deferred = pruned = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for workspace in connection.execute("SELECT id FROM workspaces ORDER BY id"):
            workspace_id = str(workspace["id"])
            repository = ActorOpsRepository(connection, workspace_id)
            pruned += repository.resilience.prune_execution_events()
            actor = _operator(connection, workspace_id)
            due = repository.resilience.due_repairs(limit=limit)
            if actor is None:
                deferred += len(due)
                continue
            for repair in due:
                repair_id = str(repair["repair_id"])
                if _active_job(connection, workspace_id, repair_id):
                    continue
                queue.create_job(
                    workspace_id=workspace_id, user_id=actor,
                    job_type="actorops_v2_repair", payload={"repair_id": repair_id},
                    priority=-10, max_attempts=1,
                    retention_days=int(resolve_system_setting(
                        store, workspace_id, "jobs.retention_days", connection=connection
                    )),
                    commit=False,
                )
                enqueued += 1
                if enqueued >= limit:
                    connection.commit()
                    return {"enqueued": enqueued, "deferred": deferred, "pruned": pruned}
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return {"enqueued": enqueued, "deferred": deferred, "pruned": pruned}


def _active_job(connection: Any, workspace_id: str, repair_id: str) -> bool:
    return connection.execute(
        """SELECT 1 FROM fetch_jobs WHERE workspace_id=? AND job_type='actorops_v2_repair'
           AND status IN ('queued','running')
           AND json_extract(payload_json, '$.repair_id')=? LIMIT 1""",
        (workspace_id, repair_id),
    ).fetchone() is not None


def _operator(connection: Any, workspace_id: str) -> str | None:
    row = connection.execute(
        """SELECT id FROM users WHERE workspace_id=? AND enabled=1
           AND role IN ('owner','admin') ORDER BY created_at, id LIMIT 1""",
        (workspace_id,),
    ).fetchone()
    return str(row["id"]) if row else None


__all__ = ["enqueue_due_actorops_v2_repairs", "run_actorops_v2_repair"]
