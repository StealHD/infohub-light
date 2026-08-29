"""Low-priority Worker boundary for bounded v2 standing maintenance."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from ..scrapers.apify_client import ApifyClient
from ..storage.service_store import ServiceStore
from .actorops.adapters import build_default_registry
from .actorops.apify_remote import ApifyV2RemoteClient
from .actorops.maintenance import ActorOpsProber, ProbeResult
from .actorops.ports import ProbePreflightResult
from .actorops.recovery_probe import (
    RECOVERY_INTENT,
    valid_recovery_job_payload,
)
from .actorops.readiness import require_actorops_v2_schema
from .actorops.repository import ActorOpsRepository
from .actorops.runtime_candidate_health import operational_route_summary
from .apify_pool_runtime import apify_coordinator_for_workspace
from .job_queue import JobQueue
from .worker_actorops_v2_discovery import _catalog
from .system_settings import resolve_system_setting


@dataclass(frozen=True, slots=True)
class WorkerActorOpsV2MaintenancePorts:
    run_probe: Callable[[dict[str, Any], str, ServiceStore], Awaitable[ProbeResult]]


def run_actorops_v2_maintenance(
    job: dict[str, Any], *, data_dir: str, store: ServiceStore,
    ports: WorkerActorOpsV2MaintenancePorts | None = None,
) -> dict[str, Any]:
    require_actorops_v2_schema(store)
    payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}
    required = {"route_id", "candidate_id", "source_id", "binding_version", "slot"}
    standing = set(payload) == required and all(
        str(payload.get(key) or "").strip() for key in required
    )
    if not standing and not valid_recovery_job_payload(payload):
        raise ValueError("ActorOps v2 maintenance job metadata is invalid")
    result = asyncio.run((ports or WorkerActorOpsV2MaintenancePorts(_run_probe)).run_probe(job, data_dir, store))
    recovery = payload.get("intent") == RECOVERY_INTENT
    succeeded = result.status == "recovered" if recovery else result.status not in {
        "failed", "recovery_required",
    }
    return {
        "ok": succeeded,
        "_job_status": "succeeded" if succeeded else "failed",
        "job_type": "actorops_v2_maintenance", "route_id": str(payload["route_id"]),
        "candidate_id": result.candidate_id, "attempt_id": result.attempt_id,
        "status": result.status, "error_code": result.error_code,
    }


async def _run_probe(job: dict[str, Any], data_dir: str, store: ServiceStore) -> ProbeResult:
    payload = job["payload_json"]
    workspace_id = str(job["workspace_id"])
    source = store.get_source(str(payload["source_id"]))
    if source is None or str(source.get("workspace_id")) != workspace_id:
        return ProbeResult(None, str(payload["candidate_id"]), "skipped", "actorops_maintenance_source_missing")
    config = source.get("config")
    if not isinstance(config, dict):
        return ProbeResult(None, str(payload["candidate_id"]), "skipped", "actorops_maintenance_source_invalid")
    coordinator = apify_coordinator_for_workspace(
        store,
        workspace_id=workspace_id,
        data_dir=data_dir,
        purpose="validation",
        require_validation_key=False,
    )
    if coordinator is None:
        return ProbeResult(None, str(payload["candidate_id"]), "skipped", "actorops_maintenance_credential_unavailable")
    catalog = _catalog(store, workspace_id, data_dir, purpose="validation")
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        remote = ApifyV2RemoteClient(ApifyClient(coordinator=coordinator, http_client=client))
        result = await ActorOpsProber(
            ActorOpsRepository(store.connect(), workspace_id), build_default_registry(), remote,
            _CatalogPreflight(catalog),
        ).probe(
            route_id=str(payload["route_id"]), candidate_id=str(payload["candidate_id"]),
            source_id=str(payload["source_id"]), source_config=config,
            maintenance_slot=str(payload["slot"]),
            expected_binding_version=int(payload["binding_version"]),
            intent=str(payload.get("intent") or "standing"),
            expected_route_generation=(
                int(payload["expected_route_generation"])
                if payload.get("intent") == RECOVERY_INTENT else None
            ),
            expected_candidate_generation=(
                int(payload["expected_candidate_generation"])
                if payload.get("intent") == RECOVERY_INTENT else None
            ),
            expected_last_failure_at=(
                str(payload["expected_last_failure_at"])
                if payload.get("intent") == RECOVERY_INTENT else None
            ),
        )
    return result


class _CatalogPreflight:
    def __init__(self, catalog: object) -> None:
        self.catalog = catalog

    async def verify(self, candidate: object, *, max_charge_usd: float) -> ProbePreflightResult:
        method = getattr(self.catalog, "verify_candidate", None)
        if method is None:
            return ProbePreflightResult(False, "actorops_maintenance_preflight_unavailable")
        return await method(candidate, max_charge_usd=max_charge_usd)


def enqueue_due_actorops_v2_maintenance(
    store: ServiceStore, queue: JobQueue, *, limit: int = 5,
) -> dict[str, int]:
    """Queue at most one safe, low-priority Probe per route/UTC slot."""

    require_actorops_v2_schema(store)
    connection = store.connect()
    enqueued = deferred = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        now = datetime.now(timezone.utc)
        slot = _slot(now)
        workspaces = connection.execute("SELECT id FROM workspaces ORDER BY id").fetchall()
        for workspace in workspaces:
            workspace_id = str(workspace["id"])
            repository = ActorOpsRepository(connection, workspace_id)
            routes = repository.maintenance.due_routes(limit=20)
            user_id = _operator(connection, workspace_id)
            if user_id is None:
                deferred += len(routes)
                continue
            for route_id in routes:
                repository.maintenance.reconcile_settled_candidates(route_id)
                _ensure_degraded_source_repairs(repository, route_id, slot)
                target = repository.maintenance.probe_target(route_id)
                if target is None:
                    deferred += 1
                    continue
                candidate_id, binding = target
                if _active_or_finished_slot(connection, workspace_id, route_id, candidate_id, slot):
                    continue
                queue.create_job(
                    workspace_id=workspace_id, user_id=user_id,
                    job_type="actorops_v2_maintenance",
                    payload={
                        "route_id": route_id, "candidate_id": candidate_id,
                        "source_id": str(binding["source_id"]),
                        "binding_version": int(binding["binding_version"]), "slot": slot,
                    },
                    priority=-10, max_attempts=1,
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


def _slot(now: datetime) -> str:
    index = (now.hour * 60 + now.minute) // 288
    return f"{now.date().isoformat()}:{index}"


def _active_or_finished_slot(connection: Any, workspace_id: str, route_id: str, candidate_id: str, slot: str) -> bool:
    return connection.execute(
        """SELECT 1 FROM fetch_jobs WHERE workspace_id=? AND job_type='actorops_v2_maintenance'
           AND json_extract(payload_json, '$.route_id')=?
           AND json_extract(payload_json, '$.candidate_id')=?
           AND json_extract(payload_json, '$.slot')=? LIMIT 1""",
        (workspace_id, route_id, candidate_id, slot),
    ).fetchone() is not None


def _ensure_degraded_source_repairs(
    repository: ActorOpsRepository, route_id: str, slot: str
) -> None:
    candidates = tuple(repository.list_route_candidates(route_id))
    bindings = repository.connection.execute(
        """SELECT source_id FROM actor_source_bindings_v2
             WHERE workspace_id=? AND route_id=? AND status='ready'
             ORDER BY source_id""",
        (repository.workspace_id, route_id),
    ).fetchall()
    for binding in bindings:
        source_id = str(binding["source_id"])
        summary = operational_route_summary(
            repository,
            candidates,
            route_id=route_id,
            source_id=source_id,
        )
        if summary.health.value == "healthy":
            continue
        repository.resilience.ensure_repair(
            route_id=route_id,
            source_id=source_id,
            origin_job_id=f"maintenance:{slot}",
            trigger_code=(
                "actorops_source_unavailable"
                if summary.health.value == "unavailable"
                else "actorops_insufficient_stable_paths"
            ),
        )


def _operator(connection: Any, workspace_id: str) -> str | None:
    row = connection.execute(
        """SELECT id FROM users WHERE workspace_id=? AND enabled=1
           AND role IN ('owner','admin') ORDER BY created_at, id LIMIT 1""",
        (workspace_id,),
    ).fetchone()
    return str(row["id"]) if row else None


__all__ = [
    "WorkerActorOpsV2MaintenancePorts", "enqueue_due_actorops_v2_maintenance",
    "run_actorops_v2_maintenance",
]
