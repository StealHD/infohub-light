"""Revision-aware authorization checks for queued Actor Canaries."""

from __future__ import annotations

from typing import Any


def route_reference_candidate_authorized(
    connection: Any,
    workspace_id: str,
    revision_id: str,
    lifecycle: str,
    candidate_state: str,
) -> bool:
    """Permit a recovered candidate only when this Revision has not failed."""

    if lifecycle not in {"static_valid", "probationary"}:
        return False
    if candidate_state != "open":
        return True
    failure = connection.execute(
        """
        SELECT 1 FROM apify_actor_validations
        WHERE workspace_id = ? AND revision_id = ?
          AND kind = 'route_reference' AND status = 'failed'
          AND cost_final = 1
        LIMIT 1
        """,
        (workspace_id, revision_id),
    ).fetchone()
    return failure is None
