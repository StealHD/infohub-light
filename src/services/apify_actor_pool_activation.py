"""Atomic activation mechanics extracted from ActorOps."""

from __future__ import annotations

import math
from typing import Any

from .apify_actor_pool_management import _ensure_ops_symbols


def _ensure_module_symbols() -> None:
    ops = _ensure_ops_symbols()
    globals().update(vars(ops))


class ApifyActorPoolActivationMixin:
    def _activation_request(
        self,
        slots: Mapping[str, str | None],
        per_run_cap_usd: float | None,
    ) -> tuple[dict[str, str], list[str], float | None]:
        if set(slots) != set(SLOT_NAMES):
            raise ActorOpsError(
                "apify_actor_active_pool_incomplete",
                "Active pool requires all three named slots",
                status_code=422,
            )
        requested = {name: str(slots[name] or "") for name in SLOT_NAMES}
        populated = [name for name in SLOT_NAMES if requested[name]]
        if len(populated) not in {1, 2, 3}:
            raise ActorOpsError(
                "apify_actor_active_pool_incomplete",
                "Active pool does not contain the permitted number of slots",
                status_code=422,
            )
        cap = (
            None
            if per_run_cap_usd is None
            else _bounded_cost(per_run_cap_usd, maximum=100.0)
        )
        return requested, populated, cap

    def _activation_route_guard(
        self,
        connection: Any,
        route_id: str,
        *,
        expected_generation: int,
        populated_count: int,
        allow_compatibility: bool,
        reject_active_stage: bool,
    ) -> tuple[Any, dict[str, str]]:
        route = self._require_route(connection, route_id)
        if (
            populated_count == 1
            and not allow_compatibility
            and int(route["min_runtime_healthy"]) != 1
        ):
            raise ActorOpsError(
                "apify_actor_active_pool_incomplete",
                "Active pool does not contain the permitted number of slots",
                status_code=422,
            )
        if int(route["generation"]) != int(expected_generation):
            raise ActorOpsError(
                "apify_actor_route_generation_conflict",
                "Actor route changed; reload before retrying",
            )
        self._require_no_active_freshness_check(connection, route_id)
        if reject_active_stage:
            self._require_pool_mutation_safe(connection, route)
        rows = connection.execute(
            """SELECT slot_name, candidate_id, revision_id
               FROM apify_route_active_slots
               WHERE workspace_id = ? AND route_id = ?""",
            (self.workspace_id, route_id),
        ).fetchall()
        return route, {
            str(row["slot_name"]): str(row["revision_id"] or "") for row in rows
        }

    def _activation_load_revisions(
        self,
        connection: Any,
        *,
        route: Any,
        requested_slots: Mapping[str, str],
        populated_slot_names: list[str],
    ) -> dict[str, sqlite3.Row]:
        revision_rows: dict[str, sqlite3.Row] = {}
        for slot_name in populated_slot_names:
            row = connection.execute(
                """
                SELECT revision.*, candidate.route_key, candidate.state
                FROM apify_actor_adapter_revisions AS revision
                JOIN apify_actor_candidates AS candidate
                  ON candidate.id = revision.candidate_id
                WHERE revision.workspace_id = ? AND revision.revision_id = ?
                """,
                (self.workspace_id, requested_slots[slot_name]),
            ).fetchone()
            if row is None or str(row["route_key"]) != str(route["route_key"]):
                raise ActorOpsError(
                    "apify_actor_revision_not_found",
                    "Actor adapter revision was not found for this route",
                    status_code=404,
                )
            revision_rows[slot_name] = row
        return revision_rows

    def _activation_validate_rollback(
        self,
        *,
        rollback_revision_id: str | None,
        revision_rows: Mapping[str, sqlite3.Row],
        old_slots: Mapping[str, str],
        requested_slots: Mapping[str, str],
    ) -> None:
        if rollback_revision_id is None:
            return
        selected_count = sum(
            str(row["revision_id"]) == rollback_revision_id
            for row in revision_rows.values()
        )
        rollback_slot = next(
            (
                slot_name
                for slot_name, row in revision_rows.items()
                if str(row["revision_id"]) == rollback_revision_id
            ),
            None,
        )
        rollback_row = next(
            (
                row
                for row in revision_rows.values()
                if str(row["revision_id"]) == rollback_revision_id
            ),
            None,
        )
        if (
            selected_count != 1
            or rollback_row is None
            or str(rollback_row["lifecycle"])
            not in {"superseded", "legacy_builtin"}
        ):
            raise ActorOpsError(
                "apify_actor_rollback_revision_invalid",
                "Rollback requires one selected historical revision",
                status_code=422,
            )
        changed_slots = {
            slot_name
            for slot_name in SLOT_NAMES
            if old_slots.get(slot_name, "") != requested_slots[slot_name]
        }
        if changed_slots != {rollback_slot}:
            raise ActorOpsError(
                "apify_actor_rollback_scope_invalid",
                "Rollback may change only the selected historical Revision slot",
                status_code=422,
            )

    def _activation_validate_revisions(
        self,
        *,
        route: Any,
        revision_rows: Mapping[str, sqlite3.Row],
        old_slots: Mapping[str, str],
        rollback_revision_id: str | None,
        allow_probationary_primary: bool,
        allow_compatibility_single: bool,
        allow_compatibility_slot: bool,
        allow_legacy_compaction: bool,
    ) -> dict[str, str]:
        actor_ids = {str(row["actor_id"]) for row in revision_rows.values()}
        publishers = {
            str(row["publisher"]).casefold() for row in revision_rows.values()
        }
        if len(actor_ids) != len(revision_rows):
            raise ActorOpsError(
                "apify_actor_active_pool_duplicate",
                "Active pool Actor IDs must be unique",
                status_code=422,
            )
        compatibility = allow_compatibility_single or allow_compatibility_slot
        if not compatibility and len(publishers) < int(route["min_publishers"]):
            raise ActorOpsError(
                "apify_actor_active_pool_publishers",
                "Active pool does not satisfy publisher diversity",
                status_code=422,
            )
        effective_lifecycles: dict[str, str] = {}
        expedited = len(revision_rows) == 2
        for slot_name, row in revision_rows.items():
            lifecycle = str(row["lifecycle"])
            if (
                lifecycle == "legacy_builtin"
                and old_slots.get(slot_name) != str(row["revision_id"])
                and str(row["revision_id"]) != str(rollback_revision_id or "")
                and not compatibility
            ):
                raise ActorOpsError(
                    "apify_actor_rollback_revision_required",
                    "Historical legacy revisions require an explicit rollback",
                    status_code=422,
                )
            if lifecycle == "superseded":
                if str(row["revision_id"]) != str(rollback_revision_id or ""):
                    raise ActorOpsError(
                        "apify_actor_active_pool_uncertified",
                        "Superseded revisions require an explicit rollback",
                        status_code=422,
                    )
                prior_lifecycle = str(row["superseded_from_lifecycle"] or "")
                allowed_prior = (
                    {"certified"}
                    if slot_name in {"primary", "backup_1"}
                    else {"certified", "probationary"}
                )
                if prior_lifecycle not in allowed_prior:
                    raise ActorOpsError(
                        "apify_actor_rollback_evidence_incomplete",
                        "Historical revision lacks the required certification evidence",
                        status_code=412,
                    )
                lifecycle = prior_lifecycle
            allowed_lifecycle = self._pool_allowed_lifecycle(
                slot_name=slot_name,
                expedited=expedited,
                allow_probationary_primary=allow_probationary_primary,
                allow_compatibility_single=allow_compatibility_single,
                allow_compatibility_slot=allow_compatibility_slot,
                allow_legacy_compaction=allow_legacy_compaction,
            )
            if lifecycle not in allowed_lifecycle:
                raise ActorOpsError(
                    "apify_actor_active_pool_uncertified",
                    "Active pool lifecycle does not satisfy the 2+1 policy",
                    status_code=422,
                )
            effective_lifecycles[slot_name] = lifecycle
            if str(row["lifecycle"]) == "legacy_builtin":
                continue
            parsed = parse_actor_manifest(str(row["manifest_json"]))
            if not row["build_id"] or not row["build_number"] or not row["manifest_hash"]:
                raise ActorOpsError(
                    "apify_actor_active_pool_unpinned",
                    "Active pool revisions require an exact Build",
                    status_code=422,
                )
            if (
                parsed.actor_id != str(row["actor_id"])
                or parsed.build_number != str(row["build_number"])
                or actor_manifest_hash(parsed) != str(row["manifest_hash"])
            ):
                raise ActorOpsError(
                    "apify_actor_revision_integrity_failed",
                    "Actor adapter revision failed its integrity check",
                    status_code=412,
                )
            _assert_manifest_route_hosts(parsed, str(route["platform"]))
        return effective_lifecycles

    def _activation_restore_rollback(
        self,
        connection: Any,
        rollback_revision_id: str | None,
        revision_rows: Mapping[str, sqlite3.Row],
    ) -> None:
        if rollback_revision_id is None:
            return
        rollback_row = next(
            row
            for row in revision_rows.values()
            if str(row["revision_id"]) == rollback_revision_id
        )
        if str(rollback_row["lifecycle"]) == "superseded":
            connection.execute(
                """
                UPDATE apify_actor_adapter_revisions
                SET lifecycle = superseded_from_lifecycle
                WHERE workspace_id = ? AND revision_id = ?
                  AND lifecycle = 'superseded'
                  AND superseded_from_lifecycle IN ('probationary', 'certified')
                """,
                (self.workspace_id, rollback_revision_id),
            )

    def _activation_supersede_replaced(
        self,
        connection: Any,
        *,
        old_slots: Mapping[str, str],
        requested_slots: Mapping[str, str],
        now: str,
    ) -> None:
        replaced_revision_ids = {
            revision_id
            for revision_id in old_slots.values()
            if revision_id and revision_id not in set(requested_slots.values())
        }
        if not replaced_revision_ids:
            return
        placeholders = ",".join("?" for _ in replaced_revision_ids)
        connection.execute(
            f"""
            UPDATE apify_actor_adapter_revisions
            SET superseded_from_lifecycle = lifecycle,
                lifecycle = 'superseded', superseded_at = ?
            WHERE workspace_id = ? AND revision_id IN ({placeholders})
              AND lifecycle IN ('probationary', 'certified')
            """,
            (now, self.workspace_id, *sorted(replaced_revision_ids)),
        )

    def _activation_write_slots(
        self,
        connection: Any,
        *,
        route_id: str,
        route_key: str,
        old_slots: Mapping[str, str],
        requested_slots: Mapping[str, str],
        revision_rows: Mapping[str, sqlite3.Row],
        effective_lifecycles: Mapping[str, str],
        reactivate_verified_slots: bool,
        now: str,
    ) -> None:
        position_offset = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(position), 0) + 1
                FROM apify_actor_candidates
                WHERE workspace_id = ? AND route_key = ?
                """,
                (self.workspace_id, route_key),
            ).fetchone()[0]
        )
        connection.execute(
            """
            UPDATE apify_actor_candidates
            SET state = 'disabled', position = position + ?, updated_at = ?
            WHERE workspace_id = ? AND route_key = ?
            """,
            (position_offset, now, self.workspace_id, route_key),
        )
        for position, slot_name in enumerate(SLOT_NAMES):
            row = revision_rows.get(slot_name)
            if row is None:
                connection.execute(
                    """
                    INSERT INTO apify_route_active_slots (
                        workspace_id, route_id, slot_name, candidate_id,
                        revision_id, updated_at
                    ) VALUES (?, ?, ?, NULL, NULL, ?)
                    ON CONFLICT(route_id, slot_name) DO UPDATE SET
                        workspace_id = excluded.workspace_id,
                        candidate_id = NULL, revision_id = NULL,
                        updated_at = excluded.updated_at
                    """,
                    (self.workspace_id, route_id, slot_name, now),
                )
                continue
            unchanged = old_slots.get(slot_name) == str(row["revision_id"])
            selected_state = (
                str(row["state"])
                if unchanged and not reactivate_verified_slots
                else "probationary"
                if effective_lifecycles[slot_name] == "probationary"
                else "closed"
            )
            connection.execute(
                """
                INSERT INTO apify_route_active_slots (
                    workspace_id, route_id, slot_name, candidate_id,
                    revision_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(route_id, slot_name) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    candidate_id = excluded.candidate_id,
                    revision_id = excluded.revision_id,
                    updated_at = excluded.updated_at
                """,
                (
                    self.workspace_id,
                    route_id,
                    slot_name,
                    row["candidate_id"],
                    row["revision_id"],
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = ?, position = ?, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (selected_state, position, now, self.workspace_id, row["candidate_id"]),
            )

    def _activation_finalize_route(
        self,
        connection: Any,
        *,
        route: Any,
        route_id: str,
        expected_generation: int,
        selected_cap: float | None,
        allow_compatibility_single: bool,
        allow_compatibility_slot: bool,
        slots_changed: bool,
        now: str,
    ) -> None:
        connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET generation = generation + 1, mode = 'primary',
                policy_version = 'actor_ops_v3',
                status = CASE WHEN status = 'blocked_unknown_start' THEN status ELSE 'ready' END,
                per_run_cap_usd = COALESCE(?, per_run_cap_usd),
                admission_mode = CASE WHEN ? THEN 'compatibility' ELSE 'standard' END,
                min_runtime_healthy = CASE WHEN ? THEN 1 ELSE 2 END,
                min_publishers = CASE WHEN ? THEN 1 ELSE 2 END,
                compatibility_risk_code = CASE WHEN ? THEN 'single_actor_no_redundancy' ELSE NULL END,
                updated_at = ?
            WHERE workspace_id = ? AND route_id = ? AND generation = ?
            """,
            (
                selected_cap,
                int(allow_compatibility_single or allow_compatibility_slot),
                int(allow_compatibility_single),
                int(allow_compatibility_single),
                int(allow_compatibility_single),
                now,
                self.workspace_id,
                route_id,
                expected_generation,
            ),
        )
        connection.execute(
            """
            UPDATE apify_actor_routes
            SET generation = generation + 1,
                status = CASE WHEN blocked_reason IN (
                    'start_outcome_unknown', 'apify_start_outcome_unknown',
                    'apify_run_reconcile_required'
                ) THEN status ELSE 'ready' END,
                blocked_reason = CASE WHEN blocked_reason IN (
                    'start_outcome_unknown', 'apify_start_outcome_unknown',
                    'apify_run_reconcile_required'
                ) THEN blocked_reason ELSE NULL END,
                updated_at = ?
            WHERE workspace_id = ? AND route_key = ?
            """,
            (now, self.workspace_id, route["route_key"]),
        )
        if slots_changed:
            connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET validation_status = 'revalidation_pending',
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND route_id = ?
                """,
                (now, self.workspace_id, route_id),
            )

    def _activation_update_cap(
        self,
        connection: Any,
        *,
        route: Any,
        route_id: str,
        expected_generation: int,
        selected_cap: float | None,
        now: str,
    ) -> None:
        if selected_cap is None or math.isclose(
            selected_cap,
            float(route["per_run_cap_usd"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            return
        connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET generation = generation + 1, per_run_cap_usd = ?, updated_at = ?
            WHERE workspace_id = ? AND route_id = ? AND generation = ?
            """,
            (selected_cap, now, self.workspace_id, route_id, expected_generation),
        )
        connection.execute(
            """
            UPDATE apify_actor_routes
            SET generation = generation + 1, updated_at = ?
            WHERE workspace_id = ? AND route_key = ?
            """,
            (now, self.workspace_id, route["route_key"]),
        )

    def _replace_active_pool_standard(
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
        reactivate_verified_slots: bool = False,
    ) -> dict[str, Any]:
        _ensure_module_symbols()
        requested_slots, populated_slot_names, selected_cap = (
            self._activation_request(slots, per_run_cap_usd)
        )
        now = self._now_iso()
        with self._write() as connection:
            route, old_slots = self._activation_route_guard(
                connection,
                route_id,
                expected_generation=expected_generation,
                populated_count=len(populated_slot_names),
                allow_compatibility=(
                    allow_compatibility_single or allow_compatibility_slot
                ),
                reject_active_stage=reject_active_stage,
            )
            if rollback_revision_id is None and old_slots == requested_slots:
                self._activation_update_cap(
                    connection,
                    route=route,
                    route_id=route_id,
                    expected_generation=expected_generation,
                    selected_cap=selected_cap,
                    now=now,
                )
                return self.get_route(route_id)
            revision_rows = self._activation_load_revisions(
                connection,
                route=route,
                requested_slots=requested_slots,
                populated_slot_names=populated_slot_names,
            )
            self._activation_validate_rollback(
                rollback_revision_id=rollback_revision_id,
                revision_rows=revision_rows,
                old_slots=old_slots,
                requested_slots=requested_slots,
            )
            effective_lifecycles = self._activation_validate_revisions(
                route=route,
                revision_rows=revision_rows,
                old_slots=old_slots,
                rollback_revision_id=rollback_revision_id,
                allow_probationary_primary=allow_probationary_primary,
                allow_compatibility_single=allow_compatibility_single,
                allow_compatibility_slot=allow_compatibility_slot,
                allow_legacy_compaction=allow_legacy_compaction,
            )
            self._activation_restore_rollback(
                connection, rollback_revision_id, revision_rows
            )
            self._activation_supersede_replaced(
                connection,
                old_slots=old_slots,
                requested_slots=requested_slots,
                now=now,
            )
            self._activation_write_slots(
                connection,
                route_id=route_id,
                route_key=str(route["route_key"]),
                old_slots=old_slots,
                requested_slots=requested_slots,
                revision_rows=revision_rows,
                effective_lifecycles=effective_lifecycles,
                reactivate_verified_slots=reactivate_verified_slots,
                now=now,
            )
            self._activation_finalize_route(
                connection,
                route=route,
                route_id=route_id,
                expected_generation=expected_generation,
                selected_cap=selected_cap,
                allow_compatibility_single=allow_compatibility_single,
                allow_compatibility_slot=allow_compatibility_slot,
                slots_changed=any(
                    old_slots.get(name, "") != requested_slots[name]
                    for name in SLOT_NAMES
                ),
                now=now,
            )
        return self.get_route(route_id)
