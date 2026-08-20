"""Fail-closed startup migration checks for the queued-job Worker."""

from __future__ import annotations

from ..storage.service_store import ServiceStore
from .apify_actor_pool_management_runtime import (
    actor_pool_management_migration_required,
)
from .actorops.readiness import actorops_v2_startup_migration_required


MigrationCheck = tuple[str, str]

WORKER_STARTUP_MIGRATIONS: tuple[MigrationCheck, ...] = (
    ("apify_actor_routing_v13", "apify_actor_routing_v13_migration_required"),
    ("webhook_providers_v14", "webhook_providers_v14_migration_required"),
    (
        "multichannel_notifications_v15",
        "multichannel_notifications_v15_migration_required",
    ),
    ("notification_targets_v16", "notification_targets_v16_migration_required"),
    ("apify_actor_ops_v15", "apify_actor_ops_v15_migration_required"),
    (
        "apify_discovery_limits_v16",
        "apify_discovery_limits_v16_migration_required",
    ),
    (
        "apify_actor_canary_batches_v17",
        "apify_actor_canary_batches_v17_migration_required",
    ),
    (
        "apify_actor_pool_staging_v18",
        "apify_actor_pool_staging_v18_migration_required",
    ),
    (
        "apify_actor_manual_pool_selection_v19",
        "apify_actor_manual_pool_selection_v19_migration_required",
    ),
    (
        "apify_actor_validation_tuning_v20",
        "apify_actor_validation_tuning_v20_migration_required",
    ),
    (
        "apify_actor_resilience_v21",
        "apify_actor_resilience_v21_migration_required",
    ),
)


def first_required_worker_startup_migration(store: ServiceStore) -> str | None:
    """Return the first missing startup migration in compatibility order."""

    for migration, check_name in WORKER_STARTUP_MIGRATIONS:
        if getattr(store, check_name)():
            return migration
    if actor_pool_management_migration_required(store):
        return "apify_actor_pool_management_v22"
    if actorops_v2_startup_migration_required(store):
        return "actorops_v2"
    return None
