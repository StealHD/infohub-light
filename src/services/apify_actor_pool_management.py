"""Fixed-slot management helpers kept outside the legacy ActorOps service."""

from __future__ import annotations

from itertools import combinations
import sqlite3
from typing import Any, Literal, Mapping


ROUTE_POOL_REMOVE_CONFIRMATION = "确认移出 Actor 主备池"


def _ops_module():
    # Import lazily: the main service inherits this mixin.
    from . import apify_actor_ops

    return apify_actor_ops


class ActorPoolManagementMixin:
    """Operations that mutate or project the fixed three-slot active pool."""

    def _require_pool_mutation_safe(
        self, connection: sqlite3.Connection, route: sqlite3.Row
    ) -> None:
        """Reject mutations while a stage, attempt, or unknown start is live."""

        ops = _ops_module()
        stage = connection.execute(
            """SELECT 1 FROM apify_actor_pool_stages
               WHERE workspace_id = ? AND route_id = ?
                 AND status NOT IN ('applied', 'stale', 'failed', 'cancelled')
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
        allow_legacy_compaction: bool,
    ) -> set[str]:
        if allow_compatibility_single or (expedited and allow_legacy_compaction):
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
        count = (
            int(requested_count)
            if requested_count is not None
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
        """Compute publisher diversity after retaining or replacing one slot."""

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
        """Keep replay idempotence scoped to the frozen slot operation."""

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

    def _pool_remove_blocker(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
        *,
        target_slot: str,
    ) -> str | None:
        ops = _ops_module()
        if target_slot not in ops.SLOT_NAMES:
            return "target_slot_required"
        if str(route["status"]) == "blocked_unknown_start":
            return "apify_start_outcome_unknown"
        checks = (
            (
                "freshness_active",
                "apify_actor_freshness_checks",
                "route_id = ? AND status IN ('queued', 'running')",
                str(route["route_id"]),
            ),
            ("pool_stage_active", "apify_actor_pool_stages", "route_id = ? AND status NOT IN ('applied', 'stale', 'failed', 'cancelled')", str(route["route_id"])),
            ("actor_attempt_active", "apify_actor_attempts", "route_key = ? AND status IN ('reserved', 'running', 'start_outcome_unknown')", str(route["route_key"])),
        )
        for reason, table, predicate, value in checks:
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE workspace_id = ? AND {predicate} LIMIT 1",
                (self.workspace_id, value),
            ).fetchone() is not None:
                return reason
        rows = connection.execute(
            """SELECT slot.slot_name, slot.revision_id, revision.publisher
               FROM apify_route_active_slots AS slot
               LEFT JOIN apify_actor_adapter_revisions AS revision
                 ON revision.workspace_id = slot.workspace_id
                AND revision.revision_id = slot.revision_id
               WHERE slot.workspace_id = ? AND slot.route_id = ?""",
            (self.workspace_id, str(route["route_id"])),
        ).fetchall()
        by_slot = {str(row["slot_name"]): row for row in rows}
        if not by_slot.get(target_slot) or not by_slot[target_slot]["revision_id"]:
            return "slot_empty"
        remaining = [
            by_slot[name] for name in ops.SLOT_NAMES
            if name != target_slot and by_slot.get(name) and by_slot[name]["revision_id"]
        ]
        if len(remaining) < int(route["min_runtime_healthy"]):
            return "pool_runtime_minimum"
        publishers = {str(row["publisher"] or "").casefold() for row in remaining}
        if len(publishers - {""}) < int(route["min_publishers"]):
            return "pool_publisher_minimum"
        return None

    def remove_active_pool_slot(
        self,
        route_id: str,
        *,
        target_slot: Literal["primary", "backup_1", "backup_2"],
        expected_generation: int,
        confirmation: str,
    ) -> dict[str, Any]:
        """Remove one active revision without erasing its evidence history."""

        ops = _ops_module()
        if confirmation != ROUTE_POOL_REMOVE_CONFIRMATION:
            raise ops.ActorOpsError(
                "apify_actor_pool_remove_confirmation_required",
                "Removing an Actor requires the exact confirmation phrase",
                status_code=422,
            )
        with self._write() as writer:
            route = self._require_route(writer, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ops.ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before removing a pool slot",
                    status_code=409,
                )
            blocker = self._pool_remove_blocker(
                writer, route, target_slot=target_slot
            )
            if blocker is not None:
                raise ops.ActorOpsError(
                    f"apify_actor_pool_remove_{blocker}",
                    "This Actor slot cannot be removed safely right now",
                    status_code=409,
                )
            rows = writer.execute(
                """SELECT slot_name, revision_id FROM apify_route_active_slots
                   WHERE workspace_id = ? AND route_id = ?""",
                (self.workspace_id, route_id),
            ).fetchall()
            by_slot = {
                str(row["slot_name"]): row["revision_id"] for row in rows
            }
            remaining = [
                str(by_slot[name]) for name in ops.SLOT_NAMES
                if name != target_slot and by_slot.get(name)
            ]
            compacted = {
                name: remaining[index] if index < len(remaining) else None
                for index, name in enumerate(ops.SLOT_NAMES)
            }
            # The nested savepoint keeps the existing CAS activation primitive
            # and this evidence projection in one outer transaction.
            result = self.replace_active_pool(
                route_id, slots=compacted, expected_generation=expected_generation,
                allow_probationary_primary=True, reject_active_stage=True,
                allow_legacy_compaction=True,
            )
            target_hash = ops.revision_set_hash(
                {name: compacted[name] or "" for name in ops.SLOT_NAMES}
            )
            bindings = writer.execute(
                """SELECT source_id, target_fingerprint
                   FROM apify_source_route_bindings
                   WHERE workspace_id = ? AND route_id = ?""",
                (self.workspace_id, route_id),
            ).fetchall()
            for binding in bindings:
                verified = all(
                    writer.execute(
                        """SELECT 1 FROM apify_actor_validations
                           WHERE workspace_id = ? AND route_id = ?
                             AND source_id = ? AND revision_id = ?
                             AND kind = 'source_canary' AND status = 'succeeded'
                             AND cost_final = 1
                             AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                             AND target_fingerprint = ? LIMIT 1""",
                        (self.workspace_id, route_id, str(binding["source_id"]),
                         revision_id, str(binding["target_fingerprint"])),
                    ).fetchone() is not None
                    for revision_id in remaining
                )
                status = (
                    f"ready_{len(remaining)}of{len(remaining)}"
                    if verified
                    else "pending"
                )
                writer.execute(
                    """UPDATE apify_source_route_bindings
                       SET validation_status = ?, verified_revision_set_hash = ?,
                           updated_at = ?
                       WHERE workspace_id = ? AND route_id = ? AND source_id = ?""",
                    (
                        status,
                        target_hash if verified else None,
                        self._now_iso(),
                        self.workspace_id,
                        route_id,
                        str(binding["source_id"]),
                    ),
                )
        return result

    def _pool_slot_operation_blocker(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
        *,
        goal: str,
        target_slot: str | None,
    ) -> str | None:
        ops = _ops_module()
        if goal not in {"add_slot", "replace_slot"}:
            return None
        if target_slot not in ops.SLOT_NAMES:
            return "target_slot_required"
        if str(route["status"]) == "blocked_unknown_start":
            return "apify_start_outcome_unknown"
        checks = (
            ("pool_stage_active", "apify_actor_pool_stages", "route_id = ? AND status NOT IN ('applied', 'stale', 'failed', 'cancelled')", str(route["route_id"])),
            ("actor_attempt_active", "apify_actor_attempts", "route_key = ? AND status IN ('reserved', 'running', 'start_outcome_unknown')", str(route["route_key"])),
            ("freshness_active", "apify_actor_freshness_checks", "route_id = ? AND status IN ('queued', 'running')", str(route["route_id"])),
        )
        for reason, table, predicate, value in checks:
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE workspace_id = ? AND {predicate} LIMIT 1",
                (self.workspace_id, value),
            ).fetchone() is not None:
                return reason
        slots = {
            str(row["slot_name"]): str(row["revision_id"] or "")
            for row in connection.execute(
                """SELECT slot_name, revision_id FROM apify_route_active_slots
                   WHERE workspace_id = ? AND route_id = ?""",
                (self.workspace_id, str(route["route_id"])),
            ).fetchall()
        }
        if goal == "add_slot":
            first_empty = next((name for name in ops.SLOT_NAMES if not slots.get(name)), None)
            if first_empty is None:
                return "pool_full"
            if target_slot != first_empty:
                return "add_requires_first_empty_slot"
            if sum(bool(slots.get(name)) for name in ops.SLOT_NAMES) < int(route["min_runtime_healthy"]):
                return "pool_runtime_minimum_incomplete"
        elif not slots.get(target_slot):
            return "replace_requires_occupied_slot"
        return None

    def slot_operations(self, route_id: str) -> dict[str, dict[str, Any]]:
        connection = self.store.connect()
        route = self._require_route(connection, route_id)
        ops = _ops_module()
        slots = {
            str(row["slot_name"]): str(row["revision_id"] or "")
            for row in connection.execute(
                """SELECT slot_name, revision_id FROM apify_route_active_slots
                   WHERE workspace_id = ? AND route_id = ?""",
                (self.workspace_id, route_id),
            ).fetchall()
        }
        result: dict[str, dict[str, Any]] = {}
        for name in ops.SLOT_NAMES:
            occupied = bool(slots.get(name))
            add_reason = self._pool_slot_operation_blocker(connection, route, goal="add_slot", target_slot=name)
            replace_reason = self._pool_slot_operation_blocker(connection, route, goal="replace_slot", target_slot=name)
            remove_reason = self._pool_remove_blocker(connection, route, target_slot=name) if occupied else "slot_empty"
            result[name] = {
                "add": not occupied and add_reason is None,
                "replace": occupied and replace_reason is None,
                "remove": occupied and remove_reason is None,
                "add_reason": add_reason,
                "replace_reason": replace_reason,
                "remove_reason": remove_reason,
            }
        return result

    def _pool_stage_target_slots(
        self,
        connection: sqlite3.Connection,
        stage_id: str,
    ) -> dict[str, str | None] | None:
        ops = _ops_module()
        stage = connection.execute(
            """SELECT stage.*, batch.batch_id FROM apify_actor_pool_stages AS stage
               JOIN apify_actor_canary_batches AS batch
                 ON batch.workspace_id = stage.workspace_id
                AND batch.batch_id = stage.initial_batch_id
               WHERE stage.workspace_id = ? AND stage.stage_id = ?""",
            (self.workspace_id, stage_id),
        ).fetchone()
        if stage is None:
            raise ops.ActorOpsError("apify_actor_pool_stage_not_found", "Actor pool stage was not found", status_code=404)
        base = {
            str(row["slot_name"]): str(row["revision_id"] or "")
            for row in connection.execute(
                """SELECT slot_name, revision_id FROM apify_route_active_slots
                   WHERE workspace_id = ? AND route_id = ?""",
                (self.workspace_id, str(stage["route_id"])),
            ).fetchall()
        }
        if ops.revision_set_hash(base) != str(stage["base_pool_hash"]):
            return None
        if str(stage["goal"]) == "compatibility_single":
            row = connection.execute(
                """SELECT item.revision_id FROM apify_actor_canary_batch_items AS item
                   JOIN apify_actor_validations AS validation
                     ON validation.workspace_id = item.workspace_id
                    AND validation.validation_id = item.validation_id
                   WHERE item.workspace_id = ? AND item.batch_id = ?
                     AND item.status = 'succeeded' AND validation.status = 'succeeded'
                     AND validation.cost_final = 1
                     AND (validation.semantic_outcome = 'valid_nonempty'
                          OR validation.semantic_outcome = 'evidence_reused' AND EXISTS (
                              SELECT 1 FROM apify_actor_validations AS proof
                              WHERE proof.workspace_id = validation.workspace_id
                                AND proof.route_id = validation.route_id
                                AND proof.revision_id = validation.revision_id
                                AND proof.kind = 'route_reference' AND proof.status = 'succeeded'
                                AND proof.cost_final = 1 AND proof.semantic_outcome = 'valid_nonempty'))
                   ORDER BY item.ordinal LIMIT 1""",
                (self.workspace_id, str(stage["batch_id"])),
            ).fetchone()
            return None if row is None else {"primary": str(row["revision_id"]), "backup_1": None, "backup_2": None}
        successful = connection.execute(
            """SELECT revision.revision_id, revision.actor_id, revision.publisher, item.ordinal
               FROM apify_actor_canary_batch_items AS item
               JOIN apify_actor_adapter_revisions AS revision
                 ON revision.workspace_id = item.workspace_id AND revision.revision_id = item.revision_id
               WHERE item.workspace_id = ? AND item.batch_id = ?
                 AND EXISTS (SELECT 1 FROM apify_actor_validations AS proof
                     WHERE proof.workspace_id = item.workspace_id AND proof.route_id = ?
                       AND proof.revision_id = item.revision_id AND proof.kind = 'route_reference'
                       AND proof.status = 'succeeded' AND proof.cost_final = 1
                       AND proof.semantic_outcome IN ('valid_nonempty', 'valid_empty'))
                 AND revision.lifecycle IN ('probationary', 'certified')
                 AND revision.build_id IS NOT NULL AND revision.build_number IS NOT NULL
                 AND revision.manifest_hash IS NOT NULL ORDER BY item.ordinal""",
            (self.workspace_id, str(stage["batch_id"]), str(stage["route_id"])),
        ).fetchall()
        goal = str(stage["goal"])
        if goal == "complete_third":
            if not successful:
                return None
            target = {"primary": base.get("primary") or None, "backup_1": base.get("backup_1") or None, "backup_2": str(successful[0]["revision_id"])}
        elif goal in {"add_slot", "replace_slot"}:
            slot = str(stage["operation_slot"] or "")
            if slot not in ops.SLOT_NAMES or not successful:
                return None
            target = {name: base.get(name) or None for name in ops.SLOT_NAMES}
            if (goal == "add_slot" and target[slot]) or (goal == "replace_slot" and not target[slot]):
                return None
            target[slot] = str(successful[0]["revision_id"])
        elif int(stage["target_slot_count"] or 2) == 1:
            if not successful:
                return None
            target = {"primary": str(successful[0]["revision_id"]), "backup_1": None, "backup_2": None}
        elif int(stage["target_slot_count"] or 2) == 3:
            if len(successful) < 3:
                return None
            selected = successful[:3]
            if len({str(row["actor_id"]) for row in selected}) != 3 or len({str(row["publisher"]).casefold() for row in selected}) < 2:
                return None
            target = {name: str(row["revision_id"]) for name, row in zip(ops.SLOT_NAMES, selected, strict=True)}
        else:
            pair = next((pair for pair in combinations(successful, 2) if str(pair[0]["actor_id"]) != str(pair[1]["actor_id"]) and str(pair[0]["publisher"]).casefold() != str(pair[1]["publisher"]).casefold()), None)
            if pair is None:
                return None
            target = {"primary": str(pair[0]["revision_id"]), "backup_1": str(pair[1]["revision_id"]), "backup_2": None}
        values = [value for value in target.values() if value]
        return None if len(set(values)) != len(values) else target
