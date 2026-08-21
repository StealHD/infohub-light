"""Offline bridge for catalog social sources absent from legacy ActorOps bindings."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from ...apify_actor_identity import source_target_fingerprint
from .adapters import build_default_registry
from .domain import RouteKey
from .registry import AdapterNotRegistered, AdapterRegistry


@dataclass(frozen=True, slots=True)
class CatalogBindingBridgeReport:
    catalog_candidates: int = 0
    existing_v1_bindings: int = 0
    existing_v2_bindings: int = 0
    invalid_targets: int = 0
    unregistered_routes: int = 0
    inserted: int = 0

    def planned_counts(self) -> dict[str, int]:
        return {
            "catalog_candidates": self.catalog_candidates,
            "existing_v1_bindings": self.existing_v1_bindings,
            "existing_v2_bindings": self.existing_v2_bindings,
            "invalid_targets": self.invalid_targets,
            "unregistered_routes": self.unregistered_routes,
        }


@dataclass(frozen=True, slots=True)
class _CatalogBindingPlan:
    binding_id: str
    workspace_id: str
    source_id: str
    route_id: str
    target_fingerprint: str


def _binding_id(
    *, workspace_id: str, source_id: str, route_id: str, target_fingerprint: str
) -> str:
    digest = hashlib.sha256(
        "\x1f".join((workspace_id, source_id, route_id, target_fingerprint)).encode(
            "utf-8"
        )
    ).hexdigest()[:32]
    return f"actorops-v2-catalog-binding-{digest}"


def _source_config(row: sqlite3.Row) -> dict[str, object] | None:
    try:
        value = json.loads(str(row["config_json"] or "{}"))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _plans(
    connection: sqlite3.Connection,
    *,
    registry: AdapterRegistry,
) -> tuple[tuple[_CatalogBindingPlan, ...], CatalogBindingBridgeReport]:
    routes = {
        RouteKey(row["platform"], row["target_type"], row["capability"]): str(
            row["route_id"]
        )
        for row in connection.execute(
            """SELECT route_id, platform, target_type, capability
               FROM actor_routes_v2 ORDER BY route_id"""
        )
    }
    legacy_sources = {
        str(row["source_id"])
        for row in connection.execute(
            "SELECT source_id FROM apify_source_route_bindings"
        )
    }
    v2_sources = {
        str(row["source_id"])
        for row in connection.execute(
            "SELECT source_id FROM actor_source_bindings_v2"
        )
    }
    plans: list[_CatalogBindingPlan] = []
    counts = CatalogBindingBridgeReport()
    for row in connection.execute(
        """SELECT id, workspace_id, config_json FROM source_catalog
           WHERE type='apify_social' ORDER BY workspace_id, id"""
    ):
        source_id = str(row["id"])
        if source_id in legacy_sources:
            counts = replace(
                counts, existing_v1_bindings=counts.existing_v1_bindings + 1
            )
            continue
        if source_id in v2_sources:
            counts = replace(
                counts, existing_v2_bindings=counts.existing_v2_bindings + 1
            )
            continue
        config = _source_config(row)
        if config is None:
            counts = replace(counts, invalid_targets=counts.invalid_targets + 1)
            continue
        try:
            route_key = RouteKey(
                str(config.get("platform") or ""),
                str(config.get("kind") or ""),
                "items",
            )
            route_id = routes[route_key]
            registry.require(route_key).normalize_target(config)
            raw_target = str(config.get("target") or "")
            if not raw_target:
                raise ValueError("catalog target is required")
        except (AdapterNotRegistered, KeyError):
            counts = replace(
                counts, unregistered_routes=counts.unregistered_routes + 1
            )
            continue
        except (TypeError, ValueError):
            counts = replace(counts, invalid_targets=counts.invalid_targets + 1)
            continue
        workspace_id = str(row["workspace_id"])
        fingerprint = source_target_fingerprint(
            workspace_id, route_id, raw_target, platform=route_key.platform
        )
        plans.append(
            _CatalogBindingPlan(
                binding_id=_binding_id(
                    workspace_id=workspace_id,
                    source_id=source_id,
                    route_id=route_id,
                    target_fingerprint=fingerprint,
                ),
                workspace_id=workspace_id,
                source_id=source_id,
                route_id=route_id,
                target_fingerprint=fingerprint,
            )
        )
        counts = replace(
            counts, catalog_candidates=counts.catalog_candidates + 1
        )
    return tuple(plans), counts


def catalog_binding_is_current(
    connection: sqlite3.Connection,
    binding: sqlite3.Row,
    *,
    registry: AdapterRegistry | None = None,
) -> bool:
    """Verify one synthetic catalog binding without exposing its target value."""

    source = connection.execute(
        """SELECT workspace_id, config_json FROM source_catalog
           WHERE id=? AND workspace_id=? AND type='apify_social'""",
        (binding["source_id"], binding["workspace_id"]),
    ).fetchone()
    if source is None or connection.execute(
        """SELECT 1 FROM apify_source_route_bindings
           WHERE workspace_id=? AND source_id=?""",
        (binding["workspace_id"], binding["source_id"]),
    ).fetchone():
        return False
    config = _source_config(source)
    if config is None:
        return False
    try:
        route_key = RouteKey(
            str(config.get("platform") or ""),
            str(config.get("kind") or ""),
            "items",
        )
        route = connection.execute(
            """SELECT route_id FROM actor_routes_v2
               WHERE workspace_id=? AND platform=? AND target_type=? AND capability=?""",
            (
                binding["workspace_id"],
                route_key.platform,
                route_key.target_type,
                route_key.capability,
            ),
        ).fetchone()
        if route is None:
            return False
        (registry or build_default_registry()).require(route_key).normalize_target(config)
        raw_target = str(config.get("target") or "")
        route_id = str(route["route_id"])
        fingerprint = source_target_fingerprint(
            str(binding["workspace_id"]),
            route_id,
            raw_target,
            platform=route_key.platform,
        )
    except (AdapterNotRegistered, TypeError, ValueError):
        return False
    return bool(
        raw_target
        and str(binding["route_id"]) == route_id
        and str(binding["target_fingerprint"]) == fingerprint
        and int(binding["source_v1_generation"]) == 1
        and str(binding["binding_id"])
        == _binding_id(
            workspace_id=str(binding["workspace_id"]),
            source_id=str(binding["source_id"]),
            route_id=route_id,
            target_fingerprint=fingerprint,
        )
    )


def bridge_catalog_source_bindings(
    connection: sqlite3.Connection,
    *,
    apply: bool,
    registry: AdapterRegistry | None = None,
    now: datetime | None = None,
) -> CatalogBindingBridgeReport:
    """Plan or insert pending v2 bindings without changing catalog or v1 facts."""

    plans, report = _plans(
        connection, registry=registry or build_default_registry()
    )
    if not apply:
        return report
    if not connection.in_transaction:
        raise RuntimeError("catalog binding bridge requires an active transaction")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    for plan in plans:
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version,
                   source_v1_generation, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, 'pending', 1, 1, ?, ?)""",
            (
                plan.binding_id,
                plan.workspace_id,
                plan.source_id,
                plan.route_id,
                plan.target_fingerprint,
                stamp,
                stamp,
            ),
        )
    return replace(report, inserted=len(plans))


__all__ = [
    "CatalogBindingBridgeReport",
    "bridge_catalog_source_bindings",
    "catalog_binding_is_current",
]
