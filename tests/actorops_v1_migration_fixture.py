"""Explicit historical-schema fixture for offline ActorOps migration tests."""

from __future__ import annotations

from src.storage.apify_actor_pool_management_schema import (
    install_schema as install_pool_management_schema,
    mark_migrated as mark_pool_management_migrated,
)
from src.storage.service_store import ServiceStore


def initialize_historical_actorops(store: ServiceStore) -> None:
    """Build the retired v13–v21 shape only for an offline migration fixture."""

    store.initialize(prepare_apify_actor_resilience_v21=True)


def initialize_historical_actorops_global24(store: ServiceStore) -> None:
    """Build the final v1 historical shape for global-25 migration tests."""

    initialize_historical_actorops(store)
    install_pool_management_schema(store.connect())
    mark_pool_management_migrated(store.connect())
    store.connect().commit()
