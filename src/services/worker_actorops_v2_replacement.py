"""Low-priority Worker boundary for explicit, serial v2 Actor replacements."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from ..scrapers.apify_client import ApifyClient
from ..storage.service_store import ServiceStore
from .actorops.adapters import build_default_registry
from .actorops.apify_remote import ApifyV2RemoteClient
from .actorops.readiness import require_actorops_v2_schema
from .actorops.replacement import ActorOpsReplacementRunner
from .actorops.repository import ActorOpsRepository
from .apify_pool_runtime import apify_coordinator_for_workspace
from .job_queue import JobQueue
from .worker_actorops_v2_discovery import _catalog
from .system_settings import resolve_system_setting


@dataclass(frozen=True, slots=True)
class WorkerActorOpsV2ReplacementPorts:
    run_plan: Callable[[dict[str, Any], str, ServiceStore], object]


def run_actorops_v2_replacement(
    job: dict[str, Any], *, data_dir: str, store: ServiceStore,
    ports: WorkerActorOpsV2ReplacementPorts | None = None,
) -> dict[str, Any]:
    require_actorops_v2_schema(store)
    payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}
    plan_id = str(payload.get("plan_id") or "").strip()
    if set(payload) != {"plan_id"} or not plan_id:
        raise ValueError("ActorOps v2 replacement job metadata is invalid")
    runner = (ports or WorkerActorOpsV2ReplacementPorts(_run_plan)).run_plan
    result = asyncio.run(runner(job, data_dir, store))
    if not isinstance(result, dict):
        raise RuntimeError("ActorOps v2 replacement result is invalid")
    return {"ok": result.get("status") not in {"failed", "recovery_required"}, "job_type": "actorops_v2_replacement", **result}


async def _run_plan(job: dict[str, Any], data_dir: str, store: ServiceStore) -> dict[str, object]:
    workspace_id = str(job["workspace_id"])
    repository = ActorOpsRepository(store.connect(), workspace_id)
    plan_id = str(job["payload_json"]["plan_id"])
    plan = repository.operator.get_plan(plan_id)
    sources: dict[str, dict[str, object]] = {}
    for source_id, _version, _fingerprint in repository.operator.binding_set(plan.route_id):
        source = store.get_source(source_id)
        config = source.get("config") if source else None
        if not isinstance(config, dict):
            return {"status": "failed", "plan_id": plan_id, "error_code": "actorops_replacement_source_missing"}
        sources[source_id] = config
    # Replacement is an explicit Candidate validation, not a production
    # acquisition purpose.  The shared pool accepts only those two purposes.
    coordinator = apify_coordinator_for_workspace(store, workspace_id=workspace_id, data_dir=data_dir, purpose="validation")
    if coordinator is None:
        return {"status": "failed", "plan_id": plan_id, "error_code": "actorops_replacement_credential_unavailable"}
    catalog = _catalog(store, workspace_id, data_dir)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
        remote = ApifyV2RemoteClient(ApifyClient(coordinator=coordinator, http_client=client))
        return await ActorOpsReplacementRunner(repository, build_default_registry(), remote, catalog).run(plan_id, sources)


def enqueue_due_actorops_v2_replacements(store: ServiceStore, queue: JobQueue, *, limit: int = 5) -> dict[str, int]:
    """Only queue explicit authorized/running plans after normal Jobs have priority."""

    require_actorops_v2_schema(store)
    connection = store.connect()
    enqueued = deferred = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for workspace in connection.execute("SELECT id FROM workspaces ORDER BY id"):
            workspace_id = str(workspace["id"])
            repository = ActorOpsRepository(connection, workspace_id)
            actor = _operator(connection, workspace_id)
            if actor is None:
                deferred += len(repository.operator.list_due_plans(limit=limit))
                continue
            for plan in repository.operator.list_due_plans(limit=limit):
                if _active_job(connection, workspace_id, plan.plan_id):
                    continue
                queue.create_job(
                    workspace_id=workspace_id, user_id=actor, job_type="actorops_v2_replacement",
                    payload={"plan_id": plan.plan_id}, priority=-10, max_attempts=1,
                    retention_days=int(resolve_system_setting(
                        store, workspace_id, "jobs.retention_days", connection=connection
                    )), commit=False,
                )
                enqueued += 1
                if enqueued >= limit:
                    connection.commit()
                    return {"enqueued": enqueued, "deferred": deferred}
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return {"enqueued": enqueued, "deferred": deferred}


def _active_job(connection: Any, workspace_id: str, plan_id: str) -> bool:
    return connection.execute(
        """SELECT 1 FROM fetch_jobs WHERE workspace_id=? AND job_type='actorops_v2_replacement'
           AND status IN ('queued','running') AND json_extract(payload_json, '$.plan_id')=? LIMIT 1""",
        (workspace_id, plan_id),
    ).fetchone() is not None


def _operator(connection: Any, workspace_id: str) -> str | None:
    row = connection.execute(
        """SELECT id FROM users WHERE workspace_id=? AND enabled=1 AND role IN ('owner','admin')
           ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END, created_at, id LIMIT 1""",
        (workspace_id,),
    ).fetchone()
    return str(row["id"]) if row else None


__all__ = [
    "WorkerActorOpsV2ReplacementPorts", "enqueue_due_actorops_v2_replacements",
    "run_actorops_v2_replacement",
]
