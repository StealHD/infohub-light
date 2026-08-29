"""Read-only, v2-only projections for the ActorOps administration surface."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .binding_service import ActorOpsBindingError, ActorOpsBindingService
from .domain import AssignmentRole, CandidateRecord, RouteHealth
from .discovery_mapping_issues import candidate_mapping_issue
from .compatibility_projection import candidate_compatibility
from .presentation_mapping import CandidatePresentationMappings
from .readiness import require_actorops_v2_schema
from .repository import ActorOpsNotFound, ActorOpsRepository
from .runtime_candidate_health import (
    CandidateOperationalState,
    candidate_operational_states,
    operational_route_summary,
)
from .workflow_projection import (
    replacement_workflow_additions,
    route_workflow_summary,
)


class ActorOpsAdminMigrationRequired(RuntimeError):
    """The installed database cannot safely serve the v2 admin contract."""


class ActorOpsAdminUnavailable(RuntimeError):
    """The v2 admin surface cannot read its own current facts."""


class ActorOpsAdminService:
    """Own all public Admin reads without consulting legacy ActorOps tables."""

    def __init__(self, store: Any, *, workspace_id: str) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)

    def list_routes(self) -> list[dict[str, object]]:
        repository = self.repository()
        rows = repository.connection.execute(
            """SELECT route_id FROM actor_routes_v2 WHERE workspace_id=?
               ORDER BY platform, target_type, capability, route_id""",
            (self.workspace_id,),
        ).fetchall()
        return [self._route_summary(repository, str(row["route_id"])) for row in rows]

    def route_detail(self, route_id: str) -> dict[str, object]:
        repository = self.repository()
        result = self._route_summary(repository, route_id)
        candidates = repository.list_route_candidates(route_id)
        binding_service = ActorOpsBindingService(
            self.store, workspace_id=self.workspace_id
        )
        bindings = repository.list_route_bindings(route_id)
        metadata = repository.operator.list_metadata(route_id)
        states = candidate_operational_states(repository, candidates)
        result.update(
            {
                "candidates": [
                    self._candidate(
                        repository,
                        item,
                        metadata.get(item.candidate_id),
                        states.get(item.candidate_id),
                    )
                    for item in candidates
                ],
                "bindings": [
                    self._binding(binding_service, item) for item in bindings
                ],
                "attempts": self._attempts(repository, route_id),
                "discoveries": self._discoveries(repository, route_id),
                "replacements": self._replacements(repository, route_id, metadata),
                "repairs": repository.resilience.route_repairs(route_id),
                "freshness_summary": self._freshness_summary(repository, route_id),
            }
        )
        return result

    def route_summary(self, route_id: str) -> dict[str, object]:
        return self._route_summary(self.repository(), route_id)

    def workspace_maintenance_policy(self) -> dict[str, object]:
        repository = self.repository()
        return self._workspace_policy(repository)

    def route_maintenance_policy(self, route_id: str) -> dict[str, object]:
        repository = self.repository()
        return self._route_policy(repository, route_id)

    def execution_events(
        self, **filters: object,
    ) -> tuple[list[dict[str, object]], str | None, str]:
        return self.repository().resilience.execution_events(**filters)

    def repository(self) -> ActorOpsRepository:
        try:
            require_actorops_v2_schema(self.store)
            return ActorOpsRepository(self.store.connect(), self.workspace_id)
        except sqlite3.Error as error:
            raise ActorOpsAdminUnavailable("actorops_v2_store_unavailable") from error
        except RuntimeError as error:
            if "migration_required" in str(error):
                raise ActorOpsAdminMigrationRequired("actorops_v2_migration_required") from error
            raise ActorOpsAdminUnavailable("actorops_v2_store_unavailable") from error

    def _route_summary(
        self, repository: ActorOpsRepository, route_id: str
    ) -> dict[str, object]:
        route = repository.get_route(route_id)
        candidates = repository.list_route_candidates(route_id)
        metadata = repository.operator.list_metadata(route_id)
        bindings = repository.list_route_bindings(route_id)
        active = next(
            (item for item in candidates if item.assignment_role is AssignmentRole.ACTIVE),
            None,
        )
        standby = [
            item for item in candidates if item.assignment_role is AssignmentRole.STANDBY
        ]
        lkg_ids = {
            str(item.last_known_good_candidate_id)
            for item in bindings
            if item.last_known_good_candidate_id
        }
        lkg = next((item for item in candidates if item.candidate_id in lkg_ids), None)
        states = candidate_operational_states(repository, candidates)
        operational = operational_route_summary(
            repository, candidates, route_id=route_id
        )
        health = operational.health
        row = repository.connection.execute(
            """SELECT updated_at FROM actor_routes_v2
               WHERE workspace_id=? AND route_id=?""",
            (self.workspace_id, route_id),
        ).fetchone()
        workflow = route_workflow_summary(
            self._discoveries(repository, route_id),
            self._replacements(repository, route_id, metadata),
        )
        return {
            "route_id": route.route_id,
            "route_key": str(route.route_key),
            "platform": route.route_key.platform,
            "target_type": route.route_key.target_type,
            "capability": route.route_key.capability,
            "runtime_mode": route.runtime_mode.value,
            "generation": route.generation,
            "per_run_cap_usd": route.per_run_cap_usd,
            **operational.public(),
            "active_candidate": self._candidate(
                repository,
                active,
                metadata.get(active.candidate_id) if active else None,
                states.get(active.candidate_id) if active else None,
            ),
            "standby_candidates": [
                self._candidate(
                    repository,
                    item,
                    metadata.get(item.candidate_id),
                    states.get(item.candidate_id),
                )
                for item in standby
            ],
            "last_known_good": self._candidate(
                repository,
                lkg,
                metadata.get(lkg.candidate_id) if lkg else None,
                states.get(lkg.candidate_id) if lkg else None,
            ),
            "binding_summary": self._binding_summary(bindings),
            "maintenance_policy": self._route_policy(repository, route_id),
            "workflow": workflow,
            "degraded_reason": self._degraded_reason(
                route.runtime_mode.value, health, bindings
            ),
            "updated_at": str(row["updated_at"]) if row is not None else None,
        }

    def _workspace_policy(self, repository: ActorOpsRepository) -> dict[str, object]:
        policy = repository.maintenance.get_policy(None)
        return {
            "enabled": bool(policy.enabled),
            "monthly_budget_usd": policy.monthly_budget_usd,
            "authorization_origin": self._authorization_origin(policy),
            "generation": policy.generation,
        }

    def _route_policy(
        self, repository: ActorOpsRepository, route_id: str
    ) -> dict[str, object]:
        effective = repository.maintenance.effective_policy(route_id)
        budget = repository.maintenance.probe_budget(route_id, datetime.now(timezone.utc))
        return {
            "authorized": bool(effective.authorized),
            "workspace": self._workspace_policy(repository),
            "route": {
                "enabled": bool(effective.route.enabled),
                "max_probe_usd": effective.route.max_probe_usd,
                "max_probes_per_utc_day": effective.route.max_probes_per_utc_day,
                "auto_add_standby": effective.route.auto_add_standby,
                "auto_replace_non_last": effective.route.auto_replace_non_last,
                "authorization_origin": self._authorization_origin(
                    effective.route
                ),
                "generation": effective.route.generation,
            },
            "budget": {
                "spent_usd": round(float(budget.spent_usd), 6),
                "reserved_usd": round(float(budget.reserved_usd), 6),
                "probe_count": int(budget.probe_count),
            },
        }

    def _candidate(
        self,
        repository: ActorOpsRepository,
        candidate: CandidateRecord | None,
        metadata: Any | None,
        state: CandidateOperationalState | None = None,
    ) -> dict[str, object] | None:
        if candidate is None:
            return None
        state = state or candidate_operational_states(repository, (candidate,))[
            candidate.candidate_id
        ]
        proofs = int(
            repository.connection.execute(
                """SELECT COUNT(DISTINCT target_fingerprint) FROM actor_attempts_v2
                   WHERE workspace_id=? AND candidate_id=? AND kind='probe'
                     AND status='succeeded' AND semantic_outcome='valid_nonempty'
                     AND cost_final=1""",
                (self.workspace_id, candidate.candidate_id),
            ).fetchone()[0]
        )
        required = len(repository.operator.binding_set(candidate.route_id))
        return {
            "candidate_id": candidate.candidate_id,
            "build_number": candidate.build_number,
            "lifecycle": candidate.lifecycle.value,
            "assignment": candidate.assignment_role.value,
            "priority": candidate.priority,
            "generation": candidate.generation,
            "mapping_issue_code": candidate_mapping_issue(candidate),
            **candidate_compatibility(repository, candidate),
            **state.public(),
            "avatar_mapping_status": CandidatePresentationMappings(
                repository
            ).status(candidate),
            "store_metadata": self._metadata(metadata),
            "evidence_progress": {
                "verified_bindings": min(proofs, required),
                "required_bindings": required,
            },
        }

    @staticmethod
    def _metadata(value: Any | None) -> dict[str, object] | None:
        if value is None:
            return None
        try:
            pricing = json.loads(value.pricing_json)
        except (TypeError, ValueError):
            pricing = []
        return {
            "actor_slug": value.actor_slug,
            "display_name": value.display_name,
            "short_description": value.short_description,
            "developer_name": value.developer_name,
            "maintained_by_apify": value.maintained_by_apify,
            "rating": value.rating,
            "review_count": value.review_count,
            "bookmark_count": value.bookmark_count,
            "total_users": value.total_users,
            "monthly_active_users": value.monthly_active_users,
            "pricing": pricing if isinstance(pricing, list) else [],
            "last_modified_at": value.last_modified_at,
            "observed_at": value.observed_at,
            "generation": value.generation,
        }

    @staticmethod
    def _authorization_origin(policy: Any) -> str:
        value = str(getattr(policy, "authorization_origin", "none"))
        return value if value in {"system_default", "operator", "none"} else "none"

    def _binding(
        self, service: ActorOpsBindingService, item: Any
    ) -> dict[str, object]:
        source = self.store.get_source(item.source_id) or {}
        verification: dict[str, object]
        if item.status == "ready":
            verification = {"state": "ready", "proof_kind": None, "reason": None}
        elif item.status == "disabled":
            verification = {"state": "disabled", "proof_kind": None, "reason": None}
        else:
            try:
                evidence = service.assess(item.source_id)
                verification = {
                    "state": "eligible" if evidence.eligible else "blocked",
                    "proof_kind": evidence.proof_kind,
                    "reason": evidence.reason,
                }
            except ActorOpsBindingError as error:
                verification = {
                    "state": "blocked",
                    "proof_kind": None,
                    "reason": error.code,
                }
        return {
            "binding_id": item.binding_id,
            "source_id": item.source_id,
            "source_name": source.get("display_name") or "来源已删除",
            "source_enabled": bool(source.get("enabled")),
            "enabled_subscription_count": self.store.source_subscription_usage(
                item.source_id
            )["enabled_subscriber_count"],
            "status": item.status,
            "binding_version": item.binding_version,
            "preferred_candidate_id": item.preferred_candidate_id,
            "last_known_good_candidate_id": item.last_known_good_candidate_id,
            "last_success_at": item.last_success_at,
            "verification": verification,
        }

    @staticmethod
    def _binding_summary(bindings: tuple[Any, ...]) -> dict[str, int]:
        return {
            "ready_count": sum(item.status == "ready" for item in bindings),
            "pending_count": sum(item.status == "pending" for item in bindings),
            "disabled_count": sum(item.status == "disabled" for item in bindings),
        }

    def _freshness_summary(
        self, repository: ActorOpsRepository, route_id: str,
    ) -> dict[str, int]:
        rows = repository.connection.execute(
            """SELECT state, COUNT(*) AS count FROM actor_source_candidate_freshness_v2
                 WHERE workspace_id=? AND source_id IN (
                    SELECT source_id FROM actor_source_bindings_v2
                    WHERE workspace_id=? AND route_id=?
                 ) GROUP BY state""",
            (self.workspace_id, self.workspace_id, route_id),
        ).fetchall()
        values = {str(row["state"]): int(row["count"]) for row in rows}
        return {
            "neutral": values.get("neutral", 0),
            "suspected_stale": values.get("suspected_stale", 0),
            "source_stale": values.get("source_stale", 0),
            "confirmed_no_change": values.get("confirmed_no_change", 0),
        }

    def _attempts(
        self, repository: ActorOpsRepository, route_id: str
    ) -> list[dict[str, object]]:
        rows = repository.connection.execute(
            """SELECT attempt_id, source_id, candidate_id, kind, status, result_state,
                      semantic_outcome, failure_class, error_code, reserved_usd,
                      actual_cost_usd, cost_final, created_at, terminal_at, updated_at
               FROM actor_attempts_v2 WHERE workspace_id=? AND route_id=?
               ORDER BY updated_at DESC, attempt_id DESC LIMIT 50""",
            (self.workspace_id, route_id),
        ).fetchall()
        return [
            {
                "attempt_id": str(row["attempt_id"]),
                "source_id": row["source_id"],
                "candidate_id": str(row["candidate_id"]),
                "kind": str(row["kind"]),
                "status": str(row["status"]),
                "result_state": str(row["result_state"]),
                "semantic_outcome": row["semantic_outcome"],
                "failure_class": row["failure_class"],
                "error_code": row["error_code"],
                "reserved_usd": float(row["reserved_usd"]),
                "actual_cost_usd": row["actual_cost_usd"],
                "cost_final": bool(row["cost_final"]),
                "created_at": str(row["created_at"]),
                "terminal_at": row["terminal_at"],
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def _discoveries(
        self, repository: ActorOpsRepository, route_id: str
    ) -> list[dict[str, object]]:
        rows = repository.connection.execute(
            """SELECT discovery_id, trigger_reason, status, stage, stage_attempt,
                      query_count, candidate_count, rejection_count, failure_class,
                      error_code, generation, search_cursor, created_at,
                      terminal_at, updated_at
               FROM actor_discovery_jobs_v2 WHERE workspace_id=? AND route_id=?
               ORDER BY updated_at DESC, discovery_id DESC LIMIT 20""",
            (self.workspace_id, route_id),
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            cursor = row["search_cursor"]
            try:
                state = json.loads(str(cursor or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                state = {}
            raw_metrics = state.get("metrics") if isinstance(state, dict) else {}
            raw_metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
            result.append({
                key: (
                    str(row[key])
                    if key in {
                        "discovery_id", "trigger_reason", "status", "stage",
                        "created_at", "updated_at",
                    }
                    else row[key]
                )
                for key in row.keys()
                if key not in {"failure_class", "search_cursor"}
            } | {
                "failure_class": row["failure_class"],
                "terminal_at": row["terminal_at"],
                "metrics": {
                    key: max(0, int(raw_metrics.get(key, 0)))
                    for key in {
                        "marketplace_hits", "revision_checks", "wrong_actor_type",
                        "preflight_blocked", "route_relevant", "static_ready",
                        "sample_required", "system_usable",
                    }
                },
            })
        return result

    def _replacements(
        self, repository: ActorOpsRepository, route_id: str, metadata: dict[str, Any]
    ) -> list[dict[str, object]]:
        rows = repository.connection.execute(
            """SELECT * FROM actor_replacement_plans_v2 WHERE workspace_id=? AND route_id=?
               ORDER BY updated_at DESC, plan_id DESC LIMIT 20""",
            (self.workspace_id, route_id),
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            candidate = repository.get_candidate(str(row["proposed_candidate_id"]))
            result.append(
                {
                    "plan_id": str(row["plan_id"]),
                    "target_assignment": str(row["target_assignment"]),
                    "target_priority": int(row["target_priority"]),
                    "status": str(row["status"]),
                    "generation": int(row["generation"]),
                    "per_probe_cap_usd": float(row["per_probe_cap_usd"]),
                    "total_cap_usd": float(row["total_cap_usd"]),
                    "binding_count": int(row["binding_count"]),
                    "error_code": row["error_code"],
                    **replacement_workflow_additions(
                        repository,
                        str(row["plan_id"]),
                        binding_count=int(row["binding_count"]),
                        status=str(row["status"]),
                    ),
                    "candidate": self._candidate(
                        repository, candidate, metadata.get(candidate.candidate_id)
                    ),
                }
            )
        return result

    @staticmethod
    def _degraded_reason(mode: str, health: RouteHealth, bindings: tuple[Any, ...]) -> str | None:
        if mode == "disabled":
            return "actorops_v2_route_disabled"
        if any(item.status != "ready" for item in bindings):
            return "actorops_v2_binding_not_ready"
        if health is RouteHealth.UNAVAILABLE:
            return "actorops_v2_no_runnable_candidate"
        if health is RouteHealth.DEGRADED:
            return "actorops_v2_single_runnable_candidate"
        return None


__all__ = [
    "ActorOpsAdminMigrationRequired",
    "ActorOpsAdminService",
    "ActorOpsAdminUnavailable",
]
