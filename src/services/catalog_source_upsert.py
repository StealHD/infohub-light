"""REST catalog upsert orchestration with explicit source identity."""

from typing import Any

from .source_identity import require_source_identity


def rest_upsert_source(service: Any, actor: Any, values: dict, *, create_only: bool = False) -> dict:
    user = service._live_actor(actor)
    if values.get("workspace_id") != actor.workspace_id:
        raise service._error("not_found", "workspace not found", status_code=404)
    scope = values.get("scope")
    if scope != "private" and user.get("role") not in {"owner", "admin"}:
        raise service._error(
            "forbidden",
            "only admins can create public or workspace sources",
            status_code=403,
        )
    if scope == "private" and values.get("owner_user_id") != actor.user_id:
        raise service._error(
            "forbidden", "cannot create another user's private source", status_code=403
        )
    if values.get("secret_env") is not None and user.get("role") not in {
        "owner",
        "admin",
    }:
        raise service._error(
            "forbidden", "only admins can assign a source secret", status_code=403
        )
    require_source_identity(service.store)
    conn = service.store.connect()
    owns_transaction = not conn.in_transaction
    try:
        if owns_transaction:
            conn.execute("BEGIN IMMEDIATE")
        existing = service.store.get_source_by_key(
            workspace_id=actor.workspace_id,
            source_key=str(values["source_key"]),
            scope=scope, owner_user_id=values.get("owner_user_id"),
        )
        if create_only and existing:
            if (
                scope != existing.get("scope")
                or values["source_type"] != existing.get("type")
                or values["config"] != existing.get("config")
                or values.get("secret_env") != existing.get("secret_env")
                or (values.get("enforce_public_network") and not existing.get("enforce_public_network"))
            ):
                raise service._error(
                    "source_key_conflict", "A source with this identity already exists.",
                    status_code=409, action="Use the existing visible source or edit its configuration.",
                )
            # Private orchestration marker, removed by the catalog endpoint before serialization.
            result = {**existing, "_catalog_reused": True}
        else:
            result = service.store.upsert_source(**values)
        if existing and (
            values["config"] != existing.get("config")
            or values.get("secret_env") != existing.get("secret_env")
        ):
            service.source_health.reset_source(
                workspace_id=actor.workspace_id,
                source_id=str(existing["id"]),
                commit=False,
            )
        if owns_transaction:
            conn.commit()
        return result
    except Exception:
        if owns_transaction and conn.in_transaction:
            conn.rollback()
        raise
