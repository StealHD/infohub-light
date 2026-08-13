"""Runtime migration gate for ActorOps pool management."""

from __future__ import annotations

from ..storage.apify_actor_pool_management_schema import migration_required
from ..storage.service_store import ServiceStore


def actor_pool_management_migration_required(store: ServiceStore) -> bool:
    """Check global schema 24 without extending ``ServiceStore``."""

    return migration_required(store.connect())
