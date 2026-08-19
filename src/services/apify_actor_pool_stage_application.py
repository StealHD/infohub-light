"""Atomic application of a validated Actor pool stage."""

from __future__ import annotations

from typing import Any

from .apify_actor_pool_management import _ensure_ops_symbols


def _ensure_module_symbols() -> None:
    ops = _ensure_ops_symbols()
    globals().update(vars(ops))


class ApifyActorPoolStageApplicationMixin:
    def _stage_application_stage(
        self, connection: Any, stage_id: str, apply_hash: str
    ) -> sqlite3.Row:
        stage = connection.execute(
            """
            SELECT * FROM apify_actor_pool_stages
            WHERE workspace_id = ? AND stage_id = ?
            """,
            (self.workspace_id, stage_id),
        ).fetchone()
        if stage is None:
            raise ActorOpsError(
                "apify_actor_pool_stage_not_found",
                "Actor pool stage was not found",
                status_code=404,
            )
        if str(stage["status"]) != "applied":
            return stage
        if str(stage["apply_key_hash"] or "") != apply_hash:
            raise ActorOpsError(
                "apify_actor_pool_stage_apply_id_conflict",
                "Apply id was already used for another action",
                status_code=409,
            )
        return stage

    def _stage_application_target(
        self, connection: Any, stage: sqlite3.Row
    ) -> dict[str, str | None]:
        target = self._frozen_pool_stage_target(stage)
        if target is not None:
            return target
        if str(stage["status"]) in {"validating_sources", "apply_ready"}:
            connection.execute(
                """
                UPDATE apify_actor_pool_stages
                SET status = 'replan_required',
                    last_error_code = 'candidate_shortfall', updated_at = ?
                WHERE workspace_id = ? AND stage_id = ?
                  AND status IN ('validating_sources', 'apply_ready')
                """,
                (self._now_iso(), self.workspace_id, str(stage["stage_id"])),
            )
        raise ActorOpsError(
            "apify_actor_pool_stage_precondition_incomplete",
            "Staged Actor target is incomplete; choose another candidate",
            status_code=412,
        )

    def _stage_application_require_settlement(
        self, connection: Any, stage: sqlite3.Row
    ) -> None:
        settlement = connection.execute(
            """
            SELECT batch.status, batch.cost_final, batch.actual_cost_usd,
                   COUNT(item.ordinal) AS item_count,
                   COALESCE(SUM(item.cost_final), 0) AS final_item_count
            FROM apify_actor_canary_batches AS batch
            LEFT JOIN apify_actor_canary_batch_items AS item
              ON item.workspace_id = batch.workspace_id AND item.batch_id = batch.batch_id
            WHERE batch.workspace_id = ? AND batch.batch_id = ?
            GROUP BY batch.batch_id
            """,
            (self.workspace_id, str(stage["initial_batch_id"])),
        ).fetchone()
        if (
            settlement is None
            or str(settlement["status"]) != "activation_ready"
            or not bool(settlement["cost_final"])
            or int(settlement["final_item_count"] or 0)
            != int(settlement["item_count"] or 0)
        ):
            raise ActorOpsError(
                "apify_actor_pool_stage_precondition_incomplete",
                "Staged Actor validation costs are not final",
                status_code=412,
            )
        source_settlement = connection.execute(
            """
            SELECT COUNT(validation.validation_id) AS validation_count,
                   COALESCE(SUM(validation.cost_final), 0) AS final_count,
                   COALESCE(SUM(CASE WHEN validation.cost_final = 1
                       THEN COALESCE(validation.cost_usd, 0) ELSE 0 END), 0) AS actual_cost_usd
            FROM apify_actor_pool_stage_sources AS source
            JOIN apify_actor_validations AS validation
              ON validation.workspace_id = source.workspace_id
             AND validation.validation_id IN (
                 source.primary_validation_id, source.backup_1_validation_id,
                 source.backup_2_validation_id
             )
            WHERE source.workspace_id = ? AND source.stage_id = ?
            """,
            (self.workspace_id, str(stage["stage_id"])),
        ).fetchone()
        if (
            source_settlement is None
            or int(source_settlement["validation_count"] or 0)
            != int(source_settlement["final_count"] or 0)
            or float(settlement["actual_cost_usd"] or 0)
            + float(source_settlement["actual_cost_usd"] or 0)
            > float(stage["max_total_charge_usd"]) + 1e-9
        ):
            raise ActorOpsError(
                "apify_actor_pool_stage_precondition_incomplete",
                "Staged source validation costs are not final",
                status_code=412,
            )

    def _stage_application_route(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        expected_generation: int,
    ) -> sqlite3.Row:
        route = self._require_route(connection, str(stage["route_id"]))
        if (
            int(route["generation"]) != int(expected_generation)
            or int(stage["base_generation"]) != int(expected_generation)
        ):
            raise ActorOpsError(
                "apify_actor_route_generation_conflict",
                "Actor route changed; reload before applying",
            )
        rows = connection.execute(
            """
            SELECT slot_name, revision_id FROM apify_route_active_slots
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, str(stage["route_id"])),
        ).fetchall()
        active_hash = revision_set_hash(
            {str(row["slot_name"]): str(row["revision_id"] or "") for row in rows}
        )
        if active_hash != str(stage["base_pool_hash"]):
            raise ActorOpsError(
                "apify_actor_pool_stage_stale",
                "Active Actor pool changed while the replacement was staged",
                status_code=409,
            )
        return route

    def _stage_application_compatibility(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        target: Mapping[str, str | None],
    ) -> tuple[bool, bool]:
        compatibility_single = str(stage["goal"]) == "compatibility_single"
        if compatibility_single or str(stage["goal"]) not in {"add_slot", "replace_slot"}:
            return compatibility_single, False
        rows = connection.execute(
            """
            SELECT lifecycle, observed_manifest FROM apify_actor_adapter_revisions
            WHERE workspace_id = ? AND revision_id IN (?, ?, ?)
            """,
            (
                self.workspace_id,
                target["primary"],
                target["backup_1"],
                target["backup_2"],
            ),
        ).fetchall()
        return False, any(
            str(row["lifecycle"] or "") == "legacy_builtin"
            and bool(row["observed_manifest"])
            for row in rows
        )

    def _stage_application_require_sources(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        compatibility_single: bool,
    ) -> None:
        if compatibility_single:
            return
        self._refresh_pool_stage_sources_locked(connection, str(stage["stage_id"]))
        refreshed = connection.execute(
            """
            SELECT status FROM apify_actor_pool_stages
            WHERE workspace_id = ? AND stage_id = ?
            """,
            (self.workspace_id, str(stage["stage_id"])),
        ).fetchone()
        if refreshed is None or str(refreshed["status"]) != "apply_ready":
            raise ActorOpsError(
                "apify_actor_pool_stage_source_validation_incomplete",
                "Enabled sources changed or still require validation",
                status_code=412,
            )

    def _stage_application_require_idle(
        self, connection: Any, route: sqlite3.Row
    ) -> None:
        active_attempt = connection.execute(
            """
            SELECT 1 FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND status IN ('reserved', 'running', 'start_outcome_unknown')
            LIMIT 1
            """,
            (self.workspace_id, str(route["route_key"])),
        ).fetchone()
        if active_attempt is not None or str(route["status"]) == "blocked_unknown_start":
            raise ActorOpsError(
                "apify_actor_pool_stage_apply_inflight",
                "Actor pool cannot switch while an attempt is unresolved",
                status_code=409,
            )

    def _stage_application_record(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        stage_id: str,
        apply_hash: str,
        generation: int,
        compatibility_single: bool,
        target: Mapping[str, str | None],
    ) -> None:
        populated = sum(revision_id is not None for revision_id in target.values())
        ready_status = f"ready_{populated}of{populated}"
        if compatibility_single:
            connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET validation_status = 'ready_1of1',
                    verified_revision_set_hash = ?, updated_at = ?
                WHERE workspace_id = ? AND route_id = ?
                """,
                (str(stage["target_pool_hash"]), self._now_iso(), self.workspace_id, str(stage["route_id"])),
            )
        else:
            connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET validation_status = ?, verified_revision_set_hash = ?, updated_at = ?
                WHERE workspace_id = ? AND route_id = ? AND source_id IN (
                    SELECT stage_source.source_id
                    FROM apify_actor_pool_stage_sources AS stage_source
                    JOIN source_catalog AS source
                      ON source.workspace_id = stage_source.workspace_id
                     AND source.id = stage_source.source_id
                    WHERE stage_source.workspace_id = ? AND stage_source.stage_id = ?
                      AND stage_source.status = 'succeeded' AND source.enabled = 1
                )
                """,
                (
                    ready_status,
                    str(stage["target_pool_hash"]),
                    self._now_iso(),
                    self.workspace_id,
                    str(stage["route_id"]),
                    self.workspace_id,
                    stage_id,
                ),
            )
        now = self._now_iso()
        connection.execute(
            """
            UPDATE apify_actor_pool_stages
            SET status = 'applied', apply_key_hash = ?,
                applied_route_generation = ?, applied_at = ?, updated_at = ?
            WHERE workspace_id = ? AND stage_id = ? AND status = 'apply_ready'
            """,
            (apply_hash, generation, now, now, self.workspace_id, stage_id),
        )

    def _apply_pool_stage_standard(
        self,
        stage_id: str,
        *,
        expected_generation: int,
        expected_plan_hash: str,
        apply_id: str,
        confirmation: str,
    ) -> dict[str, Any]:
        _ensure_module_symbols()
        if confirmation != ROUTE_POOL_ACTIVATION_CONFIRMATION:
            raise ActorOpsError(
                "apify_actor_route_activation_confirmation_required",
                "Route activation requires the exact confirmation phrase",
                status_code=422,
            )
        if not _HEX_64_RE.fullmatch(str(expected_plan_hash)):
            raise ActorOpsError(
                "apify_actor_canary_plan_invalid",
                "Pool stage plan hash is invalid",
                status_code=422,
            )
        apply_hash = _approval_key_hash(apply_id)
        with self._write() as connection:
            stage = self._stage_application_stage(connection, stage_id, apply_hash)
            if str(stage["status"]) == "applied":
                return self.get_route(str(stage["route_id"]))
            if str(stage["status"]) != "apply_ready":
                raise ActorOpsError(
                    "apify_actor_pool_stage_precondition_incomplete",
                    "Staged Actor source validation is not complete",
                    status_code=412,
                )
            if str(stage["plan_hash"]) != str(expected_plan_hash):
                raise ActorOpsError(
                    "apify_actor_canary_plan_conflict",
                    "Pool stage plan changed; reload before applying",
                    status_code=409,
                )
            target = self._stage_application_target(connection, stage)
            self._stage_application_require_settlement(connection, stage)
            route = self._stage_application_route(
                connection, stage=stage, expected_generation=expected_generation
            )
            compatibility_single, compatibility_slot = self._stage_application_compatibility(
                connection, stage=stage, target=target
            )
            self._stage_application_require_sources(
                connection, stage=stage, compatibility_single=compatibility_single
            )
            self._stage_application_require_idle(connection, route)
            result = self.replace_active_pool(
                str(stage["route_id"]),
                slots=target,
                expected_generation=expected_generation,
                allow_probationary_primary=True,
                allow_compatibility_single=compatibility_single,
                allow_compatibility_slot=compatibility_slot,
                reactivate_verified_slots=True,
            )
            self._stage_application_record(
                connection,
                stage=stage,
                stage_id=stage_id,
                apply_hash=apply_hash,
                generation=int(result["generation"]),
                compatibility_single=compatibility_single,
                target=target,
            )
        return self.get_route(str(stage["route_id"]))
