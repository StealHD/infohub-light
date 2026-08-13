"""X compatibility-candidate projections for fixed pool operations."""

from __future__ import annotations

from typing import Any

from .apify_actor_pool_management import _ensure_ops_symbols


_RELAXED_REQUIREMENTS = (
    "actor_count",
    "publisher_diversity",
    "pre_canary_store_schema",
    "pre_canary_exact_build",
    "pre_canary_manifest",
)
_RETAINED_REQUIREMENTS = (
    "public_runnable_actor",
    "controlled_input",
    "identity_and_publication_fence",
    "nonempty_reference_output",
    "per_run_price_cap",
    "explicit_paid_confirmation",
)
_TERMINAL_COMPATIBILITY_FAILURES = (
    "apify_actor_target_identity_mismatch",
    "apify_actor_contract_mismatch",
    "compatibility_nonempty_required",
    "actor_disabled",
    "actor_not_runnable",
    "apify_actor_start_rejected",
    "apify_actor_revision_unavailable",
)


def _ensure_module_symbols() -> None:
    ops = _ensure_ops_symbols()
    globals().update(vars(ops))


class ApifyActorPoolCompatibilityProjectionMixin:
    """Project only candidates justified by the reviewed discovery run."""

    def _compatibility_candidate_rows(
        self, connection: Any, *, route: Any, run_id: str
    ) -> list[Any]:
        return connection.execute(
            """
            SELECT candidate.id AS candidate_id, candidate.display_name,
                   candidate.state AS candidate_state,
                   candidate.last_error_code, candidate.position,
                   revision.revision_id, revision.actor_id, revision.publisher,
                   revision.build_id, revision.build_number,
                   revision.manifest_hash, revision.manifest_json,
                   revision.input_schema_hash, revision.output_schema_hash,
                   revision.pricing_json, revision.permission_level,
                   revision.security_evidence_json, revision.lifecycle,
                   revision.execution_mode, revision.observed_manifest,
                   EXISTS (
                       SELECT 1 FROM apify_actor_validations AS proof
                       WHERE proof.workspace_id = revision.workspace_id
                         AND proof.route_id = ?
                         AND proof.revision_id = revision.revision_id
                         AND proof.kind = 'route_reference'
                         AND proof.status = 'succeeded'
                         AND proof.cost_final = 1
                         AND proof.semantic_outcome = 'valid_nonempty'
                   ) AS already_validated,
                   EXISTS (
                       SELECT 1 FROM apify_actor_validations AS active
                       WHERE active.workspace_id = revision.workspace_id
                         AND active.revision_id = revision.revision_id
                         AND active.status IN ('queued', 'running')
                   ) AS validation_in_flight,
                   (
                       SELECT failed.semantic_outcome
                       FROM apify_actor_validations AS failed
                       WHERE failed.workspace_id = revision.workspace_id
                         AND failed.route_id = ?
                         AND failed.revision_id = revision.revision_id
                         AND failed.kind = 'route_reference'
                         AND failed.status = 'failed'
                         AND failed.cost_final = 1
                         AND failed.semantic_outcome IN (
                             'apify_actor_target_identity_mismatch',
                             'apify_actor_contract_mismatch',
                             'compatibility_nonempty_required',
                             'actor_disabled', 'actor_not_runnable',
                             'apify_actor_start_rejected',
                             'apify_actor_revision_unavailable'
                         )
                       ORDER BY failed.completed_at DESC, failed.created_at DESC,
                                failed.validation_id DESC
                       LIMIT 1
                   ) AS terminal_failure_code
            FROM apify_actor_discovery_run_revisions AS association
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = association.workspace_id
             AND revision.revision_id = association.revision_id
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE association.workspace_id = ? AND association.run_id = ?
              AND candidate.route_key = ?
            ORDER BY candidate.position, revision.created_at DESC,
                     revision.revision_id DESC
            """,
            (
                str(route["route_id"]),
                str(route["route_id"]),
                self.workspace_id,
                run_id,
                str(route["route_key"]),
            ),
        ).fetchall()

    def _compatibility_source_rows(
        self, connection: Any, *, route: Any, latest: Any
    ) -> list[Any]:
        current_run_id = str(latest["run_id"])
        rows = self._compatibility_candidate_rows(
            connection, route=route, run_id=current_run_id
        )
        if rows:
            return rows
        prior = connection.execute(
            """
            SELECT association.run_id
            FROM apify_actor_discovery_run_revisions AS association
            JOIN apify_actor_discovery_runs AS run
              ON run.workspace_id = association.workspace_id
             AND run.run_id = association.run_id
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = association.workspace_id
             AND revision.revision_id = association.revision_id
            WHERE association.workspace_id = ? AND run.route_id = ?
              AND association.run_id <> ?
              AND json_extract(revision.security_evidence_json,
                               '$.compatibility_trial_only') = 1
            ORDER BY run.created_at DESC, run.rowid DESC LIMIT 1
            """,
            (self.workspace_id, str(route["route_id"]), current_run_id),
        ).fetchone()
        return (
            self._compatibility_candidate_rows(
                connection, route=route, run_id=str(prior["run_id"])
            )
            if prior is not None
            else []
        )

    def _compatibility_trial_item(self, row: Any, *, route: Any) -> dict[str, Any]:
        _ensure_module_symbols()
        pricing = _safe_json(row["pricing_json"], {})
        security = _safe_json(row["security_evidence_json"], {})
        warnings: list[str] = []
        if str(row["lifecycle"]) == "legacy_builtin" or not row["manifest_hash"]:
            warnings.append("observed_manifest_after_canary")
        if not row["build_id"] or not row["build_number"]:
            warnings.append("follows_current_build_if_unpinnable")
        if bool(security.get("deprecated")):
            warnings.append("deprecated_actor")
        if str(row["candidate_state"]) == "open":
            warnings.append("previous_runtime_failure")
        unavailable = self._compatibility_unavailable_reason(
            row, pricing=pricing, security=security, route=route
        )
        candidate_id = str(row["candidate_id"])
        profile_hash = validation_profile_hash(
            timeout_seconds=VALIDATION_TIMEOUT_SECONDS_DEFAULT,
            sample_items=1,
            max_charge_usd=float(route["per_run_cap_usd"]),
        )
        return {
            "candidate_id": candidate_id,
            "revision_id": str(row["revision_id"]),
            "actor_public_name": _actor_public_name(
                row["display_name"], row["publisher"], row["actor_id"]
            ),
            "publisher": str(row["publisher"]),
            "pricing": pricing,
            "max_validation_charge_usd": round(
                min(VALIDATION_MAX_CHARGE_USD_DEFAULT, float(route["per_run_cap_usd"])), 6
            ),
            "execution_mode": str(row["execution_mode"]),
            "already_validated": bool(row["already_validated"]),
            "compatibility_warnings": warnings,
            "relaxed_requirements": list(_RELAXED_REQUIREMENTS),
            "validation_options": self._compatibility_validation_options(
                row, route=route, candidate_id=candidate_id, profile_hash=profile_hash
            ),
            "evaluation_history": None,
            "selectable": unavailable is None,
            "unavailable_reason": unavailable,
        }

    def _compatibility_unavailable_reason(
        self, row: Any, *, pricing: dict[str, Any], security: dict[str, Any], route: Any
    ) -> str | None:
        if row["terminal_failure_code"]:
            return str(row["terminal_failure_code"])
        compatibility_trial = bool(security.get("compatibility_trial_only"))
        if (
            str(row["candidate_state"]) == "disabled"
            and not compatibility_trial
            and not (
                str(row["lifecycle"]) == "static_valid"
                and not row["last_error_code"]
            )
        ):
            return str(row["last_error_code"] or "actor_disabled")
        if str(row["permission_level"] or "").casefold() in {
            "full", "full_access", "administrator"
        } or bool(security.get("requires_full_permissions")):
            return "actor_requires_full_permissions"
        if _pricing_exceeds_usd_cap(pricing, float(route["per_run_cap_usd"])):
            return "actor_price_above_route_cap"
        return "candidate_validation_in_progress" if bool(row["validation_in_flight"]) else None

    def _compatibility_validation_options(
        self, row: Any, *, route: Any, candidate_id: str, profile_hash: str
    ) -> dict[str, Any]:
        _ensure_module_symbols()
        return {
            "timeout_seconds": VALIDATION_TIMEOUT_SECONDS_DEFAULT,
            "timeout_min_seconds": VALIDATION_TIMEOUT_SECONDS_MIN,
            "timeout_max_seconds": VALIDATION_TIMEOUT_SECONDS_MAX,
            "allowed_sample_items": [1],
            "sample_items": 1,
            "max_charge_usd": round(float(route["per_run_cap_usd"]), 6),
            "max_charge_limit_usd": 0.02,
            "supports_sample_items": True,
            "profile_hash": profile_hash,
            "options_hash": _validation_options_hash(
                route_id=str(route["route_id"]), generation=int(route["generation"]),
                candidate_id=candidate_id, revision_id=str(row["revision_id"]),
                build_id=str(row["build_id"] or ""),
                build_number=str(row["build_number"] or ""),
                manifest_hash=str(row["manifest_hash"] or ""),
                supports_sample_items=True,
            ),
        }

    def _compatibility_current_rejections(
        self, connection: Any, *, route: Any, latest: Any, seen: set[str]
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT candidate.id AS candidate_id, candidate.actor_id,
                   candidate.display_name, evaluation.reason_code,
                   evaluation.attempt_count, evaluation.first_seen_at,
                   evaluation.last_seen_at, evaluation.retry_requested_at
            FROM apify_actor_evaluation_history AS evaluation
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = evaluation.workspace_id
             AND candidate.id = evaluation.candidate_id
            JOIN apify_actor_discovery_runs AS run
              ON run.workspace_id = evaluation.workspace_id
            WHERE evaluation.workspace_id = ? AND run.run_id = ?
              AND evaluation.route_id = run.route_id
              AND evaluation.policy_mode = 'compatibility'
              AND evaluation.outcome = 'failed'
              AND evaluation.deterministic = 1
              AND evaluation.stage = 'metadata'
              AND evaluation.last_seen_at >= run.created_at
              AND evaluation.last_seen_at <= run.updated_at
            ORDER BY evaluation.last_seen_at DESC, evaluation.evaluation_id DESC
            """,
            (self.workspace_id, str(latest["run_id"])),
        ).fetchall()
        return [
            self._compatibility_rejection_item(row, route=route)
            for row in rows
            if str(row["candidate_id"]) not in seen and not seen.add(str(row["candidate_id"]))
        ]

    def _compatibility_rejection_item(self, row: Any, *, route: Any) -> dict[str, Any]:
        _ensure_module_symbols()
        actor_id = str(row["actor_id"])
        publisher = actor_id.split("/", 1)[0] if "/" in actor_id else "unknown"
        reason = str(row["reason_code"])
        return {
            "candidate_id": str(row["candidate_id"]),
            "actor_public_name": _actor_public_name(row["display_name"], publisher, actor_id),
            "publisher": publisher,
            "pricing": {},
            "max_validation_charge_usd": round(
                min(VALIDATION_MAX_CHARGE_USD_DEFAULT, float(route["per_run_cap_usd"])), 6
            ),
            "execution_mode": "current",
            "already_validated": False,
            "compatibility_warnings": [],
            "relaxed_requirements": list(_RELAXED_REQUIREMENTS),
            "validation_options": None,
            "evaluation_history": {
                "reason_code": reason,
                "deterministic": True,
                "attempt_count": int(row["attempt_count"]),
                "first_seen_at": str(row["first_seen_at"]),
                "last_seen_at": str(row["last_seen_at"]),
                "retry_requested_at": row["retry_requested_at"],
            },
            "selectable": False,
            "unavailable_reason": (
                "actor_requires_full_permissions"
                if reason == "actor_full_permission" else reason
            ),
        }

    def _project_compatibility_candidates(
        self, connection: Any, route: Any
    ) -> dict[str, Any]:
        _ensure_module_symbols()
        latest = self._candidate_latest_run(connection, str(route["route_id"]))
        if latest is None:
            return self._compatibility_empty_response(route)
        seen: set[str] = set()
        candidates = []
        for row in self._compatibility_source_rows(connection, route=route, latest=latest):
            candidate_id = str(row["candidate_id"])
            if candidate_id not in seen:
                seen.add(candidate_id)
                candidates.append(self._compatibility_trial_item(row, route=route))
        candidates.extend(
            self._compatibility_current_rejections(
                connection, route=route, latest=latest, seen=seen
            )
        )
        return self._compatibility_response(route, latest=latest, candidates=candidates)

    def _compatibility_empty_response(self, route: Any) -> dict[str, Any]:
        return self._compatibility_response(
            route, latest=None, candidates=[], blockers=["candidate_refresh_required"]
        )

    def _compatibility_response(
        self, route: Any, *, latest: Any | None, candidates: list[dict[str, Any]],
        blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "route_id": str(route["route_id"]),
            "generation": int(route["generation"]),
            "goal": "compatibility_single",
            "run_id": str(latest["run_id"]) if latest is not None else None,
            "required_selection_count": 1,
            "relaxed_requirements": list(_RELAXED_REQUIREMENTS),
            "retained_requirements": list(_RETAINED_REQUIREMENTS),
            "candidates": candidates,
            "blockers": blockers if blockers is not None else (
                [] if any(bool(item["selectable"]) for item in candidates)
                else ["candidate_shortfall"]
            ),
        }
