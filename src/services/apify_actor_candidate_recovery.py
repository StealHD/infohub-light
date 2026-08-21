"""Revision-scoped candidate recovery for a newly verified static Build."""

from __future__ import annotations

from typing import Any


def exact_revision_has_settled_route_failure(
    connection: Any, *, workspace_id: str, revision_id: str
) -> bool:
    """Keep a failed immutable Revision out of later discovery runs."""

    return bool(
        connection.execute(
            """
            SELECT 1 FROM apify_actor_validations
            WHERE workspace_id = ? AND revision_id = ?
              AND kind = 'route_reference' AND status = 'failed'
              AND cost_final = 1
            LIMIT 1
            """,
            (workspace_id, revision_id),
        ).fetchone()
    )


def reopen_candidate_for_new_static_revision(
    connection: Any,
    *,
    workspace_id: str,
    candidate_id: str,
    revision_id: str,
    now: str,
) -> None:
    """Clear a candidate-wide rejection only after a new Revision was inserted.

    Callers invoke this after the immutable revision INSERT succeeds.  Reusing
    the same Build/Manifest returns before this point, so its settled Canary
    failure remains excluded and cannot silently become chargeable again.
    """

    connection.execute(
        """
        UPDATE apify_actor_candidates
        SET last_error_code = NULL, updated_at = ?
        WHERE workspace_id = ? AND id = ?
          AND last_error_code = 'canary_required'
        """,
        (now, workspace_id, candidate_id),
    )
    connection.execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'open', opened_at = COALESCE(opened_at, ?),
            last_error_code = NULL, updated_at = ?
        WHERE workspace_id = ? AND id = ? AND state = 'disabled'
          AND EXISTS (
              SELECT 1 FROM apify_actor_validations AS prior
              JOIN apify_actor_adapter_revisions AS prior_revision
                ON prior_revision.workspace_id = prior.workspace_id
               AND prior_revision.revision_id = prior.revision_id
              WHERE prior.workspace_id = ? AND prior_revision.candidate_id = ?
                AND prior.kind = 'route_reference' AND prior.status = 'failed'
                AND prior.cost_final = 1
          )
          AND NOT EXISTS (
              SELECT 1 FROM apify_actor_validations
              WHERE workspace_id = ? AND revision_id = ?
                AND kind = 'route_reference' AND status = 'failed'
                AND cost_final = 1
          )
        """,
        (
            now, now, workspace_id, candidate_id, workspace_id, candidate_id,
            workspace_id, revision_id,
        ),
    )
