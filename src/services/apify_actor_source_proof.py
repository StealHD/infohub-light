"""Determine whether a source Canary still proves its active Actor revision."""

from __future__ import annotations

from typing import Any


_VALID_OUTCOMES = frozenset({"valid_nonempty", "valid_empty"})
_RECOVERABLE_FAILURE = "apify_actor_revision_not_executable"


def source_validation_failure_cutoffs(
    connection: Any,
    *,
    workspace_id: str,
    route_id: str,
) -> dict[str, str]:
    """Return active Revision failures that invalidate older source evidence."""

    rows = connection.execute(
        """
        SELECT slot.revision_id, candidate.last_failure_at
        FROM apify_route_active_slots AS slot
        JOIN apify_actor_candidates AS candidate
          ON candidate.workspace_id = slot.workspace_id
         AND candidate.id = slot.candidate_id
        WHERE slot.workspace_id = ? AND slot.route_id = ?
          AND slot.revision_id IS NOT NULL
          AND candidate.state = 'open'
          AND candidate.last_error_code = ?
          AND candidate.last_failure_at IS NOT NULL
        """,
        (workspace_id, route_id, _RECOVERABLE_FAILURE),
    ).fetchall()
    return {
        str(row["revision_id"]): str(row["last_failure_at"])
        for row in rows
    }


def current_source_validation_ids(
    connection: Any,
    *,
    workspace_id: str,
    route_id: str,
    source_id: str,
    target_fingerprint: str,
) -> set[str]:
    """Return successful settled source proofs not superseded by slot failure."""

    failure_cutoffs = source_validation_failure_cutoffs(
        connection, workspace_id=workspace_id, route_id=route_id
    )
    rows = connection.execute(
        """
        SELECT revision_id, completed_at
        FROM apify_actor_validations
        WHERE workspace_id = ? AND route_id = ? AND source_id = ?
          AND kind = 'source_canary' AND status = 'succeeded'
          AND cost_final = 1
          AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
          AND target_fingerprint = ? AND completed_at IS NOT NULL
        """,
        (workspace_id, route_id, source_id, target_fingerprint),
    ).fetchall()
    return {
        str(row["revision_id"])
        for row in rows
        if str(row["completed_at"])
        >= failure_cutoffs.get(str(row["revision_id"]), "")
    }
