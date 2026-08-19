"""Canary plans and source-validation staging for Actor pools."""

from __future__ import annotations

from typing import Any

from .apify_actor_pool_management import _ensure_ops_symbols


def _ensure_module_symbols() -> None:
    ops = _ensure_ops_symbols()
    globals().update(vars(ops))


class ApifyActorPoolStagingMixin:
    def _get_canary_plan_standard(
        self,
        run_id: str,
        *,
        goal: Literal[
            "initial_pool", "complete_third", "upgrade_legacy",
            "compatibility_single", "add_slot", "replace_slot",
        ] = "initial_pool",
        max_candidates: int = 3,
        max_total_charge_usd: float | None = None,
        candidate_ids: Sequence[str] | None = None,
        candidate_validation_profiles: Sequence[Mapping[str, Any]] | None = None,
        target_slot_count: int | None = None,
        target_slot: str | None = None,
    ) -> dict[str, Any]:
        """Return a server-selected or administrator-selected paid plan."""

        _ensure_module_symbols()
        if goal == "compatibility_single":
            if candidate_ids is None:
                raise ActorOpsError(
                    "apify_actor_manual_candidate_set_incomplete",
                    "Compatibility mode requires one explicitly selected Actor",
                    status_code=422,
                )
            return self._get_compatibility_canary_plan(
                run_id,
                candidate_ids=tuple(candidate_ids),
                max_total_charge_usd=max_total_charge_usd,
                target_slot_count=target_slot_count,
            )

        if candidate_ids is not None:
            return self._get_pool_stage_canary_plan(
                run_id,
                goal=goal,
                max_candidates=len(candidate_ids),
                max_total_charge_usd=max_total_charge_usd,
                candidate_ids=tuple(candidate_ids),
                candidate_validation_profiles=candidate_validation_profiles,
                target_slot_count=target_slot_count,
                target_slot=target_slot,
            )

        if goal == "initial_pool":
            return self._get_initial_canary_plan(
                run_id,
                max_candidates=max_candidates,
                max_total_charge_usd=(
                    BATCH_CANARY_MAX_TOTAL_USD
                    if max_total_charge_usd is None
                    else max_total_charge_usd
                ),
            )
        if goal not in {
            "initial_pool", "complete_third", "upgrade_legacy",
            "add_slot", "replace_slot",
        }:
            raise ActorOpsError(
                "apify_actor_pool_stage_goal_invalid",
                "Actor pool workflow goal is invalid",
                status_code=422,
            )
        return self._get_pool_stage_canary_plan(
            run_id,
            goal=goal,
            max_candidates=max_candidates,
            max_total_charge_usd=max_total_charge_usd,
            candidate_ids=None,
            candidate_validation_profiles=candidate_validation_profiles,
            target_slot_count=target_slot_count,
            target_slot=target_slot,
        )


    def _create_canary_batch_standard(
        self,
        run_id: str,
        *,
        expected_generation: int,
        expected_plan_hash: str,
        approval_id: str,
        confirmation: str,
        max_candidates: int,
        max_total_charge_usd: float,
        created_by_user_id: str,
        reference_fingerprints: Mapping[str, str],
        goal: Literal[
            "initial_pool", "complete_third", "upgrade_legacy",
            "compatibility_single", "add_slot", "replace_slot",
        ] = "initial_pool",
        candidate_ids: Sequence[str] | None = None,
        candidate_validation_profiles: Sequence[Mapping[str, Any]] | None = None,
        target_slot_count: int | None = None,
        target_slot: str | None = None,
    ) -> dict[str, Any]:
        _ensure_module_symbols()
        if goal == "initial_pool" and candidate_ids is None:
            return self._create_initial_canary_batch(
                run_id,
                expected_generation=expected_generation,
                expected_plan_hash=expected_plan_hash,
                approval_id=approval_id,
                confirmation=confirmation,
                max_candidates=max_candidates,
                max_total_charge_usd=max_total_charge_usd,
                created_by_user_id=created_by_user_id,
                reference_fingerprints=reference_fingerprints,
            )
        if goal not in {
            "initial_pool",
            "complete_third",
            "upgrade_legacy",
            "compatibility_single",
            "add_slot",
            "replace_slot",
        }:
            raise ActorOpsError(
                "apify_actor_pool_stage_goal_invalid",
                "Actor pool workflow goal is invalid",
                status_code=422,
            )
        return self._create_pool_stage_canary_batch(
            run_id,
            goal=goal,
            expected_generation=expected_generation,
            expected_plan_hash=expected_plan_hash,
            approval_id=approval_id,
            confirmation=confirmation,
            max_candidates=max_candidates,
            max_total_charge_usd=max_total_charge_usd,
            created_by_user_id=created_by_user_id,
            reference_fingerprints=reference_fingerprints,
            candidate_ids=(
                tuple(candidate_ids) if candidate_ids is not None else None
            ),
            candidate_validation_profiles=candidate_validation_profiles,
            target_slot_count=target_slot_count,
            target_slot=target_slot,
        )

    def _stage_for_source_preparation(
        self, connection: Any, stage_id: str
    ) -> sqlite3.Row:
        stage = connection.execute(
            """
            SELECT stage.*
            FROM apify_actor_pool_stages AS stage
            JOIN apify_actor_canary_batches AS batch
              ON batch.workspace_id = stage.workspace_id
             AND batch.batch_id = stage.initial_batch_id
            WHERE stage.workspace_id = ? AND stage.stage_id = ?
            """,
            (self.workspace_id, stage_id),
        ).fetchone()
        if stage is None:
            raise ActorOpsError(
                "apify_actor_pool_stage_not_found",
                "Actor pool stage was not found",
                status_code=404,
            )
        if str(stage["status"]) not in {
            "queued", "validating_route", "validating_sources"
        }:
            raise ActorOpsError(
                "apify_actor_pool_stage_conflict",
                "Actor pool stage cannot prepare source validations",
                status_code=409,
            )
        return stage

    def _stage_freeze_source_target(
        self,
        connection: Any,
        *,
        stage_id: str,
        now: str,
    ) -> dict[str, str | None] | None:
        target = self._pool_stage_target_slots(connection, stage_id)
        if target is None:
            connection.execute(
                """
                UPDATE apify_actor_pool_stages
                SET status = 'replan_required',
                    last_error_code = 'candidate_shortfall', updated_at = ?
                WHERE workspace_id = ? AND stage_id = ?
                """,
                (now, self.workspace_id, stage_id),
            )
            return None
        target_hash = revision_set_hash(
            {name: value or "" for name, value in target.items()}
        )
        connection.execute(
            """
            UPDATE apify_actor_pool_stages
            SET target_primary_revision_id = ?, target_backup_1_revision_id = ?,
                target_backup_2_revision_id = ?, target_pool_hash = ?,
                status = 'validating_sources', updated_at = ?
            WHERE workspace_id = ? AND stage_id = ?
            """,
            (
                target["primary"],
                target["backup_1"],
                target["backup_2"],
                target_hash,
                now,
                self.workspace_id,
                stage_id,
            ),
        )
        return target

    def _stage_source_is_current(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        source: sqlite3.Row,
        stage_id: str,
        now: str,
    ) -> bool:
        source_id = str(source["source_id"])
        catalog = connection.execute(
            "SELECT enabled FROM source_catalog WHERE workspace_id = ? AND id = ?",
            (self.workspace_id, source_id),
        ).fetchone()
        if catalog is None or not bool(catalog["enabled"]):
            connection.execute(
                """
                UPDATE apify_actor_pool_stage_sources
                SET status = 'skipped', updated_at = ?
                WHERE workspace_id = ? AND stage_id = ? AND source_id = ?
                """,
                (now, self.workspace_id, stage_id, source_id),
            )
            return False
        binding = connection.execute(
            """
            SELECT generation, target_fingerprint
            FROM apify_source_route_bindings
            WHERE workspace_id = ? AND source_id = ? AND route_id = ?
            """,
            (self.workspace_id, source_id, str(stage["route_id"])),
        ).fetchone()
        if (
            binding is not None
            and int(binding["generation"]) == int(source["binding_generation"])
            and str(binding["target_fingerprint"])
            == str(source["target_fingerprint"])
        ):
            return True
        connection.execute(
            """
            UPDATE apify_actor_pool_stage_sources
            SET status = 'failed', last_error_code = 'source_binding_changed',
                updated_at = ?
            WHERE workspace_id = ? AND stage_id = ? AND source_id = ?
            """,
            (now, self.workspace_id, stage_id, source_id),
        )
        return False

    def _stage_source_proof_exists(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        source: sqlite3.Row,
        revision_id: str,
    ) -> bool:
        return connection.execute(
            """
            SELECT 1 FROM apify_actor_validations
            WHERE workspace_id = ? AND route_id = ? AND source_id = ?
              AND revision_id = ? AND kind = 'source_canary'
              AND status = 'succeeded' AND cost_final = 1
              AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
              AND target_fingerprint = ?
            LIMIT 1
            """,
            (
                self.workspace_id,
                str(stage["route_id"]),
                str(source["source_id"]),
                revision_id,
                str(source["target_fingerprint"]),
            ),
        ).fetchone() is not None

    def _stage_queue_source_validation(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        source: sqlite3.Row,
        stage_id: str,
        slot_name: str,
        revision_id: str,
        now: str,
    ) -> str:
        settings = connection.execute(
            """
            SELECT timeout_seconds, sample_items, max_charge_usd, profile_hash
            FROM apify_actor_pool_stage_candidate_settings
            WHERE workspace_id = ? AND stage_id = ? AND revision_id = ?
            """,
            (self.workspace_id, stage_id, revision_id),
        ).fetchone()
        timeout_seconds = int(
            settings["timeout_seconds"]
            if settings is not None
            else VALIDATION_TIMEOUT_SECONDS_DEFAULT
        )
        sample_items = int(
            settings["sample_items"] if settings is not None else 1
        )
        validation_cap = float(
            settings["max_charge_usd"]
            if settings is not None
            else VALIDATION_MAX_CHARGE_USD_DEFAULT
        )
        profile_hash = str(
            settings["profile_hash"]
            if settings is not None
            else validation_profile_hash(
                timeout_seconds=timeout_seconds,
                sample_items=sample_items,
                max_charge_usd=validation_cap,
            )
        )
        validation_id = f"apify-validation-{uuid.uuid4().hex}"
        approval_hash = hashlib.sha256(
            f"{stage['approval_key_hash']}:{source['source_id']}:{slot_name}:{revision_id}".encode(
                "utf-8"
            )
        ).hexdigest()
        connection.execute(
            """
            INSERT INTO apify_actor_validations (
                validation_id, workspace_id, route_id, source_id, revision_id,
                attempt_id, discovery_run_id, kind, approval_key_hash,
                approved_generation, approved_max_cost_usd, status,
                semantic_outcome, cost_usd, cost_final, counts_toward_canary,
                target_fingerprint, validation_timeout_seconds,
                validation_sample_items, validation_profile_hash, created_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, 'source_canary', ?, ?, ?,
                'queued', NULL, NULL, 0, 0, ?, ?, ?, ?, ?, NULL)
            """,
            (
                validation_id,
                self.workspace_id,
                str(stage["route_id"]),
                str(source["source_id"]),
                revision_id,
                str(stage["discovery_run_id"]),
                approval_hash,
                int(source["binding_generation"]),
                validation_cap,
                str(source["target_fingerprint"]),
                timeout_seconds,
                sample_items,
                profile_hash,
                now,
            ),
        )
        column = {
            "primary": "primary_validation_id",
            "backup_1": "backup_1_validation_id",
            "backup_2": "backup_2_validation_id",
        }[slot_name]
        connection.execute(
            f"""
            UPDATE apify_actor_pool_stage_sources
            SET {column} = ?, updated_at = ?
            WHERE workspace_id = ? AND stage_id = ? AND source_id = ?
            """,
            (validation_id, now, self.workspace_id, stage_id, str(source["source_id"])),
        )
        return validation_id

    def _stage_queue_missing_source_proofs(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        source: sqlite3.Row,
        stage_id: str,
        target: Mapping[str, str | None],
        now: str,
    ) -> tuple[int, list[str]]:
        passed = 0
        queued: list[str] = []
        for slot_name in SLOT_NAMES:
            revision_id = target[slot_name]
            if revision_id is None:
                continue
            if self._stage_source_proof_exists(
                connection, stage=stage, source=source, revision_id=revision_id
            ):
                passed += 1
                continue
            queued.append(
                self._stage_queue_source_validation(
                    connection,
                    stage=stage,
                    source=source,
                    stage_id=stage_id,
                    slot_name=slot_name,
                    revision_id=revision_id,
                    now=now,
                )
            )
        return passed, queued

    def _stage_prepare_source_proofs(
        self,
        connection: Any,
        *,
        stage: sqlite3.Row,
        stage_id: str,
        target: Mapping[str, str | None],
        now: str,
    ) -> list[str]:
        validation_ids: list[str] = []
        rows = connection.execute(
            """
            SELECT * FROM apify_actor_pool_stage_sources
            WHERE workspace_id = ? AND stage_id = ? ORDER BY source_id
            """,
            (self.workspace_id, stage_id),
        ).fetchall()
        for source in rows:
            if not self._stage_source_is_current(
                connection, stage=stage, source=source, stage_id=stage_id, now=now
            ):
                continue
            passed, queued = self._stage_queue_missing_source_proofs(
                connection,
                stage=stage,
                source=source,
                stage_id=stage_id,
                target=target,
                now=now,
            )
            connection.execute(
                """
                UPDATE apify_actor_pool_stage_sources
                SET passed_count = ?,
                    status = CASE WHEN ? = 0 THEN 'succeeded' ELSE 'queued' END,
                    updated_at = ?
                WHERE workspace_id = ? AND stage_id = ? AND source_id = ?
                """,
                (
                    passed,
                    len(queued),
                    now,
                    self.workspace_id,
                    stage_id,
                    str(source["source_id"]),
                ),
            )
            validation_ids.extend(queued)
        return validation_ids

    def _prepare_pool_stage_source_validations_standard(
        self,
        stage_id: str,
    ) -> list[str]:
        """Freeze the server-selected target and queue only missing source proofs."""

        _ensure_module_symbols()
        with self._write() as connection:
            now = self._now_iso()
            stage = self._stage_for_source_preparation(connection, stage_id)
            target = self._stage_freeze_source_target(
                connection, stage_id=stage_id, now=now
            )
            if target is None:
                return []
            validation_ids = self._stage_prepare_source_proofs(
                connection,
                stage=stage,
                stage_id=stage_id,
                target=target,
                now=now,
            )
            if not validation_ids:
                self._refresh_pool_stage_sources_locked(connection, stage_id)
        return validation_ids
