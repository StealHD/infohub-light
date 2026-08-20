"""Fresh-database bootstrap for explicit ActorOps schema extensions."""

from __future__ import annotations

import sqlite3

from .apify_actor_auto_pool_schema import (
    bootstrap_service_store_schema as bootstrap_auto_pool_schema,
)
from .apify_actor_pool_management_schema import (
    bootstrap_service_store_schema as bootstrap_pool_management_schema,
)


def bootstrap_actor_schemas(
    connection: sqlite3.Connection,
    *,
    existing_schema: bool,
) -> None:
    """Install current ActorOps extensions only for a genuinely fresh store."""

    bootstrap_pool_management_schema(connection, existing_schema=existing_schema)
    bootstrap_auto_pool_schema(connection, existing_schema=existing_schema)
