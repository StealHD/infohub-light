"""Fresh-database bootstrap for explicit ActorOps schema extensions."""

from __future__ import annotations

import sqlite3

from .actorops_v2_schema import (
    install_schema as install_actorops_v2_schema,
    mark_migrated as mark_actorops_v2_migrated,
)
from .actorops_v2_operator_schema import (
    bootstrap_service_store_schema as bootstrap_actorops_v2_operator_schema,
)
from .actorops_v2_attempt_recovery_schema import (
    bootstrap_service_store_schema as bootstrap_actorops_v2_attempt_recovery_schema,
)
from .actorops_v2_single_track_schema import (
    bootstrap_service_store_schema as bootstrap_actorops_v2_single_track_schema,
)
from .system_settings_v31_schema import (
    bootstrap_service_store_schema as bootstrap_system_settings_schema,
)


def bootstrap_actor_schemas(
    connection: sqlite3.Connection,
    *,
    existing_schema: bool,
) -> None:
    """Install current ActorOps extensions only for a genuinely fresh store."""

    if existing_schema:
        return
    # Fresh stores begin at the native v2 schema.  Globals 24/27 and the
    # associated v1 Pool/Canary tables remain historical migration shapes,
    # never bootstrap prerequisites for a new database.
    install_actorops_v2_schema(connection)
    mark_actorops_v2_migrated(connection)
    bootstrap_actorops_v2_operator_schema(connection, existing_schema=existing_schema)
    bootstrap_actorops_v2_attempt_recovery_schema(
        connection, existing_schema=existing_schema
    )
    if not existing_schema and connection.in_transaction:
        connection.commit()
    bootstrap_actorops_v2_single_track_schema(
        connection, existing_schema=existing_schema
    )
    bootstrap_system_settings_schema(connection, existing_schema=existing_schema)
