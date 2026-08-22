"""Explicit test-only adapter for historical v1 Discovery handler coverage."""

from __future__ import annotations

from typing import Any

from src.services.worker_actor_discovery_handler import (
    WorkerActorDiscoveryPorts,
    actor_discovery_queries,
    run_actor_discovery,
)
from src.storage.service_store import ServiceStore

_PORTS = WorkerActorDiscoveryPorts(
    safe_machine_code=lambda value, fallback: str(value or fallback),
    log_close_failure=lambda: None,
)


def legacy_actor_discovery_queries(route: dict[str, Any]) -> tuple[str, str, str]:
    return actor_discovery_queries(route)


def run_legacy_actor_discovery(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    return run_actor_discovery(job, data_dir=data_dir, store=store, ports=_PORTS)


__all__ = ["legacy_actor_discovery_queries", "run_legacy_actor_discovery"]
