"""Low-priority, default-off Worker boundary for v2 standing maintenance."""

from __future__ import annotations

import asyncio
import os
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
from .actorops.readiness import actorops_v2_enabled, require_actorops_v2_if_enabled
from .actorops.repository import ActorOpsRepository
from .apify_pool_runtime import apify_coordinator_for_workspace
from .job_queue import JobQueue
from .worker_actorops_v2_discovery import _catalog


@dataclass(frozen=True, slots=True)
class WorkerActorOpsV2MaintenancePorts:
    run_probe: Callable[[dict[str, Any], str, ServiceStore], Awaitable[ProbeResult]]


def run_actorops_v2_maintenance(
    job: dict[str, Any], *, data_dir: str, store: ServiceStore,
    ports: WorkerActorOpsV2MaintenancePorts | None = None,
) -> dict[str, Any]:
    if not actorops_v2_enabled():
        raise RuntimeError("actorops_v2_disabled")
    require_actorops_v2_if_enabled(store)
    payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}
    required = {"route_id", "candidate_id", "source_id", "binding_version", "slot"}
    if set(payload) != required or not all(str(payload.get(key) or "").strip() for key in required):
        raise ValueError("ActorOps v2 maintenance job metadata is invalid")
    result = asyncio.run((ports or WorkerActorOpsV2MaintenancePorts(_run_probe)).run_probe(job, data_dir, store))
    return {
        "ok": result.status not in {"failed", "recovery_required"},
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
        store, workspace_id=workspace_id, data_dir=data_dir, purpose="maintenance"
    )
    if coordinator is None:
        return ProbeResult(None, str(payload["candidate_id"]), "skipped", "actorops_maintenance_credential_unavailable")
    catalog = _catalog(store, workspace_id, data_dir)
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

    if not actorops_v2_enabled():
        return {"enqueued": 0, "deferred": 0}
    require_actorops_v2_if_enabled(store)
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
            for route_id in repository.maintenance.due_routes(limit=20):
                candidate_id = repository.maintenance.eligible_candidate(route_id)
                binding = repository.maintenance.probe_binding(route_id, candidate_id) if candidate_id else None
                if candidate_id is None or binding is None:
                    deferred += 1
                    continue
                if _active_or_finished_slot(connection, workspace_id, route_id, candidate_id, slot):
                    continue
                user_id = _operator(connection, workspace_id)
                if user_id is None:
                    deferred += 1
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
                    retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")), commit=False,
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


def _operator(connection: Any, workspace_id: str) -> str | None:
    row = connection.execute(
        """SELECT id FROM users WHERE workspace_id=? AND enabled=1
           AND role IN ('owner','admin') ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END,
           created_at, id LIMIT 1""",
        (workspace_id,),
    ).fetchone()
    return str(row["id"]) if row else None


__all__ = [
    "WorkerActorOpsV2MaintenancePorts", "enqueue_due_actorops_v2_maintenance",
    "run_actorops_v2_maintenance",
]
