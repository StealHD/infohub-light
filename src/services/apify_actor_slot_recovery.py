"""Recover stale circuit state only when current source proof supersedes it."""

from __future__ import annotations

from datetime import datetime, timezone

from ..storage.service_store import ServiceStore
from .apify_actor_source_proof import current_source_validation_ids


def recover_source_proven_slots(
    store: ServiceStore,
    *,
    workspace_id: str,
) -> int:
    """Reopen active slots whose current source Canary is newer than failure.

    A historical ``revision_not_executable`` failure may belong to a replaced
    Revision while the atomically selected fixed Revision has current, settled
    source evidence.  No other circuit state is eligible for this recovery.
    """

    connection = store.connect()
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        slots = connection.execute(
            """
            SELECT slot.route_id, slot.candidate_id, slot.revision_id,
                   revision.lifecycle
            FROM apify_route_active_slots AS slot
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = slot.workspace_id
             AND candidate.id = slot.candidate_id
            WHERE slot.workspace_id = ?
              AND candidate.state = 'open'
              AND candidate.last_error_code = 'apify_actor_revision_not_executable'
              AND candidate.last_failure_at IS NOT NULL
              AND revision.lifecycle IN ('probationary', 'certified')
            """,
            (workspace_id,),
        ).fetchall()
        recovered = 0
        for row in slots:
            bindings = connection.execute(
                """
                SELECT binding.source_id, binding.target_fingerprint
                FROM apify_source_route_bindings AS binding
                JOIN source_catalog AS source
                  ON source.workspace_id = binding.workspace_id
                 AND source.id = binding.source_id
                WHERE binding.workspace_id = ? AND binding.route_id = ?
                  AND source.enabled = 1
                """,
                (workspace_id, str(row["route_id"])),
            ).fetchall()
            if not bindings or not all(
                str(row["revision_id"])
                in current_source_validation_ids(
                    connection,
                    workspace_id=workspace_id,
                    route_id=str(row["route_id"]),
                    source_id=str(binding["source_id"]),
                    target_fingerprint=str(binding["target_fingerprint"]),
                )
                for binding in bindings
            ):
                continue
            state = "probationary" if str(row["lifecycle"]) == "probationary" else "closed"
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = ?, opened_at = NULL, retry_at = NULL,
                    recovery_successes = 0, last_error_code = NULL, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                  AND state = 'open'
                  AND last_error_code = 'apify_actor_revision_not_executable'
                """,
                (state, now, workspace_id, str(row["candidate_id"])),
            )
            recovered += 1
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return recovered
