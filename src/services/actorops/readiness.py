"""ActorOps v2 single-track schema gate."""

from __future__ import annotations

from ...storage.actorops_v2_stability_schema import (
    migration_marker_exists as stability_migration_marker_exists,
    schema_shapes_valid as stability_schema_shapes_valid,
)
from ...storage.actorops_v2_revalidation_schema import (
    migration_marker_exists as revalidation_migration_marker_exists,
    schema_shapes_valid as revalidation_schema_shapes_valid,
)
from ...storage.actorops_v2_sampling_schema import (
    migration_marker_exists as sampling_migration_marker_exists,
    schema_shapes_valid as sampling_schema_shapes_valid,
)
from ...storage.service_store import ServiceStore


def require_actorops_v2_schema(store: ServiceStore) -> None:
    """Require the current v2 source runtime schema without a feature flag."""

    connection = store.connect()
    if (
        not stability_migration_marker_exists(connection)
        or not stability_schema_shapes_valid(connection)
        or not revalidation_migration_marker_exists(connection)
        or not revalidation_schema_shapes_valid(connection)
        or not sampling_migration_marker_exists(connection)
        or not sampling_schema_shapes_valid(connection)
    ):
        raise RuntimeError("actorops_v2 migration_required")


def actorops_v2_startup_migration_required(store: ServiceStore) -> bool:
    connection = store.connect()
    return not (
        stability_migration_marker_exists(connection)
        and stability_schema_shapes_valid(connection)
        and revalidation_migration_marker_exists(connection)
        and revalidation_schema_shapes_valid(connection)
        and sampling_migration_marker_exists(connection)
        and sampling_schema_shapes_valid(connection)
    )
