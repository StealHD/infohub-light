"""Fixed-slot management helpers kept outside the legacy ActorOps service."""

from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations
import sqlite3
from typing import Any, Literal, Mapping


ROUTE_POOL_REMOVE_CONFIRMATION = "确认移出 Actor 主备池"
ROUTE_POOL_PROMOTE_CONFIRMATION = "确认设为主用 Actor"
MAX_OPERATOR_ROUTE_CAP_USD = 0.10


def _ops_module():
    # Import lazily: the main service inherits this mixin.
    from . import apify_actor_ops

    return apify_actor_ops


def _ensure_ops_symbols() -> Any:
    """Make extracted legacy helpers resolve their original private symbols.

    The service imports this mixin while it is being defined, so importing the
    individual constants above would create a cycle.  The implementations are
    invoked only after the service module is fully loaded; lazily sharing its
    internal helpers keeps this extraction behavior-preserving.
    """

    ops = _ops_module()
    globals().update(vars(ops))
    return ops


class ActorPoolManagementMixin:
    """Operations that mutate or project the fixed three-slot active pool."""

    def observation_probe_allowed(
        self, row: Any, manifest: Mapping[str, Any], evidence: Mapping[str, Any]
    ) -> bool:
        from .apify_actor_observed_probe import can_observe_youtube_probe

        return can_observe_youtube_probe(
            platform=str(row["platform"]), target_type=str(row["target_type"]),
            capability=str(row["capability"]), manifest=manifest,
            security_evidence=evidence,
        )

    def replace_active_pool(
        self,
        route_id: str,
        *,
        slots: Mapping[str, str | None],
        expected_generation: int,
        rollback_revision_id: str | None = None,
        per_run_cap_usd: float | None = None,
        allow_probationary_primary: bool = False,
        allow_compatibility_single: bool = False,
        allow_compatibility_slot: bool = False,
        reject_active_stage: bool = False,
        allow_legacy_compaction: bool = False,
    ) -> dict[str, Any]:
        """Activate an ordinary immutable pool through the extracted facade."""

        _ensure_ops_symbols()
        return self._replace_active_pool_standard(
            route_id,
            slots=slots,
            expected_generation=expected_generation,
            rollback_revision_id=rollback_revision_id,
            per_run_cap_usd=per_run_cap_usd,
            allow_probationary_primary=allow_probationary_primary,
            allow_compatibility_single=allow_compatibility_single,
            allow_compatibility_slot=allow_compatibility_slot,
            reject_active_stage=reject_active_stage,
            allow_legacy_compaction=allow_legacy_compaction,
        )

    def list_pool_candidates(
        self,
        route_id: str,
        *,
        goal: str,
        target_slot: str | None = None,
    ) -> dict[str, Any]:
        """Project candidates for a standard or X compatibility slot plan."""

        _ensure_ops_symbols()
        connection = self.store.connect()
        route = self._require_route(connection, route_id)
        if goal == "compatibility_single" and str(route["platform"]) != "x":
            # Compatibility trials intentionally use X-specific input rendering
            # and X-post semantics. Never expose their historical revisions on
            # another platform: that would produce a paid plan which cannot run.
            return {
                "schema_version": 1,
                "route_id": route_id,
                "generation": int(route["generation"]),
                "goal": goal,
                "target_slot": target_slot,
                "run_id": None,
                "required_selection_count": 1,
                "candidates": [],
                "blockers": ["compatibility_route_unsupported"],
            }
        if (
            goal in {"add_slot", "replace_slot"}
            and str(route["platform"]) == "x"
        ):
            blocked = self.pool_candidate_operation_blocker(
                connection, route, goal=goal, target_slot=target_slot
            )
            if blocked is not None:
                return blocked
            result = self._list_compatibility_candidates(connection, route)
            candidates = [
                {
                    **item,
                    "selectable": False,
                    "unavailable_reason": "actor_already_active",
                }
                if bool(item.get("active_in_route"))
                else item
                for item in result["candidates"]
            ]
            return {
                **result,
                "candidates": candidates,
                "schema_version": 3,
                "goal": goal,
                "target_slot": target_slot,
                "operation_mode": "compatibility_slot",
                "required_selection_count": 1,
            }
        return self._list_pool_candidates_standard(
            route_id, goal=goal, target_slot=target_slot
        )

    def list_verified_pool_candidates(
        self,
        route_id: str,
        *,
        goal: str,
        target_slot: str | None = None,
    ) -> dict[str, Any]:
        from .apify_actor_verified_catalog import list_verified_pool_candidates

        return list_verified_pool_candidates(
            self, route_id, goal=goal, target_slot=target_slot
        )

    def activate_verified_pool_candidates(self, route_id: str, **kwargs: Any) -> dict[str, Any]:
        """Enable only an already-settled browser catalog selection."""

        from .apify_actor_verified_catalog import activate_verified_pool_candidates

        return activate_verified_pool_candidates(self, route_id, **kwargs)

    def get_canary_plan(
        self,
        run_id: str,
        *,
        goal: str = "initial_pool",
        max_candidates: int = 3,
        max_total_charge_usd: float | None = None,
        candidate_ids: Any = None,
        candidate_validation_profiles: Any = None,
        target_slot_count: int | None = None,
        target_slot: str | None = None,
    ) -> dict[str, Any]:
        """Create an immutable plan; X slot actions use controlled trials."""

        _ensure_ops_symbols()
        if goal == "compatibility_single":
            connection = self.store.connect()
            run = connection.execute(
                """
                SELECT profile.platform
                FROM apify_actor_discovery_runs AS run
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = run.workspace_id
                 AND profile.route_id = run.route_id
                WHERE run.workspace_id = ? AND run.run_id = ?
                """,
                (self.workspace_id, str(run_id)),
            ).fetchone()
            if run is not None and str(run["platform"]) != "x":
                raise ActorOpsError(
                    "compatibility_route_unsupported",
                    "Compatibility single-Actor trials support X only",
                    status_code=412,
                )
        if goal in {"add_slot", "replace_slot"}:
            connection = self.store.connect()
            run = connection.execute(
                """
                SELECT run.*, profile.platform
                FROM apify_actor_discovery_runs AS run
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = run.workspace_id
                 AND profile.route_id = run.route_id
                WHERE run.workspace_id = ? AND run.run_id = ?
                """,
                (self.workspace_id, str(run_id)),
            ).fetchone()
            if run is not None and str(run["platform"]) == "x":
                return self._get_x_compatibility_slot_plan(
                    run,
                    goal=goal,
                    candidate_ids=tuple(candidate_ids or ()),
                    candidate_validation_profiles=candidate_validation_profiles,
                    max_total_charge_usd=max_total_charge_usd,
                    target_slot_count=target_slot_count,
                    target_slot=target_slot,
                )
        return self._get_canary_plan_standard(
            run_id,
            goal=goal,
            max_candidates=max_candidates,
            max_total_charge_usd=max_total_charge_usd,
            candidate_ids=candidate_ids,
            candidate_validation_profiles=candidate_validation_profiles,
            target_slot_count=target_slot_count,
            target_slot=target_slot,
        )

    def create_canary_batch(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        """Persist an approved plan, including X's compatibility-slot proof."""

        _ensure_ops_symbols()
        return self._create_canary_batch_standard(run_id, **kwargs)

    def prepare_pool_stage_source_validations(self, stage_id: str) -> list[str]:
        """Prepare ordinary stages after compatibility promotion if necessary."""

        _ensure_ops_symbols()
        return self._prepare_pool_stage_source_validations_standard(stage_id)

    def apply_pool_stage(self, stage_id: str, **kwargs: Any) -> dict[str, Any]:
        """Apply a source-proven stage through the existing CAS primitive."""

        _ensure_ops_symbols()
        return self._apply_pool_stage_standard(stage_id, **kwargs)

    def source_capability_ready(
        self,
        route_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        """Evaluate source binding readiness without exposing private targets."""

        _ensure_ops_symbols()
        return self._source_capability_ready_standard(
            route_id, connection=connection
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
            ("pool_stage_active", "apify_actor_pool_stages", "route_id = ? AND status NOT IN ('applied', 'stale', 'failed', 'cancelled', 'replan_required')", str(route["route_id"])),
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
            # A failed stage holds no live reservation.  Retire it with this
            # mutation so it cannot later be mistaken for the new pool plan.
            writer.execute(
                """UPDATE apify_actor_pool_stages
                   SET status = 'stale', updated_at = ?
                   WHERE workspace_id = ? AND route_id = ?
                     AND status = 'replan_required'""",
                (self._now_iso(), self.workspace_id, route_id),
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
            ("pool_stage_active", "apify_actor_pool_stages", "route_id = ? AND status NOT IN ('applied', 'stale', 'failed', 'cancelled', 'replan_required')", str(route["route_id"])),
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
            promote_reason = (
                "primary_slot" if name == "primary" else "slot_empty" if not occupied
                else "primary_slot_empty" if not slots.get("primary") else replace_reason
            )
            result[name] = {
                "add": not occupied and add_reason is None,
                "replace": occupied and replace_reason is None,
                "remove": occupied and remove_reason is None,
                "promote": promote_reason is None,
                "add_reason": add_reason,
                "replace_reason": replace_reason,
                "remove_reason": remove_reason,
                "promote_reason": promote_reason,
            }
        return result

    def promote_active_pool_slot(
        self,
        route_id: str,
        *,
        target_slot: Literal["backup_1", "backup_2"],
        expected_generation: int,
        confirmation: str,
    ) -> dict[str, Any]:
        """Atomically swap a current backup into primary without a paid run.

        This deliberately moves only existing active revisions.  It neither
        creates an Actor run nor changes the active revision set, so valid
        source evidence remains valid.  Normal staged-work and unknown-start
        fences still apply before the route generation can change.
        """

        ops = _ops_module()
        if confirmation != ROUTE_POOL_PROMOTE_CONFIRMATION:
            raise ops.ActorOpsError(
                "apify_actor_pool_promote_confirmation_required",
                "Setting a primary Actor requires the exact confirmation phrase",
                status_code=422,
            )
        with self._write() as writer:
            route = self._require_route(writer, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ops.ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before selecting the primary Actor",
                    status_code=409,
                )
            self._require_pool_mutation_safe(writer, route)
            self._require_no_active_freshness_check(writer, route_id)
            rows = writer.execute(
                """SELECT slot_name, candidate_id, revision_id
                   FROM apify_route_active_slots
                   WHERE workspace_id = ? AND route_id = ?""",
                (self.workspace_id, route_id),
            ).fetchall()
            slots = {str(row["slot_name"]): row for row in rows}
            primary, target = slots.get("primary"), slots.get(target_slot)
            if primary is None or target is None or not primary["revision_id"] or not target["revision_id"]:
                raise ops.ActorOpsError(
                    "apify_actor_pool_promote_slot_empty",
                    "Only an occupied backup slot can become the primary Actor",
                    status_code=409,
                )
            for slot_name, row in (("primary", target), (target_slot, primary)):
                writer.execute(
                    """UPDATE apify_route_active_slots
                       SET candidate_id = ?, revision_id = ?, updated_at = ?
                       WHERE workspace_id = ? AND route_id = ? AND slot_name = ?""",
                    (
                        row["candidate_id"], row["revision_id"], self._now_iso(),
                        self.workspace_id, route_id, slot_name,
                    ),
                )
            active_candidate_ids = [
                str(row["candidate_id"])
                for row in slots.values()
                if row["candidate_id"]
            ]
            if active_candidate_ids:
                offset = int(
                    writer.execute(
                        """SELECT COALESCE(MAX(position), 0) + 4
                           FROM apify_actor_candidates
                           WHERE workspace_id = ? AND route_key = ?""",
                        (self.workspace_id, route["route_key"]),
                    ).fetchone()[0]
                )
                placeholders = ", ".join("?" for _ in active_candidate_ids)
                writer.execute(
                    f"""UPDATE apify_actor_candidates
                        SET position = position + ?, updated_at = ?
                        WHERE workspace_id = ? AND id IN ({placeholders})""",
                    (offset, self._now_iso(), self.workspace_id, *active_candidate_ids),
                )
            for position, slot_name in enumerate(ops.SLOT_NAMES):
                row = target if slot_name == "primary" else primary if slot_name == target_slot else slots.get(slot_name)
                if row is not None and row["candidate_id"]:
                    writer.execute(
                        """UPDATE apify_actor_candidates SET position = ?, updated_at = ?
                           WHERE workspace_id = ? AND id = ?""",
                        (position, self._now_iso(), self.workspace_id, row["candidate_id"]),
                    )
            now = self._now_iso()
            writer.execute(
                """UPDATE apify_actor_route_profiles
                   SET generation = generation + 1, updated_at = ?
                   WHERE workspace_id = ? AND route_id = ? AND generation = ?""",
                (now, self.workspace_id, route_id, expected_generation),
            )
            writer.execute(
                """UPDATE apify_actor_routes
                   SET generation = generation + 1, last_switch_reason = 'manual_primary_selection',
                       last_switch_at = ?, updated_at = ?
                   WHERE workspace_id = ? AND route_key = ?""",
                (now, now, self.workspace_id, route["route_key"]),
            )
        return self.get_route(route_id)

    def set_route_price_cap(
        self,
        route_id: str,
        *,
        per_run_cap_usd: float,
        expected_generation: int,
    ) -> dict[str, Any]:
        """Change a Route's future-run ceiling without replacing its pool."""

        ops = _ops_module()
        cap = float(per_run_cap_usd)
        if not math.isfinite(cap) or not 0 < cap <= MAX_OPERATOR_ROUTE_CAP_USD:
            raise ops.ActorOpsError(
                "apify_actor_route_price_cap_invalid",
                "Actor Route price cap must be between zero and the operator ceiling",
                status_code=422,
            )
        with self._write() as writer:
            route = self._require_route(writer, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ops.ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before changing its price cap",
                    status_code=409,
                )
            self._require_pool_mutation_safe(writer, route)
            self._require_no_active_freshness_check(writer, route_id)
            self._activation_update_cap(
                writer,
                route=route,
                route_id=route_id,
                expected_generation=expected_generation,
                selected_cap=cap,
                now=self._now_iso(),
            )
        return self.get_route(route_id)

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
        goal = str(stage["goal"])
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
                 AND (
                     (revision.lifecycle IN ('probationary', 'certified')
                      AND revision.build_id IS NOT NULL
                      AND revision.build_number IS NOT NULL
                      AND revision.manifest_hash IS NOT NULL)
                     OR (
                         ? = 1 AND revision.lifecycle = 'legacy_builtin'
                         AND revision.observed_manifest = 1
                     )
                 ) ORDER BY item.ordinal""",
            (
                self.workspace_id,
                str(stage["batch_id"]),
                str(stage["route_id"]),
                int(goal in {"add_slot", "replace_slot"}),
            ),
        ).fetchall()
        if goal == "complete_third":
            if not successful:
                return None
            target = {"primary": base.get("primary") or None, "backup_1": base.get("backup_1") or None, "backup_2": str(successful[0]["revision_id"])}
        elif goal == "replace_slot" and int(stage["target_slot_count"] or 0) == 1:
            if not successful:
                return None
            target = {
                "primary": str(successful[0]["revision_id"]),
                "backup_1": None,
                "backup_2": None,
            }
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
