"""Bounded, free public Store metadata refresh for v2 Candidate chips."""

from __future__ import annotations

import asyncio
from typing import Any

from ..storage.service_store import ServiceStore
from .actorops.domain import AssignmentRole
from .actorops.readiness import require_actorops_v2_schema
from .actorops.repository import ActorOpsRepository
from .worker_actorops_v2_discovery import _catalog


def run_actorops_v2_metadata_refresh(
    job: dict[str, Any], *, data_dir: str, store: ServiceStore,
) -> dict[str, Any]:
    require_actorops_v2_schema(store)
    payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}
    route_id = str(payload.get("route_id") or "").strip()
    if set(payload) != {"route_id"} or not route_id:
        raise ValueError("ActorOps v2 metadata refresh job metadata is invalid")
    result = asyncio.run(_refresh(workspace_id=str(job["workspace_id"]), route_id=route_id, store=store, data_dir=data_dir))
    return {"ok": True, "job_type": "actorops_v2_metadata_refresh", "route_id": route_id, **result}


async def _refresh(*, workspace_id: str, route_id: str, store: ServiceStore, data_dir: str) -> dict[str, int]:
    repository = ActorOpsRepository(store.connect(), workspace_id)
    catalog = _catalog(store, workspace_id, data_dir)
    refreshed = failed = 0
    # The operator screen renders only current assignments.  Refreshing old
    # inactive audit revisions would create unnecessary public Store traffic.
    candidates = (
        candidate for candidate in repository.list_route_candidates(route_id)
        if candidate.assignment_role in {AssignmentRole.ACTIVE, AssignmentRole.STANDBY}
    )
    for candidate in candidates:
        try:
            metadata = await catalog.store_metadata(candidate)
            with repository.transaction():
                current = repository.operator.metadata(candidate.candidate_id)
                repository.operator.upsert_metadata(
                    candidate.candidate_id, metadata,
                    expected_generation=current.generation if current else None,
                )
            refreshed += 1
        except Exception:
            failed += 1
    return {"refreshed": refreshed, "failed": failed}


__all__ = ["run_actorops_v2_metadata_refresh"]
