"""Fixed-slot safety, projection, and removal operations for Actor pools."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal, Mapping

from .apify_actor_pool_management import (
    ROUTE_POOL_REMOVE_CONFIRMATION,
    _ops_module,
)


class ApifyActorPoolSlotsMixin:
    """Own slot-state rules that are shared by plans and activation."""

    def _require_pool_mutation_safe(
        self, connection: sqlite3.Connection, route: sqlite3.Row
    ) -> None:
        """Reject mutations while a stage, attempt, or unknown start is live."""

        ops = _ops_module()
        stage = connection.execute(
            """SELECT 1 FROM apify_actor_pool_stages
               WHERE workspace_id = ? AND route_id = ?
                 AND status NOT IN (
                     'applied', 'stale', 'failed', 'cancelled', 'replan_required'
                 )
               LIMIT 1""",
            (self.workspace_id, str(route["route_id"])),
        ).fetchone()
        if stage is not None:
            raise ops.ActorOpsError(
                "apify_actor_pool_stage_active",
                "Actor pool cannot change while a staged workflow is active",
                status_code=409,
            )
        attempt = connection.execute(
            """SELECT 1 FROM apify_actor_attempts
               WHERE workspace_id = ? AND route_key = ?
                 AND status IN ('reserved', 'running', 'start_outcome_unknown')
               LIMIT 1""",
            (self.workspace_id, str(route["route_key"])),
        ).fetchone()
        if attempt is not None or str(route["status"]) == "blocked_unknown_start":
            raise ops.ActorOpsError(
                "apify_actor_pool_remove_inflight",
                "Actor pool cannot change while an attempt is unresolved",
                status_code=409,
            )

    def _pool_allowed_lifecycle(
        self,
        *,
        slot_name: str,
        expedited: bool,
        allow_probationary_primary: bool,
        allow_compatibility_single: bool,
        allow_compatibility_slot: bool = False,
        allow_legacy_compaction: bool = False,
    ) -> set[str]:
        if (
            allow_compatibility_single
            or allow_compatibility_slot
            or (expedited and allow_legacy_compaction)
        ):
            return {"certified", "probationary", "legacy_builtin"}
        if expedited or allow_probationary_primary:
            return {"certified", "probationary"}
        return (
            {"certified", "legacy_builtin"}
            if slot_name in {"primary", "backup_1"}
            else {"certified", "probationary", "legacy_builtin"}
        )

    def pool_candidate_operation_blocker(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
        *,
        goal: str,
        target_slot: str | None,
    ) -> dict[str, Any] | None:
        """Return the authoritative empty candidate projection when blocked."""

        blocker = self._pool_slot_operation_blocker(
            connection, route, goal=goal, target_slot=target_slot
        )
        if blocker is None:
            return None
        return {
            "schema_version": 1,
            "route_id": str(route["route_id"]),
            "generation": int(route["generation"]),
            "goal": goal,
            "target_slot": target_slot,
            "run_id": None,
            "required_selection_count": 1,
            "candidates": [],
            "blockers": [blocker],
        }

    def pool_stage_operation_target_count(
        self,
        connection: sqlite3.Connection,
        *,
        route_id: str,
        goal: str,
        target_slot: str | None,
        populated_count: int,
        requested_count: int | None,
        minimum_healthy: int,
    ) -> int:
        """Validate a single-slot goal and resolve its frozen slot count."""

        ops = _ops_module()
        route = self._require_route(connection, route_id)
        blocker = self._pool_slot_operation_blocker(
            connection, route, goal=goal, target_slot=target_slot
        )
        if blocker is not None:
            raise ops.ActorOpsError(
                f"apify_actor_pool_{blocker}",
                "The requested Actor slot operation is not safe to stage",
                status_code=409,
            )
        compact_unverified_youtube = (
            requested_count is None
            and goal == "replace_slot"
            and str(route["platform"]) == "youtube"
            and int(route["min_runtime_healthy"]) == 1
            and connection.execute(
                """
                SELECT 1
                FROM apify_source_route_bindings AS binding
                JOIN source_catalog AS source
                  ON source.workspace_id = binding.workspace_id
                 AND source.id = binding.source_id
                WHERE binding.workspace_id = ? AND binding.route_id = ?
                  AND source.enabled = 1
                  AND binding.validation_status NOT IN (
                      'ready_1of1', 'ready_2of2', 'ready_3of3'
                  )
                LIMIT 1
                """,
                (self.workspace_id, route_id),
            ).fetchone() is not None
        )
        count = (
            int(requested_count)
            if requested_count is not None
            else 1
            if compact_unverified_youtube
            else populated_count + 1
            if goal == "add_slot"
            else populated_count
            if goal == "replace_slot"
            else 3
            if goal in {"complete_third", "upgrade_legacy"}
            else minimum_healthy
        )
        if count not in {1, 2, 3} or (
            count == 1 and goal not in {"initial_pool", "add_slot", "replace_slot"}
        ) or count < minimum_healthy:
            raise ops.ActorOpsError(
                "apify_actor_pool_target_count_invalid",
                "Actor pool target slot count is invalid for this workflow",
                status_code=422,
            )
        return count

    def pool_stage_context(
        self,
        connection: sqlite3.Connection,
        *,
        run: sqlite3.Row,
        goal: str,
        target_slot: str | None,
        requested_count: int | None,
    ) -> tuple[dict[str, sqlite3.Row], list[sqlite3.Row], int]:
        """Load and freeze the active-pool context for a staged operation."""

        ops = _ops_module()
        active_stage = connection.execute(
            """SELECT stage_id, status FROM apify_actor_pool_stages
               WHERE workspace_id = ? AND route_id = ?
                 AND status NOT IN ('applied', 'stale', 'failed', 'cancelled')
               LIMIT 1""",
            (self.workspace_id, str(run["route_id"])),
        ).fetchone()
        if active_stage is not None and str(active_stage["status"]) != "replan_required":
            raise ops.ActorOpsError(
                "apify_actor_pool_stage_active",
                "A staged Actor pool workflow is already active",
                status_code=409,
            )
        slot_rows = connection.execute(
            """SELECT slot.slot_name, slot.revision_id, revision.actor_id,
                      revision.publisher, revision.lifecycle, revision.build_id,
                      revision.build_number, revision.manifest_hash
               FROM apify_route_active_slots AS slot
               LEFT JOIN apify_actor_adapter_revisions AS revision
                 ON revision.workspace_id = slot.workspace_id
                AND revision.revision_id = slot.revision_id
               WHERE slot.workspace_id = ? AND slot.route_id = ?""",
            (self.workspace_id, str(run["route_id"])),
        ).fetchall()
        populated = [row for row in slot_rows if row["revision_id"] is not None]
        resolved = self.pool_stage_operation_target_count(
            connection,
            route_id=str(run["route_id"]),
            goal=goal,
            target_slot=target_slot,
            populated_count=len(populated),
            requested_count=requested_count,
            minimum_healthy=int(run["min_runtime_healthy"]),
        )
        return {str(row["slot_name"]): row for row in slot_rows}, populated, resolved

    @staticmethod
    def pool_final_publishers(
        *,
        goal: str,
        target_slot: str | None,
        selected: list[sqlite3.Row],
        populated: list[sqlite3.Row],
    ) -> set[str]:
        retained = {
            str(row["publisher"]).casefold()
            for row in populated
            if row["publisher"] and not (
                goal == "replace_slot" and str(row["slot_name"]) == str(target_slot)
            )
        }
        return retained | {str(row["publisher"]).casefold() for row in selected}

    @staticmethod
    def pool_selected_publishers(selected: tuple[sqlite3.Row, ...]) -> set[str]:
        return {str(row["publisher"]).casefold() for row in selected}

    def pool_stage_replay_matches(
        self,
        replay: sqlite3.Row,
        *,
        goal: str,
        target_slot: str | None,
        expected_plan_hash: str,
        max_candidates: int,
        plan: Mapping[str, Any],
        max_total_charge_usd: float,
    ) -> bool:
        return not (
            str(replay["plan_hash"]) != expected_plan_hash
            or int(replay["max_candidates"]) != int(max_candidates)
            or str(replay["goal"]) != goal
            or str(replay["operation_slot"] or "") != str(target_slot or "")
            or replay["pool_stage_id"] is None
            or int(replay["target_slot_count"]) != int(plan["target_slot_count"])
            or str(replay["selection_mode"]) != str(plan["selection_mode"])
            or str(replay["stage_operation_slot"] or "")
            != str(plan.get("operation_slot") or "")
            or abs(
                float(replay["max_total_charge_usd"] or 0)
                - float(max_total_charge_usd)
            ) > 1e-12
        )
