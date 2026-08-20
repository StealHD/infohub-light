"""Controlled X compatibility plans for one fixed Actor-pool slot."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Callable, Iterable
from typing import Any, Mapping

from .apify_actor_pool_management import _ensure_ops_symbols
from .apify_actor_candidate_quality import (
    actor_store_quality,
    quality_sort_key,
    store_quality_evidence,
)


def persist_compatibility_candidates(
    *,
    ops: Any,
    route_id: str,
    discovery_run_id: str,
    candidates: Iterable[Any],
    candidate_limit: int,
    preferred_actor_ids: set[str],
    store_search_actor_ids: set[str],
    pricing_summary: Callable[[Any], Mapping[str, Any]],
    schema_hash: Callable[[Mapping[str, Any]], str],
    input_dialect: Callable[[Any], str | None],
    input_count_field: Callable[[Any], str | None],
) -> None:
    """Persist bounded X compatibility candidates with Store runnable proof."""

    for candidate in sorted(
        candidates,
        key=lambda item: quality_sort_key(
            item.actor_id, actor_store_quality(item.actor),
            preferred=item.actor_id in preferred_actor_ids,
        ),
    )[:candidate_limit]:
        ops.ensure_compatibility_trial_revision(
            route_id=route_id, discovery_run_id=discovery_run_id,
            actor_id=candidate.actor_id, publisher=candidate.publisher,
            build_id=candidate.build_id, build_number=candidate.build_number,
            pricing=pricing_summary(candidate.pricing),
            permission_level=str(
                candidate.actor.get("actorPermissionLevel") or "limited"
            ),
            input_schema_hash=schema_hash(candidate.input_schema),
            output_schema_hash=schema_hash(candidate.output_schema),
            deprecated=candidate.actor.get("isDeprecated") is True,
            permission_unverified=(
                str(candidate.actor.get("actorPermissionLevel") or "").casefold()
                not in {"limited_permissions", "limited"}
            ),
            input_dialect=input_dialect(candidate.input_schema),
            input_count_field=input_count_field(candidate.input_schema),
            store_runnable_provenance=(candidate.actor_id in store_search_actor_ids),
            compatibility_preflight_version=2,
            free_input_validated=True,
            output_schema_proves_items=True,
            x_profile_semantics_proven=True,
            store_quality=actor_store_quality(candidate.actor),
        )


class ApifyActorPoolCompatibilityMixin:
    """Keep X's controlled compatibility path separate from normal Canaries."""

    def ensure_compatibility_trial_revision(
        self,
        *,
        route_id: str,
        discovery_run_id: str,
        actor_id: str,
        publisher: str,
        build_id: str | None,
        build_number: str | None,
        pricing: Mapping[str, Any] | None,
        permission_level: str,
        input_schema_hash: str | None,
        output_schema_hash: str | None,
        deprecated: bool = False,
        permission_unverified: bool = False,
        input_dialect: str = "controlled_default",
        input_count_field: str | None = None,
        store_runnable_provenance: bool = False,
        compatibility_preflight_version: int = 0,
        free_input_validated: bool = False,
        output_schema_proves_items: bool = False,
        x_profile_semantics_proven: bool = False,
        store_quality: Mapping[str, Any] | None = None,
    ) -> str:
        """Persist a controlled X trial and its exact Store runnable evidence."""

        ops = _ensure_ops_symbols()
        normalized_actor = ops._normalize_actor_id(actor_id)
        candidate_id = self.ensure_candidate(
            route_id, actor_id=normalized_actor, display_name=normalized_actor
        )
        evidence_key = ops.actor_evidence_fingerprint(
            route_id=route_id,
            candidate_id=candidate_id,
            actor_id=normalized_actor,
            build_id=str(build_id or ""),
            build_number=str(build_number or ""),
            manifest_hash=str(output_schema_hash or ""),
            pricing=pricing,
            input_schema_hash=str(input_schema_hash or ""),
            output_schema_hash=str(output_schema_hash or ""),
        )
        revision_id = f"apify-revision-{evidence_key[:32]}"
        now = self._now_iso()
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            if str(route["platform"]) != "x":
                raise ops.ActorOpsError(
                    "compatibility_route_unsupported",
                    "Compatibility trial metadata is supported only for X",
                    status_code=412,
                )
            run = connection.execute(
                """SELECT 1 FROM apify_actor_discovery_runs
                   WHERE workspace_id = ? AND run_id = ? AND route_id = ?""",
                (self.workspace_id, discovery_run_id, route_id),
            ).fetchone()
            if run is None:
                raise ops.ActorOpsError(
                    "apify_actor_discovery_revision_mismatch",
                    "Compatibility trial does not belong to this discovery run",
                    status_code=422,
                )
            security = self._compatibility_trial_security(
                ops,
                build_id=build_id,
                build_number=build_number,
                deprecated=deprecated,
                permission_unverified=permission_unverified,
                input_dialect=input_dialect,
                input_count_field=input_count_field,
                store_runnable_provenance=store_runnable_provenance,
                compatibility_preflight_version=compatibility_preflight_version,
                free_input_validated=free_input_validated,
                output_schema_proves_items=output_schema_proves_items,
                x_profile_semantics_proven=x_profile_semantics_proven,
                store_quality=store_quality,
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO apify_actor_adapter_revisions (
                    revision_id, workspace_id, candidate_id, actor_id,
                    publisher, build_id, build_number, manifest_json,
                    manifest_hash, input_schema_hash, output_schema_hash,
                    execution_mode, observed_manifest, pricing_json,
                    permission_level, security_evidence_json, lifecycle,
                    ai_provider, ai_model, prompt_version, discovery_run_id,
                    canary_passed_at, created_at, superseded_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, 0, ?, ?, ?,
                    'legacy_builtin', NULL, NULL, 'compatibility_trial_v1', ?,
                    NULL, ?, NULL
                )
                """,
                (
                    revision_id, self.workspace_id, candidate_id, normalized_actor,
                    ops._safe_label(publisher, 128), ops._optional_label(build_id, 256),
                    ops._optional_label(build_number, 256), input_schema_hash,
                    output_schema_hash,
                    "pinned" if build_id and build_number else "current",
                    ops._bounded_safe_json(pricing or {}, max_bytes=8 * 1024),
                    ops._safe_label(permission_level, 64), security,
                    discovery_run_id, now,
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO apify_actor_discovery_run_revisions (
                       workspace_id, run_id, revision_id, created_at
                   ) VALUES (?, ?, ?, ?)""",
                (self.workspace_id, discovery_run_id, revision_id, now),
            )
        return revision_id

    @staticmethod
    def _compatibility_trial_security(
        ops: Any,
        *,
        build_id: str | None,
        build_number: str | None,
        deprecated: bool,
        permission_unverified: bool,
        input_dialect: str,
        input_count_field: str | None,
        store_runnable_provenance: bool,
        compatibility_preflight_version: int,
        free_input_validated: bool,
        output_schema_proves_items: bool,
        x_profile_semantics_proven: bool,
        store_quality: Mapping[str, Any] | None,
    ) -> str:
        return ops._bounded_safe_json(
            {
                "public": True,
                "compatibility_trial_only": True,
                "controlled_input_required": True,
                "nonempty_reference_required": True,
                "exact_build_proven": bool(build_id and build_number),
                "deprecated": bool(deprecated),
                "permission_unverified": bool(permission_unverified),
                "store_runnable_provenance": bool(store_runnable_provenance),
                "compatibility_preflight_version": (
                    2 if int(compatibility_preflight_version) >= 2 else 0
                ),
                "free_input_validated": bool(free_input_validated),
                "output_schema_proves_items": bool(output_schema_proves_items),
                "x_profile_semantics_proven": bool(x_profile_semantics_proven),
                **store_quality_evidence(store_quality),
                "input_dialect": input_dialect if input_dialect in {
                    "controlled_default", "twitter_handles", "start_urls",
                    "profile_urls", "handle", "username", "twitter_handle",
                    "url", "urls", "direct_urls",
                } else "controlled_default",
                "input_count_field": input_count_field if input_count_field in {
                    "maxItems", "max_items", "maxResults", "max_results",
                    "resultsLimit", "limit", "tweetsDesired",
                } else None,
            },
            max_bytes=16 * 1024,
        )

    def _get_x_compatibility_slot_plan(
        self,
        run: sqlite3.Row,
        *,
        goal: str,
        candidate_ids: tuple[str, ...],
        candidate_validation_profiles: Any,
        max_total_charge_usd: float | None,
        target_slot_count: int | None,
        target_slot: str | None,
    ) -> dict[str, Any]:
        """Freeze one X trial candidate into one unchanged pool slot."""

        automatic = not candidate_ids
        if automatic:
            connection = self.store.connect()
            route = self._require_route(connection, str(run["route_id"]))
            available = self._list_compatibility_candidates(connection, route)
            trial = next(
                (
                    item for item in available["candidates"]
                    if bool(item.get("selectable"))
                    and not bool(item.get("already_validated"))
                    and not bool(item.get("active_in_route"))
                ),
                None,
            )
            if trial is None:
                return self._x_slot_insufficient_plan(
                    run, goal=goal, target_slot=target_slot
                )
            candidate_ids = (str(trial["candidate_id"]),)
        context = self._x_slot_compatibility_context(
            run,
            goal=goal,
            candidate_ids=candidate_ids,
            candidate_validation_profiles=candidate_validation_profiles,
            target_slot_count=target_slot_count,
            target_slot=target_slot,
        )
        sources = self._x_slot_source_budget(context)
        return self._x_slot_plan_response(
            context,
            sources,
            max_total_charge_usd=max_total_charge_usd,
            selection_mode="server" if automatic else "manual",
        )

    def _x_slot_insufficient_plan(
        self,
        run: sqlite3.Row,
        *,
        goal: str,
        target_slot: str | None,
    ) -> dict[str, Any]:
        """Return a stable no-spend response when no trial remains.

        The public picker intentionally hides unverified Actors.  A server
        plan must therefore say "insufficient" instead of asking a user to
        select a rejected or already-active Actor just to discover that later.
        """

        ops = _ensure_ops_symbols()
        connection = self.store.connect()
        route = self._require_route(connection, str(run["route_id"]))
        target_count = self.pool_stage_operation_target_count(
            connection,
            route_id=str(route["route_id"]),
            goal=goal,
            target_slot=target_slot,
            populated_count=sum(
                row["revision_id"] is not None
                for row in connection.execute(
                    """SELECT revision_id FROM apify_route_active_slots
                       WHERE workspace_id = ? AND route_id = ?""",
                    (self.workspace_id, str(route["route_id"])),
                ).fetchall()
            ),
            requested_count=None,
            minimum_healthy=int(route["min_runtime_healthy"]),
        )
        payload = {
            "schema_version": 4,
            "goal": goal,
            "operation_mode": "compatibility_slot",
            "operation_slot": target_slot,
            "selection_mode": "server",
            "target_slot_count": target_count,
            "run_id": str(run["run_id"]),
            "route_id": str(route["route_id"]),
            "generation": int(route["generation"]),
            "items": [],
            "required_success_count": 1,
            "required_source_slots": target_count,
            "max_total_charge_usd": 0.0,
        }
        plan_hash = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return {
            **payload,
            "route_key": str(route["route_key"]),
            "platform": "x",
            "target_type": str(route["target_type"]),
            "capability": str(route["capability"]),
            "mode": str(route["mode"]),
            "status": "insufficient_candidates",
            "ready": False,
            "activation_ready": False,
            "plan_hash": plan_hash,
            "max_candidates": 1,
            "route_validation_cap_usd": 0.0,
            "source_validation_cap_usd": 0.0,
            "source_count": 0,
            "source_validation_count": 0,
            "per_candidate_cap_usd": min(
                float(route["per_run_cap_usd"]), float(ops.VALIDATION_MAX_CHARGE_USD_LIMIT)
            ),
            "successful_actor_count": 0,
            "successful_publisher_count": 0,
            "attempts_used": 0,
            "attempts_remaining": 0,
            "budget_remaining_usd": float(ops.POOL_STAGE_MAX_TOTAL_USD),
            "_eligible_candidate_count": 0,
            "_source_snapshot": [],
            "_reference_fingerprints": {},
        }

    def _x_slot_compatibility_context(
        self,
        run: sqlite3.Row,
        *,
        goal: str,
        candidate_ids: tuple[str, ...],
        candidate_validation_profiles: Any,
        target_slot_count: int | None,
        target_slot: str | None,
    ) -> dict[str, Any]:
        ops = _ensure_ops_symbols()
        if len(candidate_ids) != 1 or len(set(candidate_ids)) != 1:
            raise ops.ActorOpsError(
                "apify_actor_manual_candidate_set_incomplete",
                "A slot operation requires exactly one selected Actor",
                status_code=422,
            )
        connection = self.store.connect()
        route = self._require_route(connection, str(run["route_id"]))
        active_slots = {
            str(row["slot_name"]): str(row["revision_id"] or "")
            for row in connection.execute(
                """SELECT slot_name, revision_id FROM apify_route_active_slots
                   WHERE workspace_id = ? AND route_id = ?""",
                (self.workspace_id, str(route["route_id"])),
            ).fetchall()
        }
        target_count = self.pool_stage_operation_target_count(
            connection,
            route_id=str(route["route_id"]),
            goal=goal,
            target_slot=target_slot,
            populated_count=sum(bool(value) for value in active_slots.values()),
            requested_count=target_slot_count,
            minimum_healthy=int(route["min_runtime_healthy"]),
        )
        selected = next(
            (
                item
                for item in self._list_compatibility_candidates(connection, route)[
                    "candidates"
                ]
                if str(item["candidate_id"]) == candidate_ids[0]
            ),
            None,
        )
        if (
            selected is None
            or not bool(selected.get("selectable"))
            or bool(selected.get("active_in_route"))
        ):
            raise ops.ActorOpsError(
                "apify_actor_candidate_not_selectable",
                "Selected Actor no longer satisfies the compatibility fences",
                status_code=412,
            )
        profile = self._x_slot_validation_profile(
            selected, candidate_ids[0], candidate_validation_profiles,
            route_cap=float(route["per_run_cap_usd"]),
        )
        revision = connection.execute(
            """SELECT revision.*, candidate.display_name
               FROM apify_actor_adapter_revisions AS revision
               JOIN apify_actor_candidates AS candidate
                 ON candidate.workspace_id = revision.workspace_id
                AND candidate.id = revision.candidate_id
               WHERE revision.workspace_id = ? AND revision.revision_id = ?""",
            (self.workspace_id, str(selected["revision_id"])),
        ).fetchone()
        if revision is None:
            raise ops.ActorOpsError(
                "apify_actor_revision_not_found",
                "Selected Actor revision was not found",
                status_code=404,
            )
        assert target_slot is not None
        target_slots = dict(active_slots)
        target_slots[target_slot] = str(revision["revision_id"])
        return {
            "connection": connection,
            "run": run,
            "goal": goal,
            "route": route,
            "selected": selected,
            "revision": revision,
            "profile": profile,
            "target_count": target_count,
            "target_slot": target_slot,
            "active_slots": active_slots,
            "target_slots": target_slots,
        }

    def _x_slot_validation_profile(
        self,
        selected: dict[str, Any],
        candidate_id: str,
        profiles: Any,
        *,
        route_cap: float,
    ) -> dict[str, Any]:
        ops = _ensure_ops_symbols()
        options = dict(selected.get("validation_options") or {})
        requested = list(profiles or ())
        if not requested:
            return {
                "timeout_seconds": int(options["timeout_seconds"]),
                "sample_items": int(options["sample_items"]),
                "max_charge_usd": round(
                    min(route_cap, float(ops.VALIDATION_MAX_CHARGE_USD_LIMIT)),
                    6,
                ),
                "supports_sample_items": True,
                "options_hash": str(options["options_hash"]),
                "profile_hash": str(options["profile_hash"]),
            }
        same = (
            len(requested) == 1
            and str(requested[0].get("candidate_id") or "") == candidate_id
            and str(requested[0].get("options_hash") or "")
            == str(options.get("options_hash") or "")
            and int(requested[0].get("timeout_seconds") or 0)
            == int(options.get("timeout_seconds") or 0)
            and int(requested[0].get("sample_items") or 0)
            == int(options.get("sample_items") or 0)
            and math.isclose(
                float(requested[0].get("max_charge_usd") or 0),
                float(options.get("max_charge_usd") or 0),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        )
        if not same:
            raise ops.ActorOpsError(
                "apify_actor_validation_options_stale",
                "Compatibility validation controls changed; reload before approval",
                status_code=409,
            )
        return {
            "timeout_seconds": int(options["timeout_seconds"]),
            "sample_items": int(options["sample_items"]),
            "max_charge_usd": round(
                min(route_cap, float(ops.VALIDATION_MAX_CHARGE_USD_LIMIT)),
                6,
            ),
            "supports_sample_items": True,
            "options_hash": str(options["options_hash"]),
            "profile_hash": str(options["profile_hash"]),
        }

    def _x_slot_source_budget(self, context: dict[str, Any]) -> dict[str, Any]:
        ops = _ensure_ops_symbols()
        connection = context["connection"]
        route = context["route"]
        sources = connection.execute(
            """SELECT binding.source_id, binding.generation, binding.target_fingerprint
               FROM apify_source_route_bindings AS binding
               JOIN source_catalog AS source
                 ON source.workspace_id = binding.workspace_id
                AND source.id = binding.source_id
               WHERE binding.workspace_id = ? AND binding.route_id = ?
                 AND source.enabled = 1
               ORDER BY binding.source_id LIMIT ?""",
            (self.workspace_id, str(route["route_id"]), int(ops.POOL_STAGE_MAX_SOURCES) + 1),
        ).fetchall()
        if len(sources) > int(ops.POOL_STAGE_MAX_SOURCES):
            raise ops.ActorOpsError(
                "apify_actor_pool_stage_source_limit",
                "Too many enabled sources are attached to this Actor route",
                status_code=412,
            )
        missing = sum(
            self._x_slot_source_proof_missing(
                connection, route_id=str(route["route_id"]), source=source,
                revision_id=revision_id,
            )
            for source in sources
            for revision_id in context["target_slots"].values()
            if revision_id
        )
        return {"rows": sources, "missing": missing}

    def _x_slot_source_proof_missing(
        self,
        connection: sqlite3.Connection,
        *,
        route_id: str,
        source: sqlite3.Row,
        revision_id: str,
    ) -> int:
        proof = connection.execute(
            """SELECT 1 FROM apify_actor_validations
               WHERE workspace_id = ? AND route_id = ? AND source_id = ?
                 AND revision_id = ? AND kind = 'source_canary'
                 AND status = 'succeeded' AND cost_final = 1
                 AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                 AND target_fingerprint = ? LIMIT 1""",
            (
                self.workspace_id, route_id, str(source["source_id"]),
                revision_id, str(source["target_fingerprint"]),
            ),
        ).fetchone()
        return int(proof is None)

    def _x_slot_plan_response(
        self,
        context: dict[str, Any],
        sources: dict[str, Any],
        *,
        max_total_charge_usd: float | None,
        selection_mode: str = "manual",
    ) -> dict[str, Any]:
        ops = _ensure_ops_symbols()
        route, run, selected, revision = (
            context["route"], context["run"], context["selected"], context["revision"]
        )
        profile, cap = context["profile"], float(context["profile"]["max_charge_usd"])
        route_cap = 0.0 if bool(selected.get("already_validated")) else cap
        source_cap = round(int(sources["missing"]) * cap, 6)
        total_cap = round(route_cap + source_cap, 6)
        if max_total_charge_usd is not None and not math.isclose(
            float(max_total_charge_usd), total_cap, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ops.ActorOpsError(
                "apify_actor_canary_plan_conflict",
                "Compatibility slot validation cap changed; reload before approval",
                status_code=409,
            )
        from .apify_actor_canary import next_reference_fingerprint

        item = self._x_slot_plan_item(revision, selected, profile)
        snapshot = [
            {
                "source_id": str(row["source_id"]),
                "binding_generation": int(row["generation"]),
                "target_fingerprint": str(row["target_fingerprint"]),
            }
            for row in sources["rows"]
        ]
        payload = self._x_slot_plan_payload(
            context, item, snapshot, total_cap, selection_mode=selection_mode
        )
        plan_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        reference = next_reference_fingerprint(
            self.store, workspace_id=self.workspace_id, platform="x",
            route_id=str(route["route_id"]), revision_id=str(revision["revision_id"]),
        )
        return {
            **payload, "route_key": str(route["route_key"]), "platform": "x",
            "target_type": str(route["target_type"]), "capability": str(route["capability"]),
            "mode": str(route["mode"]), "status": "ready", "ready": True,
            "activation_ready": False, "plan_hash": plan_hash, "max_candidates": 1,
            "route_validation_cap_usd": round(route_cap, 6),
            "source_validation_cap_usd": source_cap, "source_count": len(snapshot),
            "source_validation_count": int(sources["missing"]),
            "per_candidate_cap_usd": round(cap, 6),
            "successful_actor_count": int(bool(selected.get("already_validated"))),
            "successful_publisher_count": int(bool(selected.get("already_validated"))),
            "attempts_used": 0, "attempts_remaining": 1,
            "budget_remaining_usd": round(float(ops.POOL_STAGE_MAX_TOTAL_USD) - total_cap, 6),
            "_eligible_candidate_count": sum(
                bool(row.get("selectable"))
                for row in self._list_compatibility_candidates(
                    context["connection"], route
                )["candidates"]
            ),
            "_source_snapshot": snapshot,
            "_reference_fingerprints": {str(revision["revision_id"]): reference},
        }

    @staticmethod
    def _x_slot_plan_item(
        revision: sqlite3.Row, selected: dict[str, Any], profile: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "ordinal": 1, "candidate_id": str(revision["candidate_id"]),
            "revision_id": str(revision["revision_id"]), "actor_id": str(revision["actor_id"]),
            "publisher": str(revision["publisher"]), "build_id": str(revision["build_id"] or ""),
            "build_number": str(revision["build_number"] or ""),
            "manifest_hash": str(revision["manifest_hash"] or ""),
            "already_validated": bool(selected.get("already_validated")),
            "authorized_cap_usd": float(profile["max_charge_usd"]),
            "validation_profile": profile,
        }

    def _x_slot_plan_payload(
        self, context: dict[str, Any], item: dict[str, Any],
        snapshot: list[dict[str, Any]], total_cap: float, *, selection_mode: str,
    ) -> dict[str, Any]:
        ops = _ensure_ops_symbols()
        return {
            "schema_version": 4, "goal": context["goal"],
            "operation_mode": "compatibility_slot", "operation_slot": context["target_slot"],
            "selection_mode": selection_mode, "target_slot_count": context["target_count"],
            "run_id": str(context["run"]["run_id"]), "route_id": str(context["route"]["route_id"]),
            "generation": int(context["route"]["generation"]),
            "base_pool_hash": ops.revision_set_hash(context["active_slots"]),
            "base_slots": context["active_slots"],
            "items": [{key: item[key] for key in (
                "ordinal", "candidate_id", "revision_id", "actor_id", "publisher",
                "build_id", "build_number", "manifest_hash", "already_validated",
                "authorized_cap_usd", "validation_profile",
            )}],
            "sources": snapshot, "required_success_count": 1,
            "required_source_slots": context["target_count"],
            "max_total_charge_usd": total_cap,
        }
