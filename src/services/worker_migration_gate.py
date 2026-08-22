"""Fail-closed startup migration checks for the queued-job Worker."""

from __future__ import annotations

from ..storage.service_store import ServiceStore


MigrationCheck = tuple[str, str]

WORKER_STARTUP_MIGRATIONS: tuple[MigrationCheck, ...] = (
    ("webhook_providers_v14", "webhook_providers_v14_migration_required"),
    (
        "multichannel_notifications_v15",
        "multichannel_notifications_v15_migration_required",
    ),
    ("notification_targets_v16", "notification_targets_v16_migration_required"),
)


def first_required_worker_startup_migration(store: ServiceStore) -> str | None:
    """Return the first missing startup migration in compatibility order."""

    for migration, check_name in WORKER_STARTUP_MIGRATIONS:
        if getattr(store, check_name)():
            return migration
    return None
