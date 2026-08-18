"""Small candidate-projection helpers for Actor pool selection."""

from __future__ import annotations

from typing import Any

from .apify_actor_pool_management import _ensure_ops_symbols
from .apify_actor_candidate_quality import actor_store_quality, quality_sort_key


def _ensure_module_symbols() -> None:
    ops = _ensure_ops_symbols()
    globals().update(vars(ops))


class ApifyActorPoolCandidateProjectionMixin:

    def _candidate_sources_are_verified(
        self,
        connection: Any,
        *,
        route_id: str,
        revision_id: str,
    ) -> bool:
        """Return whether this revision has settled proof for every live source.

        A route-reference Canary only proves that an Actor can run.  It does
        not prove that it returned the configured account/channel for each
        enabled source.  Manual selection is deliberately stricter: callers
        may only receive a revision after those source-specific proofs are
        settled as well.
        """

        missing = connection.execute(
            """
            SELECT 1
            FROM apify_source_route_bindings AS binding
            JOIN source_catalog AS source
              ON source.workspace_id = binding.workspace_id
             AND source.id = binding.source_id
            WHERE binding.workspace_id = ? AND binding.route_id = ?
              AND source.enabled = 1
              AND NOT EXISTS (
                  SELECT 1 FROM apify_actor_validations AS proof
                  WHERE proof.workspace_id = binding.workspace_id
                    AND proof.route_id = binding.route_id
                    AND proof.source_id = binding.source_id
                    AND proof.revision_id = ?
                    AND proof.kind = 'source_canary'
                    AND proof.status = 'succeeded'
                    AND proof.cost_final = 1
                    AND proof.semantic_outcome IN ('valid_nonempty', 'valid_empty')
                    AND proof.target_fingerprint = binding.target_fingerprint
              )
            LIMIT 1
            """,
            (self.workspace_id, route_id, revision_id),
        ).fetchone()
        return missing is None

    def _candidate_empty_response(
        self,
        *,
        route_id: str,
        route: Any,
        goal: str,
        target_slot: str | None,
        required_count: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "route_id": route_id,
            "generation": int(route["generation"]),
            "goal": goal,
            "target_slot": target_slot,
            "run_id": None,
            "required_selection_count": required_count,
            "candidates": [],
            "blockers": ["candidate_refresh_required"],
        }

    def _candidate_latest_run(self, connection: Any, route_id: str) -> Any:
        return connection.execute(
            """
            SELECT run_id, stage FROM apify_actor_discovery_runs
            WHERE workspace_id = ? AND route_id = ?
              AND COALESCE(error_code, '') != 'superseded_duplicate_refresh'
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (self.workspace_id, route_id),
        ).fetchone()

    def _candidate_active_rows(self, connection: Any, route_id: str) -> list[Any]:
        return connection.execute(
            """
            SELECT slot.slot_name, revision.candidate_id, revision.actor_id,
                   revision.lifecycle, revision.publisher, revision.pricing_json,
                   candidate.display_name
            FROM apify_route_active_slots AS slot
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
              AND slot.revision_id IS NOT NULL
            ORDER BY CASE slot.slot_name
                WHEN 'primary' THEN 1 WHEN 'backup_1' THEN 2 ELSE 3 END
            """,
            (self.workspace_id, route_id),
        ).fetchall()

    def _candidate_discovery_rows(
        self, connection: Any, *, route: Any, run_id: str
    ) -> list[Any]:
        return connection.execute(
            """
            SELECT candidate.id AS candidate_id, candidate.display_name,
                   candidate.state AS candidate_state,
                   candidate.last_error_code AS candidate_error_code,
                   candidate.position, revision.revision_id, revision.actor_id,
                   revision.publisher, revision.build_id, revision.build_number,
                   revision.manifest_hash, revision.manifest_json,
                   revision.input_schema_hash, revision.output_schema_hash,
                   revision.pricing_json, revision.lifecycle, revision.created_at,
                   revision.security_evidence_json,
                   EXISTS (SELECT 1 FROM apify_actor_validations AS proof
                     WHERE proof.workspace_id = revision.workspace_id
                       AND proof.route_id = ?
                       AND proof.revision_id = revision.revision_id
                       AND proof.kind = 'route_reference'
                       AND proof.status = 'succeeded'
                       AND proof.cost_final = 1
                       AND proof.semantic_outcome IN ('valid_nonempty', 'valid_empty'))
                     AS already_validated,
                   EXISTS (SELECT 1 FROM apify_actor_validations AS validation
                     WHERE validation.workspace_id = revision.workspace_id
                       AND validation.revision_id = revision.revision_id
                       AND validation.kind = 'route_reference'
                       AND validation.status IN ('queued', 'running')) AS validation_in_flight
            FROM apify_actor_discovery_run_revisions AS association
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = association.workspace_id
             AND revision.revision_id = association.revision_id
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE association.workspace_id = ? AND association.run_id = ?
              AND candidate.route_key = ?
            ORDER BY candidate.position, revision.created_at DESC, revision.revision_id DESC
            """,
            (
                str(route["route_id"]),
                self.workspace_id,
                run_id,
                str(route["route_key"]),
            ),
        ).fetchall()

    def _candidate_upgrade_rows(
        self, connection: Any, *, route: Any, route_id: str, run_id: str
    ) -> list[Any]:
        return connection.execute(
            """
            SELECT candidate.id AS candidate_id, candidate.display_name,
                   candidate.state AS candidate_state,
                   candidate.last_error_code AS candidate_error_code,
                   candidate.position, revision.revision_id, revision.actor_id,
                   revision.publisher, revision.build_id, revision.build_number,
                   revision.manifest_hash, revision.manifest_json,
                   revision.input_schema_hash, revision.output_schema_hash,
                   revision.pricing_json, revision.lifecycle, revision.created_at,
                   revision.security_evidence_json,
                   EXISTS (SELECT 1 FROM apify_actor_validations AS validation
                     WHERE validation.workspace_id = revision.workspace_id
                       AND validation.revision_id = revision.revision_id
                       AND validation.kind = 'route_reference'
                       AND validation.status IN ('queued', 'running')) AS validation_in_flight,
                   EXISTS (SELECT 1 FROM apify_actor_validations AS proof
                     WHERE proof.workspace_id = revision.workspace_id AND proof.route_id = ?
                       AND proof.revision_id = revision.revision_id
                       AND proof.kind = 'route_reference' AND proof.status = 'succeeded'
                       AND proof.cost_final = 1
                       AND proof.semantic_outcome IN ('valid_nonempty', 'valid_empty')) AS already_validated,
                   EXISTS (SELECT 1 FROM apify_actor_discovery_run_revisions AS current_link
                     WHERE current_link.workspace_id = revision.workspace_id AND current_link.run_id = ?
                       AND current_link.revision_id = revision.revision_id) AS in_current_run
            FROM apify_actor_adapter_revisions AS revision
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id AND candidate.id = revision.candidate_id
            WHERE revision.workspace_id = ? AND candidate.route_key = ?
              AND revision.lifecycle IN ('static_valid', 'probationary', 'certified')
              AND revision.build_id IS NOT NULL AND revision.build_number IS NOT NULL
              AND revision.manifest_hash IS NOT NULL
              AND EXISTS (SELECT 1 FROM apify_actor_discovery_run_revisions AS association
                JOIN apify_actor_discovery_runs AS source_run
                  ON source_run.workspace_id = association.workspace_id AND source_run.run_id = association.run_id
                WHERE association.workspace_id = revision.workspace_id
                  AND association.revision_id = revision.revision_id AND source_run.route_id = ?)
            ORDER BY already_validated DESC, in_current_run DESC,
                     revision.created_at DESC, revision.revision_id DESC
            """,
            (route_id, run_id, self.workspace_id, str(route["route_key"]), route_id),
        ).fetchall()

    def _candidate_unavailable_reason(
        self,
        connection: Any,
        *,
        row: Any,
        route_id: str,
        goal: str,
        active_ids: set[str],
        active_lifecycles: dict[str, str],
    ) -> tuple[str | None, bool]:
        actor_id = str(row["actor_id"])
        existing_upgrade = (
            goal == "upgrade_legacy"
            and active_lifecycles.get(actor_id) == "legacy_builtin"
            and str(row["lifecycle"]) != "legacy_builtin"
        )
        if actor_id in active_ids and not existing_upgrade:
            return "actor_already_active", existing_upgrade
        if str(row["candidate_state"]) == "disabled" and row["candidate_error_code"]:
            return str(row["candidate_error_code"]), existing_upgrade
        if str(row["lifecycle"]) not in {"static_valid", "probationary", "certified"}:
            return "candidate_not_validated", existing_upgrade
        if not row["build_id"] or not row["build_number"] or not row["manifest_hash"]:
            return "candidate_exact_build_missing", existing_upgrade
        if bool(row["validation_in_flight"]):
            return "candidate_validation_in_progress", existing_upgrade
        if goal == "upgrade_legacy" and _pricing_exceeds_usd_cap(
            _safe_json(row["pricing_json"], {}), VALIDATION_MAX_CHARGE_USD_DEFAULT
        ):
            return "actor_price_above_route_cap", existing_upgrade
        return self._revision_canary_block_reason(
            connection, route_id, str(row["revision_id"])
        ), existing_upgrade

    def _candidate_failure(self, connection: Any, *, route_id: str, revision_id: str) -> Any:
        return connection.execute(
            """
            SELECT semantic_outcome, cost_usd, cost_final,
                   validation_timeout_seconds, validation_sample_items,
                   approved_max_cost_usd, validation_profile_hash,
                   failure_fingerprint, duration_seconds, dataset_row_count,
                   mapped_item_count, completed_at
            FROM apify_actor_validations
            WHERE workspace_id = ? AND route_id = ? AND revision_id = ?
              AND status = 'failed' AND failure_fingerprint IS NOT NULL
            ORDER BY completed_at DESC, created_at DESC, validation_id DESC LIMIT 1
            """,
            (self.workspace_id, route_id, revision_id),
        ).fetchone()

    def _candidate_evaluation(
        self, connection: Any, *, route_id: str, candidate_id: str, actor_id: str, row: Any
    ) -> Any:
        fingerprint = actor_evidence_fingerprint(
            route_id=route_id,
            candidate_id=candidate_id,
            actor_id=actor_id,
            build_id=str(row["build_id"] or ""),
            build_number=str(row["build_number"] or ""),
            manifest_hash=str(row["manifest_hash"] or ""),
            pricing=_safe_json(row["pricing_json"], {}),
            input_schema_hash=str(row["input_schema_hash"] or ""),
            output_schema_hash=str(row["output_schema_hash"] or ""),
        )
        return connection.execute(
            """
            SELECT evaluation_id, reason_code, deterministic, attempt_count,
                   first_seen_at, last_seen_at, retry_requested_at
            FROM apify_actor_evaluation_history
            WHERE workspace_id = ? AND route_id = ? AND candidate_id = ?
              AND evidence_fingerprint = ? AND policy_mode = 'standard'
              AND outcome = 'failed'
            ORDER BY last_seen_at DESC, evaluation_id DESC LIMIT 1
            """,
            (self.workspace_id, route_id, candidate_id, fingerprint),
        ).fetchone()

    def _candidate_validation_options(
        self,
        *,
        route: Any,
        route_id: str,
        goal: str,
        candidate_id: str,
        row: Any,
        failure: Any,
    ) -> tuple[dict[str, Any], int, int, float, list[int], float]:
        _ensure_module_symbols()
        supported = _manifest_supports_sample_items(row["manifest_json"])
        failure_timeout = int(
            failure["validation_timeout_seconds"]
            if failure is not None
            else VALIDATION_TIMEOUT_SECONDS_DEFAULT
        )
        timeout = (
            VALIDATION_TIMEOUT_SECONDS_DEFAULT
            if goal == "upgrade_legacy"
            else failure_timeout
        )
        sample_items = int(failure["validation_sample_items"] if failure else 1)
        cap = float(
            failure["approved_max_cost_usd"]
            if failure is not None and failure["approved_max_cost_usd"] is not None
            else min(VALIDATION_MAX_CHARGE_USD_DEFAULT, float(route["per_run_cap_usd"]))
        )
        if goal == "upgrade_legacy":
            cap = min(cap, VALIDATION_MAX_CHARGE_USD_DEFAULT, float(route["per_run_cap_usd"]))
        allowed = [1, 3] if goal == "upgrade_legacy" and supported else [1, 3, 5] if supported else [1]
        limit = (
            min(cap, VALIDATION_MAX_CHARGE_USD_DEFAULT, float(route["per_run_cap_usd"]))
            if goal == "upgrade_legacy"
            else VALIDATION_MAX_CHARGE_USD_LIMIT
        )
        profile_hash = validation_profile_hash(
            timeout_seconds=timeout, sample_items=sample_items, max_charge_usd=cap
        )
        return (
            {
                "timeout_seconds": timeout,
                "timeout_min_seconds": VALIDATION_TIMEOUT_SECONDS_MIN,
                "timeout_max_seconds": VALIDATION_TIMEOUT_SECONDS_MAX,
                "sample_items": sample_items,
                "allowed_sample_items": allowed,
                "max_charge_usd": round(cap, 6),
                "max_charge_limit_usd": round(limit, 6),
                "supports_sample_items": supported,
                "options_hash": _validation_options_hash(
                    route_id=route_id,
                    generation=int(route["generation"]),
                    candidate_id=candidate_id,
                    revision_id=str(row["revision_id"]),
                    build_id=str(row["build_id"] or ""),
                    build_number=str(row["build_number"] or ""),
                    manifest_hash=str(row["manifest_hash"] or ""),
                    supports_sample_items=supported,
                ),
                "profile_hash": profile_hash,
            },
            failure_timeout,
            sample_items,
            cap,
            allowed,
            limit,
        )

    def _candidate_failure_summary(
        self,
        *,
        failure: Any,
        row: Any,
        goal: str,
        supports_sample_items: bool,
        failure_timeout: int,
        sample_items: int,
        cap: float,
        profile_hash: str,
        allowed: list[int],
        unavailable_reason: str | None,
    ) -> tuple[dict[str, Any] | None, list[int], str | None]:
        _ensure_module_symbols()
        if failure is None:
            return None, allowed, unavailable_reason
        code = str(failure["semantic_outcome"] or "")
        if not _SAFE_ACTOROPS_ERROR_CODE_RE.fullmatch(code):
            code = "apify_actor_validation_failed"
        if goal == "upgrade_legacy" and not bool(row["already_validated"]):
            if code in {"suspicious_empty", "apify_actor_suspicious_empty"}:
                allowed = [1, 3] if supports_sample_items and sample_items < 3 else [sample_items]
                if sample_items >= 3 or not supports_sample_items:
                    unavailable_reason = "actor_validation_sample_limit_reached"
            else:
                unavailable_reason = "actor_validation_retry_not_permitted"
        summary = {
            "code": code,
            "duration_seconds": int(failure["duration_seconds"]) if failure["duration_seconds"] is not None else None,
            "dataset_row_count": int(failure["dataset_row_count"]) if failure["dataset_row_count"] is not None else None,
            "mapped_item_count": int(failure["mapped_item_count"]) if failure["mapped_item_count"] is not None else None,
            "actual_cost_usd": round(float(failure["cost_usd"]), 6) if failure["cost_usd"] is not None else None,
            "cost_final": bool(failure["cost_final"]),
            "timeout_seconds": failure_timeout,
            "sample_items": sample_items,
            "max_charge_usd": round(cap, 6),
            "profile_hash": profile_hash,
            "completed_at": str(failure["completed_at"] or "") or None,
        }
        return summary, allowed, unavailable_reason

    def _candidate_item(
        self,
        connection: Any,
        *,
        route: Any,
        route_id: str,
        goal: str,
        row: Any,
        active_ids: set[str],
        active_lifecycles: dict[str, str],
    ) -> dict[str, Any]:
        _ensure_module_symbols()
        candidate_id, actor_id = str(row["candidate_id"]), str(row["actor_id"])
        unavailable, existing_upgrade = self._candidate_unavailable_reason(
            connection, row=row, route_id=route_id, goal=goal,
            active_ids=active_ids, active_lifecycles=active_lifecycles,
        )
        failure = self._candidate_failure(
            connection, route_id=route_id, revision_id=str(row["revision_id"])
        )
        evaluation = self._candidate_evaluation(
            connection, route_id=route_id, candidate_id=candidate_id, actor_id=actor_id, row=row
        )
        if unavailable is None and evaluation is not None and bool(evaluation["deterministic"]) and evaluation["retry_requested_at"] is None:
            unavailable = "actor_evaluation_deterministic_failure"
        options, failure_timeout, sample_items, cap, allowed, limit = self._candidate_validation_options(
            route=route, route_id=route_id, goal=goal, candidate_id=candidate_id, row=row, failure=failure
        )
        summary, allowed, unavailable = self._candidate_failure_summary(
            failure=failure, row=row, goal=goal,
            supports_sample_items=bool(options["supports_sample_items"]),
            failure_timeout=failure_timeout, sample_items=sample_items, cap=cap,
            profile_hash=str(options["profile_hash"]), allowed=allowed,
            unavailable_reason=unavailable,
        )
        options["allowed_sample_items"] = allowed
        fully_verified = bool(row["already_validated"]) and self._candidate_sources_are_verified(
            connection, route_id=route_id, revision_id=str(row["revision_id"])
        )
        return {
            "candidate_id": candidate_id,
            "actor_public_name": _actor_public_name(row["display_name"], row["publisher"], row["actor_id"]),
            "publisher": str(row["publisher"]),
            "pricing": _safe_json(row["pricing_json"], {}),
            "store_quality": actor_store_quality(
                _safe_json(row["security_evidence_json"], {})
            ),
            "max_validation_charge_usd": round(limit, 6),
            "validation_options": options,
            "last_failure": summary,
            "evaluation_history": dict(evaluation) if evaluation is not None else None,
            # This public flag is intentionally stronger than the SQL alias
            # above: a user-visible candidate means route *and* current source
            # evidence succeeded and its cost was reconciled.
            "already_validated": fully_verified,
            "requires_profile_change": bool(failure is not None and failure["failure_fingerprint"]),
            "existing_actor_upgrade": existing_upgrade,
            "selectable": unavailable is None,
            "unavailable_reason": unavailable,
        }

    def _candidate_remembered_failures(
        self,
        connection: Any,
        *,
        route_id: str,
        route: Any,
        active_ids: set[str],
        seen_candidates: set[str],
        seen_actors: set[str],
        candidates: list[dict[str, Any]],
    ) -> None:
        _ensure_module_symbols()
        rows = connection.execute(
            """
            SELECT evaluation.evaluation_id, evaluation.candidate_id,
                   evaluation.reason_code, evaluation.attempt_count,
                   evaluation.first_seen_at, evaluation.last_seen_at,
                   evaluation.retry_requested_at, candidate.actor_id,
                   candidate.display_name
            FROM apify_actor_evaluation_history AS evaluation
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = evaluation.workspace_id AND candidate.id = evaluation.candidate_id
            WHERE evaluation.workspace_id = ? AND evaluation.route_id = ?
              AND evaluation.policy_mode = 'standard' AND evaluation.outcome = 'failed'
              AND evaluation.deterministic = 1
            ORDER BY evaluation.last_seen_at DESC, evaluation.evaluation_id DESC LIMIT 90
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        for failure in rows:
            candidate_id = str(failure["candidate_id"])
            actor_id = str(failure["actor_id"])
            if candidate_id in seen_candidates or actor_id in seen_actors:
                continue
            publisher = actor_id.split("/", 1)[0] if "/" in actor_id else "unknown"
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "actor_public_name": _actor_public_name(failure["display_name"], publisher, actor_id),
                    "publisher": publisher,
                    "pricing": {},
                    "store_quality": actor_store_quality(None),
                    "max_validation_charge_usd": round(
                        min(VALIDATION_MAX_CHARGE_USD_DEFAULT, float(route["per_run_cap_usd"])), 6
                    ),
                    "validation_options": None,
                    "last_failure": None,
                    "evaluation_history": {
                        "evaluation_id": str(failure["evaluation_id"]),
                        "reason_code": str(failure["reason_code"]),
                        "deterministic": True,
                        "attempt_count": int(failure["attempt_count"]),
                        "first_seen_at": str(failure["first_seen_at"]),
                        "last_seen_at": str(failure["last_seen_at"]),
                        "retry_requested_at": failure["retry_requested_at"],
                    },
                    "requires_profile_change": False,
                    "existing_actor_upgrade": actor_id in active_ids,
                    "selectable": False,
                    "unavailable_reason": "actor_evaluation_deterministic_failure",
                }
            )
            seen_candidates.add(candidate_id)
            seen_actors.add(actor_id)
            if len(candidates) >= 30:
                return

    def _candidate_legacy_placeholders(
        self,
        *,
        latest: Any,
        active_rows: list[Any],
        seen_actors: set[str],
        candidates: list[dict[str, Any]],
        route: Any,
    ) -> None:
        _ensure_module_symbols()
        pending = str(latest["stage"]) in {
            "queued", "searching", "metadata", "ranking", "static_validation", "input_validation"
        }
        reason = "actor_upgrade_inspection_running" if pending else "actor_upgrade_revision_unavailable"
        for row in active_rows:
            if str(row["lifecycle"]) != "legacy_builtin" or str(row["actor_id"]) in seen_actors:
                continue
            candidate_id = str(row["candidate_id"] or "")
            if not candidate_id:
                continue
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "actor_public_name": _actor_public_name(row["display_name"], row["publisher"], row["actor_id"]),
                    "publisher": str(row["publisher"]),
                    "pricing": _safe_json(row["pricing_json"], {}),
                    "store_quality": actor_store_quality(None),
                    "max_validation_charge_usd": min(
                        VALIDATION_MAX_CHARGE_USD_DEFAULT, float(route["per_run_cap_usd"])
                    ),
                    "validation_options": None,
                    "last_failure": None,
                    "requires_profile_change": False,
                    "existing_actor_upgrade": True,
                    "selectable": False,
                    "unavailable_reason": reason,
                }
            )

    def _candidate_response(
        self,
        *,
        route_id: str,
        route: Any,
        goal: str,
        target_slot: str | None,
        latest: Any,
        required_count: int,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        candidates.sort(
            key=lambda item: (
                0 if bool(item.get("selectable")) else 1,
                *quality_sort_key(
                    str(item["candidate_id"]), item.get("store_quality"),
                    preferred=bool(item.get("existing_actor_upgrade")),
                )[:-1],
                "" if bool(item.get("existing_actor_upgrade")) else str(item["candidate_id"]),
            )
        )
        blockers = []
        if sum(bool(item["selectable"]) for item in candidates) < required_count:
            blockers.append("candidate_shortfall")
        return {
            "schema_version": 1,
            "route_id": route_id,
            "generation": int(route["generation"]),
            "goal": goal,
            "target_slot": target_slot,
            "run_id": str(latest["run_id"]),
            "required_selection_count": required_count,
            "candidates": candidates,
            "blockers": blockers,
        }
