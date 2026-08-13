"""Source capability readiness for Actor pools."""

from __future__ import annotations

from typing import Any

from .apify_actor_pool_management import _ensure_ops_symbols


def _ensure_module_symbols() -> None:
    ops = _ensure_ops_symbols()
    globals().update(vars(ops))


class ApifyActorPoolReadinessMixin:
    def _source_capability_ready_standard(
        self,
        route_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        """Return whether a Route can safely bind a new source.

        A full 2+1 pool is preferred. Expedited launch permits two
        Canary-proven exact-Build revisions from different publishers; source
        validation covers the revisions that are actually active.
        """

        _ensure_module_symbols()
        active = connection or self.store.connect()
        route = active.execute(
            """
            SELECT status, min_publishers, min_runtime_healthy, admission_mode
            FROM apify_actor_route_profiles
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, route_id),
        ).fetchone()
        if route is None or str(route["status"]) != "ready":
            return False
        rows = active.execute(
            """
            SELECT slot.slot_name, slot.revision_id, revision.actor_id,
                   revision.publisher,
                   revision.lifecycle, revision.build_id,
                   revision.build_number, revision.manifest_hash,
                   candidate.state AS candidate_state
            FROM apify_route_active_slots AS slot
            LEFT JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = slot.workspace_id
             AND candidate.id = slot.candidate_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        configured = [row for row in rows if row["revision_id"]]
        if len(configured) < int(route["min_runtime_healthy"]):
            return False
        if str(route["admission_mode"]) == "compatibility":
            for row in configured:
                if (
                    str(row["candidate_state"] or "")
                    not in _RUNNABLE_CANDIDATE_STATES
                    or not row["actor_id"]
                ):
                    return False
                proof = active.execute(
                    """
                    SELECT 1 FROM apify_actor_validations
                    WHERE workspace_id = ? AND route_id = ?
                      AND revision_id = ? AND kind = 'route_reference'
                      AND status = 'succeeded' AND cost_final = 1
                      AND semantic_outcome = 'valid_nonempty'
                    LIMIT 1
                    """,
                    (self.workspace_id, route_id, str(row["revision_id"])),
                ).fetchone()
                if proof is None:
                    return False
            return True
        actor_ids: set[str] = set()
        publishers: set[str] = set()
        for row in configured:
            if (
                str(row["lifecycle"] or "")
                not in {"probationary", "certified"}
                or str(row["candidate_state"] or "")
                not in _RUNNABLE_CANDIDATE_STATES
                or not row["actor_id"]
                or not row["publisher"]
                or not row["build_id"]
                or not row["build_number"]
                or not row["manifest_hash"]
            ):
                return False
            actor_ids.add(str(row["actor_id"]))
            publishers.add(str(row["publisher"]).casefold())
        return (
            len(actor_ids) == len(configured)
            and len(publishers) >= int(route["min_publishers"])
        )
