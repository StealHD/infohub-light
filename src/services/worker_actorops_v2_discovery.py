"""Worker boundary for explicit, recoverable ActorOps v2 Discovery Jobs."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..storage.service_store import ServiceStore
from .actorops.adapters import build_default_registry
from .actorops.apify_catalog import ApifyDiscoveryCatalog
from .actorops.discovery import ActorOpsDiscovery, DiscoveryCatalogError
from .actorops.discovery_ai import open_actorops_discovery_ai_mapper
from .actorops.readiness import actorops_v2_enabled, require_actorops_v2_if_enabled
from .actorops.repository import ActorOpsRepository
from .apify_actor_discovery import ApifyStoreRestClient
from .job_queue import JobQueue
from .secret_store import SecretStore


@dataclass(frozen=True, slots=True)
class WorkerActorOpsV2DiscoveryPorts:
    build_catalog: Callable[[ServiceStore, str, str], object]


def run_actorops_v2_discovery(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerActorOpsV2DiscoveryPorts | None = None,
) -> dict[str, Any]:
    if not actorops_v2_enabled():
        raise RuntimeError("actorops_v2_disabled")
    require_actorops_v2_if_enabled(store)
    payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}
    discovery_id = str(payload.get("discovery_id") or "").strip()
    if set(payload) != {"discovery_id"} or not discovery_id:
        raise ValueError("ActorOps v2 Discovery job metadata is invalid")
    catalog = (ports or WorkerActorOpsV2DiscoveryPorts(_catalog)).build_catalog(
        store, str(job["workspace_id"]), data_dir
    )
    repository = ActorOpsRepository(store.connect(), str(job["workspace_id"]))
    ai_mapper = open_actorops_discovery_ai_mapper(
        store=store, data_dir=data_dir, workspace_id=str(job["workspace_id"]),
        user_id=str(job["user_id"]),
    )
    result = asyncio.run(_run_discovery(repository, catalog, discovery_id, ai_mapper))
    if result.status == "completed" and not result.idempotent_replay:
        asyncio.run(_refresh_discovered_store_metadata(repository, catalog, discovery_id))
    return {
        "ok": result.status != "failed",
        "job_type": "actorops_v2_discovery",
        "discovery_id": result.discovery_id,
        "stage": result.stage,
        "status": result.status,
        "idempotent_replay": result.idempotent_replay,
    }


def enqueue_due_actorops_v2_discoveries(
    store: ServiceStore,
    queue: JobQueue,
    *,
    limit: int = 5,
) -> dict[str, int]:
    """Queue only already-created v2 facts; flag-off must not read global 26."""

    if not actorops_v2_enabled():
        return {"enqueued": 0, "deferred": 0}
    require_actorops_v2_if_enabled(store)
    connection = store.connect()
    enqueued = deferred = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        now = datetime.now(timezone.utc).isoformat()
        workspaces = connection.execute("SELECT id FROM workspaces ORDER BY id").fetchall()
        for workspace in workspaces:
            workspace_id = str(workspace["id"])
            repository = ActorOpsRepository(connection, workspace_id)
            for row in repository.discovery.list_due(now=now, limit=limit):
                if _active_job(connection, workspace_id, str(row["discovery_id"])):
                    continue
                actor = _operator(connection, workspace_id)
                if actor is None:
                    deferred += 1
                    continue
                queue.create_job(
                    workspace_id=workspace_id, user_id=actor,
                    job_type="actorops_v2_discovery",
                    payload={"discovery_id": str(row["discovery_id"])},
                    priority=50, max_attempts=1,
                    retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
                    commit=False,
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


def _catalog(store: ServiceStore, workspace_id: str, data_dir: str) -> object:
    row = store.connect().execute(
        """SELECT secret.env_name FROM apify_key_pool_state AS state
           JOIN secret_refs AS secret ON secret.id=state.active_secret_id
           WHERE state.workspace_id=?""",
        (workspace_id,),
    ).fetchone()
    env_name = str(row["env_name"]) if row else ""
    environment = os.getenv(env_name) if env_name else ""
    token = str(SecretStore(data_dir).read().get(env_name) or environment or "").strip()
    if not token:
        return _UnavailableCatalog()
    return ApifyDiscoveryCatalog(ApifyStoreRestClient(token))


async def _refresh_discovered_store_metadata(
    repository: ActorOpsRepository, catalog: object, discovery_id: str
) -> None:
    """Persist public card facts for newly accepted Candidates, one at a time.

    Discovery stays free and its success does not depend on this optional Store
    refresh.  A failed public GET therefore cannot poison the discovery record
    or cause a paid Actor call.
    """

    refresh = getattr(catalog, "store_metadata", None)
    if not callable(refresh):
        return
    for candidate_id in repository.discovery.list_accepted_candidate_ids(discovery_id):
        try:
            metadata = await refresh(repository.get_candidate(candidate_id))
            with repository.transaction():
                repository.operator.upsert_metadata(candidate_id, metadata)
        except Exception:
            continue


async def _run_discovery(
    repository: ActorOpsRepository, catalog: object, discovery_id: str, ai_mapper: object | None,
) -> Any:
    try:
        return await ActorOpsDiscovery(
            repository, build_default_registry(), catalog, ai_mapper=ai_mapper,
        ).run(discovery_id)
    finally:
        close = getattr(ai_mapper, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception:
                pass


class _UnavailableCatalog:
    async def search(self, _query: str):
        raise DiscoveryCatalogError("actorops_discovery_catalog_unconfigured", retryable=False)

    async def get_revision(self, _actor_id: str):
        raise DiscoveryCatalogError("actorops_discovery_catalog_unconfigured", retryable=False)


def _active_job(connection: Any, workspace_id: str, discovery_id: str) -> bool:
    return connection.execute(
        """SELECT 1 FROM fetch_jobs WHERE workspace_id=?
           AND job_type='actorops_v2_discovery' AND status IN ('queued','running')
           AND json_extract(payload_json, '$.discovery_id')=? LIMIT 1""",
        (workspace_id, discovery_id),
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
    "WorkerActorOpsV2DiscoveryPorts",
    "enqueue_due_actorops_v2_discoveries",
    "run_actorops_v2_discovery",
]
