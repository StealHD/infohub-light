"""Conditional ActorOps v2 runtime gate."""

from __future__ import annotations

import os

from ...storage.actorops_v2_single_track_schema import (
    migration_marker_exists as single_track_migration_marker_exists,
)
from ...storage.actorops_v2_single_track_schema import (
    schema_shapes_valid as single_track_schema_shapes_valid,
)
from ...storage.service_store import ServiceStore


def actorops_v2_enabled() -> bool:
    return os.getenv("ACTOROPS_V2_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_actorops_v2_if_enabled(store: ServiceStore) -> None:
    if not actorops_v2_enabled():
        return
    require_actorops_v2_schema(store)


def require_actorops_v2_schema(store: ServiceStore) -> None:
    """Require the current v2 source runtime schema without a feature flag."""

    connection = store.connect()
    if (
        not single_track_migration_marker_exists(connection)
        or not single_track_schema_shapes_valid(connection)
    ):
        raise RuntimeError("actorops_v2 migration_required")


def actorops_v2_startup_migration_required(store: ServiceStore) -> bool:
    if not actorops_v2_enabled():
        return False
    connection = store.connect()
    return not (
        single_track_migration_marker_exists(connection)
        and single_track_schema_shapes_valid(connection)
    )
