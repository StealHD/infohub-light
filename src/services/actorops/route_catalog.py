"""Deterministic v2 Route catalog facts derived from the Adapter Registry."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .domain import RouteKey
from .registry import AdapterRegistry


DEFAULT_PER_RUN_CAP_USD = 0.02


@dataclass(frozen=True, slots=True)
class RouteCatalogEntry:
    route_key: RouteKey
    per_run_cap_usd: float = DEFAULT_PER_RUN_CAP_USD


def catalog_entries(registry: AdapterRegistry) -> tuple[RouteCatalogEntry, ...]:
    """Return every registered Adapter Route in stable order without I/O."""

    return tuple(
        RouteCatalogEntry(route_key=route_key)
        for route_key in registry.registered_keys()
    )


def catalog_route_id(workspace_id: str, route_key: RouteKey) -> str:
    digest = hashlib.sha256(
        f"{workspace_id}:{route_key}".encode("utf-8")
    ).hexdigest()[:24]
    return f"actorops-v2-route-{digest}"


def maintenance_policy_id(workspace_id: str, route_id: str | None) -> str:
    digest = hashlib.sha256(
        f"{workspace_id}:{route_id or 'workspace'}".encode("utf-8")
    ).hexdigest()[:24]
    return f"actorops-v2-policy-{digest}"


__all__ = [
    "DEFAULT_PER_RUN_CAP_USD",
    "RouteCatalogEntry",
    "catalog_entries",
    "catalog_route_id",
    "maintenance_policy_id",
]
