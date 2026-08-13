"""API fail-closed gate for global ActorOps pool-management schema 24."""

from ..services.apify_actor_pool_management_runtime import (
    actor_pool_management_migration_required,
)
from ..storage.service_store import ServiceStore
from .responses import ApiError


def require_actor_pool_management_schema(store: ServiceStore) -> None:
    if actor_pool_management_migration_required(store):
        raise ApiError(
            "migration_required",
            "Apify Actor pool management v22 migration must be applied before Actor routes are used",
            status_code=503,
            action=(
                "Stop API and Worker, then run "
                "scripts/migrate_apify_actor_pool_management_v22.py --apply."
            ),
        )
