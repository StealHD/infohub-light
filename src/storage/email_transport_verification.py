"""Persist verified email readiness and its recovery watermark atomically."""

from datetime import datetime, timezone
from typing import Any


def record_email_transport_test(
    store: Any,
    *,
    workspace_id: str,
    generation: int,
    status: str,
    error_code: str | None = None,
    tested_at: str | None = None,
) -> dict[str, Any] | None:
    if status not in {"sent", "failed"}:
        raise ValueError("email transport test status is invalid")
    conn = store.connect()
    owns_transaction = not conn.in_transaction
    try:
        if owns_transaction:
            conn.execute("BEGIN IMMEDIATE")
        current = store.get_workspace_email_transport(workspace_id=workspace_id)
        if current is None or int(current.get("generation") or 0) != generation:
            if owns_transaction:
                conn.rollback()
            return None
        was_verified = bool(
            current.get("last_test_status") == "sent"
            and current.get("last_test_generation") == generation
        )
        now = tested_at or datetime.now(timezone.utc).isoformat()
        # Keep the old column as a compatibility mirror, never a readiness input.
        conn.execute(
            """
            UPDATE workspace_email_transports
            SET enabled = ?, last_test_status = ?, last_test_generation = ?,
                last_tested_at = ?, last_test_error_code = ?, updated_at = ?
            WHERE workspace_id = ? AND generation = ?
            """,
            (int(status == "sent"), status, generation, now,
             error_code if status == "failed" else None, now, workspace_id, generation),
        )
        if status == "sent" and not was_verified:
            store.advance_notification_channel_watermarks(
                workspace_id=workspace_id, channel="email", enabled_at=now, commit=False,
            )
        elif status == "failed":
            store.invalidate_pending_email_deliveries(workspace_id=workspace_id, commit=False)
        updated = store.get_workspace_email_transport(workspace_id=workspace_id)
        if owns_transaction:
            conn.commit()
        return updated
    except Exception:
        if owns_transaction and conn.in_transaction:
            conn.rollback()
        raise
