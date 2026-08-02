"""Explicitly approved paid Canary execution for one immutable revision."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..scrapers.apify_client import ApifyClient, ApifyClientError
from ..storage.service_store import ServiceStore
from .apify_key_pool import ApifyKeyPoolError
from .apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    map_actor_output,
    parse_actor_manifest,
    render_actor_input,
)
from .apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    RouteExecutionSnapshot,
    RouteSlotSnapshot,
    source_target_fingerprint,
)


_REFERENCE_TARGETS: dict[str, tuple[ActorTarget, ...]] = {
    "x": (
        ActorTarget(canonical_url="https://x.com/openai", handle="openai"),
        ActorTarget(canonical_url="https://x.com/github", handle="github"),
    ),
    "instagram": (
        ActorTarget(
            canonical_url="https://www.instagram.com/instagram/",
            handle="instagram",
        ),
        ActorTarget(
            canonical_url="https://www.instagram.com/natgeo/",
            handle="natgeo",
        ),
    ),
    "youtube": (
        ActorTarget(
            canonical_url="https://www.youtube.com/@YouTube",
            handle="YouTube",
        ),
        ActorTarget(
            canonical_url="https://www.youtube.com/@GoogleDevelopers",
            handle="GoogleDevelopers",
        ),
    ),
}

DEFAULT_ACTOR_CANARY_TIMEOUT_SECONDS = 300
MIN_ACTOR_CANARY_TIMEOUT_SECONDS = 180
MAX_ACTOR_CANARY_TIMEOUT_SECONDS = 900
_HARD_OUTPUT_CONTRACT_FAILURES = frozenset(
    {
        "apify_actor_contract_mismatch",
        "apify_actor_metadata_only",
        "apify_actor_placeholder",
    }
)


def actor_canary_timeout_seconds() -> int:
    """Return the bounded per-Actor Canary timeout hot-loaded per job."""

    raw = os.getenv(
        "HORIZON_APIFY_ACTOR_CANARY_TIMEOUT_SECONDS",
        str(DEFAULT_ACTOR_CANARY_TIMEOUT_SECONDS),
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_ACTOR_CANARY_TIMEOUT_SECONDS
    return max(
        MIN_ACTOR_CANARY_TIMEOUT_SECONDS,
        min(value, MAX_ACTOR_CANARY_TIMEOUT_SECONDS),
    )


def reference_target_fingerprint(
    target: ActorTarget,
    *,
    workspace_id: str,
    route_id: str,
    platform: str,
) -> str:
    """Return a stable opaque digest without persisting the reference target."""

    identity = (
        target.native_id
        or target.handle
        or target.canonical_url
        or ""
    ).strip()
    if not identity:
        raise ActorOpsError(
            "apify_actor_reference_unavailable",
            "Public reference target does not have a stable identity",
            status_code=412,
        )
    return source_target_fingerprint(
        workspace_id,
        route_id,
        identity,
        platform=platform,
    )


def next_reference_fingerprint(
    store: ServiceStore,
    *,
    workspace_id: str,
    platform: str,
    route_id: str,
    revision_id: str,
) -> str:
    """Choose the next fixed public reference without returning its value."""

    references = _REFERENCE_TARGETS.get(str(platform).casefold())
    if not references:
        raise ActorOpsError(
            "apify_actor_reference_unavailable",
            "No public reference target is configured for this Route",
            status_code=412,
        )
    used = {
        str(row["target_fingerprint"])
        for row in store.connect().execute(
            """
            SELECT target_fingerprint
            FROM apify_actor_validations
            WHERE workspace_id = ? AND revision_id = ?
              AND kind = 'route_reference'
              AND status IN ('queued', 'running', 'succeeded')
              AND target_fingerprint IS NOT NULL
            """,
            (workspace_id, revision_id),
        ).fetchall()
    }
    for target in references:
        fingerprint = reference_target_fingerprint(
            target,
            workspace_id=workspace_id,
            route_id=route_id,
            platform=platform,
        )
        if fingerprint not in used:
            return fingerprint
    return reference_target_fingerprint(
        references[-1],
        workspace_id=workspace_id,
        route_id=route_id,
        platform=platform,
    )


@dataclass(frozen=True, slots=True)
class CanaryResult:
    validation_id: str
    revision_id: str
    status: str
    semantic_outcome: str
    cost_usd: float | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "revision_id": self.revision_id,
            "status": self.status,
            "semantic_outcome": self.semantic_outcome,
            "cost_usd": self.cost_usd,
        }


class ApifyActorCanaryRunner:
    """Run a single queued validation; raw input and Dataset never persist."""

    def __init__(
        self,
        store: ServiceStore,
        ops: ApifyActorOpsService,
        client: ApifyClient,
    ) -> None:
        self.store = store
        self.ops = ops
        self.client = client

    async def run(
        self,
        validation_id: str,
        *,
        job_id: str,
        skip_preflight: bool = False,
    ) -> CanaryResult:
        row = self.store.connect().execute(
            """
            SELECT validation.*, profile.route_key, profile.platform,
                   profile.generation AS route_generation,
                   profile.per_run_cap_usd, profile.status AS route_status,
                   revision.candidate_id, revision.actor_id,
                   revision.publisher, revision.build_id,
                   revision.build_number, revision.manifest_json,
                   revision.manifest_hash, revision.lifecycle,
                   candidate.state AS candidate_state
            FROM apify_actor_validations AS validation
            JOIN apify_actor_route_profiles AS profile
              ON profile.route_id = validation.route_id
             AND profile.workspace_id = validation.workspace_id
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.revision_id = validation.revision_id
             AND revision.workspace_id = validation.workspace_id
            JOIN apify_actor_candidates AS candidate
              ON candidate.id = revision.candidate_id
             AND candidate.workspace_id = validation.workspace_id
            WHERE validation.workspace_id = ? AND validation.validation_id = ?
            """,
            (self.ops.workspace_id, validation_id),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_validation_not_found",
                "Actor validation was not found",
                status_code=404,
            )
        if str(row["status"]) != "queued":
            raise ActorOpsError(
                "apify_actor_validation_not_queued",
                "Actor validation is not queued",
            )
        if (
            not row["build_id"]
            or not row["build_number"]
            or not row["manifest_json"]
            or not row["manifest_hash"]
        ):
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome="revision_not_executable",
            )
            raise ActorOpsError(
                "apify_actor_revision_not_executable",
                "Actor adapter revision does not have an exact Build and Manifest",
                status_code=412,
            )
        if (
            str(row["kind"]) == "route_reference"
            and int(row["route_generation"])
            != int(row["approved_generation"] or -1)
        ):
            self.ops.record_validation(
                validation_id,
                status="cancelled",
                semantic_outcome="approval_stale",
            )
            raise ActorOpsError(
                "apify_actor_canary_approval_stale",
                "Actor Route changed after Canary approval",
                status_code=409,
            )
        if not self._approval_still_authorized(row):
            self.ops.record_validation(
                validation_id,
                status="cancelled",
                semantic_outcome="approval_revoked",
            )
            raise ActorOpsError(
                "apify_actor_canary_approval_stale",
                "Actor revision eligibility changed after Canary approval",
                status_code=409,
            )
        manifest = parse_actor_manifest(str(row["manifest_json"]))
        try:
            target = self._target_for(row)
        except ActorOpsError as exc:
            self.ops.record_validation(
                validation_id,
                status="cancelled",
                semantic_outcome=str(exc.code),
            )
            raise
        runtime = ActorRuntime(
            max_items=1,
            until_iso=datetime.now(timezone.utc).isoformat(),
        )
        actor_input = render_actor_input(manifest, target, runtime)
        slot_name = self._slot_name(row)
        slot = RouteSlotSnapshot(
            slot_name=slot_name,
            candidate_id=str(row["candidate_id"]),
            revision_id=str(row["revision_id"]),
            actor_id=str(row["actor_id"]),
            publisher=str(row["publisher"]),
            build_id=str(row["build_id"]),
            build_number=str(row["build_number"]),
            manifest_hash=str(row["manifest_hash"]),
            lifecycle=str(row["lifecycle"]),
            candidate_state=str(row["candidate_state"]),
            manifest=manifest,
        )
        key_row = self.store.connect().execute(
            """
            SELECT generation FROM apify_key_pool_state
            WHERE workspace_id = ?
            """,
            (self.ops.workspace_id,),
        ).fetchone()
        snapshot = RouteExecutionSnapshot(
            workspace_id=self.ops.workspace_id,
            route_id=str(row["route_id"]),
            route_key=str(row["route_key"]),
            route_generation=int(row["route_generation"]),
            per_run_cap_usd=min(
                float(row["per_run_cap_usd"]),
                float(
                    row["approved_max_cost_usd"]
                    or row["cost_usd"]
                    or row["per_run_cap_usd"]
                ),
            ),
            slots=(slot,),
            source_id=(
                str(row["source_id"]) if row["source_id"] is not None else None
            ),
            target_fingerprint=str(row["target_fingerprint"] or "") or None,
            key_pool_generation=(
                int(key_row["generation"]) if key_row is not None else None
            ),
        )
        preflight = getattr(self.client, "preflight_actor_revision", None)
        if not skip_preflight and callable(preflight):
            try:
                await preflight(
                    slot.actor_id,
                    build_id=str(slot.build_id),
                    build_number=str(slot.build_number),
                )
            except ApifyClientError as exc:
                deterministic = str(exc.code) == (
                    "apify_actor_revision_unavailable"
                )
                self.ops.record_validation(
                    validation_id,
                    status="failed",
                    semantic_outcome=str(exc.code),
                    cost_usd=0.0,
                    cost_final=True,
                    counts_toward_canary=False,
                )
                if deterministic:
                    self.ops.stop_unavailable_revision(
                        str(row["revision_id"]),
                        reason=str(exc.code),
                    )
                raise ActorOpsError(
                    str(exc.code),
                    "Actor revision failed the free paid-start preflight",
                    retryable=bool(exc.retryable),
                    status_code=(
                        503
                        if exc.retryable
                        else 412
                        if deterministic
                        else 422
                    ),
                ) from None
        attempt_id = self.ops.begin_validation_attempt(
            validation_id,
            snapshot,
            slot,
            job_id=job_id,
        )
        actual_charge_usd: float | None = None
        try:
            run = await self.client.run_actor_detailed(
                slot.actor_id,
                actor_input,
                max_total_charge_usd=snapshot.per_run_cap_usd,
                logical_run_id=attempt_id,
                build_number=slot.build_number,
                max_paid_dataset_items=1,
                dataset_item_limit=2,
                expected_pool_generation=snapshot.key_pool_generation,
                max_remote_starts=1,
            )
            actual_charge_usd = run.actual_charge_usd
            mapped = map_actor_output(manifest, run.items, target, runtime)
        except TimeoutError:
            error_code = "apify_actor_run_timed_out"
            actual_charge_usd = self.ops.finalized_actor_run_cost(attempt_id)
            self.ops.finish_attempt(
                attempt_id,
                status="actor_failed",
                semantic_outcome=error_code,
                actual_cost_usd=actual_charge_usd,
                error_code=error_code,
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=error_code,
                attempt_id=attempt_id,
                cost_usd=actual_charge_usd,
            )
            raise ActorOpsError(
                error_code,
                "Actor Canary timed out and was aborted",
                retryable=True,
                status_code=503,
            ) from None
        except ApifyClientError as exc:
            unknown = exc.code in {
                "apify_start_outcome_unknown",
                "apify_run_reconcile_required",
            }
            public_error_code = str(exc.code)
            if unknown:
                self.ops.finish_unknown_start(
                    snapshot,
                    attempt_id=attempt_id,
                    semantic_outcome=str(exc.code),
                    error_code=str(exc.code),
                    validation_id=validation_id,
                )
            elif (
                str(exc.code)
                in {
                    "apify_actor_deleted",
                    "apify_actor_build_unavailable",
                    "apify_actor_start_rejected",
                }
                and self.ops.proven_no_remote_start(attempt_id)
            ):
                self.ops.finish_attempt(
                    attempt_id,
                    status="cancelled",
                    semantic_outcome="apify_actor_revision_unavailable",
                    actual_cost_usd=0.0,
                    error_code="apify_actor_revision_unavailable",
                )
                self.ops.record_validation(
                    validation_id,
                    status="failed",
                    semantic_outcome="apify_actor_revision_unavailable",
                    attempt_id=attempt_id,
                    cost_usd=0.0,
                    cost_final=True,
                    counts_toward_canary=False,
                )
                self.ops.stop_unavailable_revision(
                    str(row["revision_id"]),
                    reason="apify_actor_revision_unavailable",
                )
                public_error_code = "apify_actor_revision_unavailable"
            else:
                actual_charge_usd = self.ops.finalized_actor_run_cost(
                    attempt_id
                )
                self.ops.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome=str(exc.code),
                    actual_cost_usd=actual_charge_usd,
                    error_code=str(exc.code),
                )
                self.ops.record_validation(
                    validation_id,
                    status="failed",
                    semantic_outcome=str(exc.code),
                    attempt_id=attempt_id,
                    cost_usd=actual_charge_usd,
                    cost_final=actual_charge_usd is not None,
                )
            raise ActorOpsError(
                public_error_code,
                "Actor Canary could not complete safely",
                retryable=bool(exc.retryable),
                status_code=503 if unknown or exc.retryable else 422,
            ) from None
        except ApifyKeyPoolError as exc:
            self.ops.finish_attempt(
                attempt_id,
                status="cancelled",
                semantic_outcome=str(exc.code),
                actual_cost_usd=0.0,
                error_code=str(exc.code),
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=str(exc.code),
                attempt_id=attempt_id,
                cost_usd=0.0,
                cost_final=True,
                counts_toward_canary=False,
            )
            raise ActorOpsError(
                str(exc.code),
                "Actor Canary could not acquire an eligible Key",
                retryable=bool(exc.retryable),
                status_code=503,
            ) from None
        except ActorManifestError as exc:
            self.ops.finish_attempt(
                attempt_id,
                status="actor_failed",
                semantic_outcome=str(exc.code),
                actual_cost_usd=actual_charge_usd,
                error_code=str(exc.code),
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=str(exc.code),
                attempt_id=attempt_id,
                cost_usd=actual_charge_usd,
            )
            if (
                str(row["kind"]) == "route_reference"
                and str(exc.code) in _HARD_OUTPUT_CONTRACT_FAILURES
            ):
                self._stop_incompatible_revision(str(row["revision_id"]))
            raise ActorOpsError(
                str(exc.code),
                "Actor Canary output failed semantic validation",
                retryable=bool(exc.retryable),
                status_code=422,
            ) from None

        semantic = str(mapped.semantic_outcome)
        if semantic not in {"valid_nonempty", "valid_empty"}:
            self.ops.finish_attempt(
                attempt_id,
                status="actor_failed",
                semantic_outcome=semantic,
                actual_cost_usd=run.actual_charge_usd,
                error_code="apify_actor_suspicious_empty",
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=semantic,
                attempt_id=attempt_id,
                cost_usd=run.actual_charge_usd,
            )
            raise ActorOpsError(
                "apify_actor_suspicious_empty",
                "Actor Canary returned an unconfirmed empty Dataset",
                status_code=422,
            )
        self.ops.finish_attempt(
            attempt_id,
            status=("valid_empty" if semantic == "valid_empty" else "succeeded"),
            semantic_outcome=semantic,
            actual_cost_usd=run.actual_charge_usd,
        )
        validation = self.ops.record_validation(
            validation_id,
            status="succeeded",
            semantic_outcome=semantic,
            attempt_id=attempt_id,
            cost_usd=run.actual_charge_usd,
        )
        if str(row["kind"]) == "route_reference":
            self._advance_revision(str(row["revision_id"]))
        return CanaryResult(
            validation_id=str(validation["validation_id"]),
            revision_id=str(validation["revision_id"]),
            status=str(validation["status"]),
            semantic_outcome=str(validation["semantic_outcome"]),
            cost_usd=(
                float(validation["cost_usd"])
                if validation["cost_usd"] is not None
                else None
            ),
        )

    def _target_for(self, row: Any) -> ActorTarget:
        if row["source_id"] is not None:
            source = self.store.get_source(str(row["source_id"]))
            if source is None or str(source["workspace_id"]) != self.ops.workspace_id:
                raise ActorOpsError(
                    "apify_actor_source_not_found",
                    "Actor validation source was not found",
                    status_code=404,
                )
            binding = self.store.connect().execute(
                """
                SELECT route_id, target_fingerprint, generation
                FROM apify_source_route_bindings
                WHERE workspace_id = ? AND source_id = ?
                """,
                (self.ops.workspace_id, str(row["source_id"])),
            ).fetchone()
            active = self.store.connect().execute(
                """
                SELECT 1 FROM apify_route_active_slots
                WHERE workspace_id = ? AND route_id = ? AND revision_id = ?
                """,
                (
                    self.ops.workspace_id,
                    str(row["route_id"]),
                    str(row["revision_id"]),
                ),
            ).fetchone()
            config = (
                source["config"]
                if isinstance(source.get("config"), dict)
                else {}
            )
            expected_fingerprint = source_target_fingerprint(
                self.ops.workspace_id,
                str(row["route_id"]),
                str(config.get("target") or config.get("url") or ""),
                platform=str(row["platform"]),
            )
            if (
                binding is None
                or str(binding["route_id"]) != str(row["route_id"])
                or str(binding["target_fingerprint"])
                != str(row["target_fingerprint"] or "")
                or str(binding["target_fingerprint"]) != expected_fingerprint
                or int(binding["generation"])
                != int(row["approved_generation"] or -1)
                or active is None
            ):
                raise ActorOpsError(
                    "apify_actor_canary_approval_stale",
                    "Actor source changed after Canary approval",
                    status_code=409,
                )
            return _source_target(
                platform=str(row["platform"]),
                config=config,
            )
        references = _REFERENCE_TARGETS.get(str(row["platform"]))
        if not references:
            raise ActorOpsError(
                "apify_actor_reference_unavailable",
                "No public reference target is configured for this Route",
                status_code=412,
            )
        expected_fingerprint = str(row["target_fingerprint"] or "")
        for target in references:
            if reference_target_fingerprint(
                target,
                workspace_id=self.ops.workspace_id,
                route_id=str(row["route_id"]),
                platform=str(row["platform"]),
            ) == expected_fingerprint:
                return target
        raise ActorOpsError(
            "apify_actor_reference_unavailable",
            "Approved public reference target is not in the fixed catalog",
            status_code=412,
        )

    def _slot_name(self, row: Any) -> str:
        slot = self.store.connect().execute(
            """
            SELECT slot_name FROM apify_route_active_slots
            WHERE workspace_id = ? AND route_id = ? AND revision_id = ?
            """,
            (
                self.ops.workspace_id,
                str(row["route_id"]),
                str(row["revision_id"]),
            ),
        ).fetchone()
        return str(slot["slot_name"]) if slot is not None else "primary"

    def _approval_still_authorized(self, row: Any) -> bool:
        lifecycle = str(row["lifecycle"])
        state = str(row["candidate_state"])
        if str(row["kind"]) == "route_reference":
            return (
                lifecycle in {"static_valid", "probationary"}
                and state != "open"
            )
        slot = self.store.connect().execute(
            """
            SELECT slot.slot_name
            FROM apify_route_active_slots AS slot
            WHERE slot.workspace_id = ? AND slot.route_id = ?
              AND slot.candidate_id = ? AND slot.revision_id = ?
            """,
            (
                self.ops.workspace_id,
                str(row["route_id"]),
                str(row["candidate_id"]),
                str(row["revision_id"]),
            ),
        ).fetchone()
        if slot is None or state not in {"closed", "half_open", "probationary"}:
            return False
        allowed = (
            {"certified", "legacy_builtin"}
            if str(slot["slot_name"]) in {"primary", "backup_1"}
            else {"certified", "probationary", "legacy_builtin"}
        )
        return lifecycle in allowed

    def _advance_revision(self, revision_id: str) -> None:
        lifecycle = str(self.ops.get_revision(revision_id)["lifecycle"])
        try:
            if lifecycle == "static_valid":
                self.ops.transition_revision(
                    revision_id,
                    expected_lifecycle="static_valid",
                    lifecycle="probationary",
                )
            elif lifecycle == "probationary":
                self.ops.transition_revision(
                    revision_id,
                    expected_lifecycle="probationary",
                    lifecycle="certified",
                )
        except ActorOpsError as exc:
            if exc.code not in {
                "apify_actor_revision_canary_incomplete",
                "apify_actor_revision_observation_incomplete",
                "apify_actor_revision_success_rate_low",
            }:
                raise

    def _stop_incompatible_revision(self, revision_id: str) -> None:
        """Prevent another paid Canary for an immutable incompatible Build."""

        lifecycle = str(self.ops.get_revision(revision_id)["lifecycle"])
        destination = (
            "rejected" if lifecycle == "static_valid" else "quarantined"
        )
        if lifecycle not in {"static_valid", "probationary"}:
            return
        try:
            self.ops.transition_revision(
                revision_id,
                expected_lifecycle=lifecycle,
                lifecycle=destination,
            )
        except ActorOpsError as exc:
            if exc.code != "apify_actor_revision_generation_conflict":
                raise

def _source_target(
    *,
    platform: str,
    config: dict[str, Any],
) -> ActorTarget:
    raw = str(config.get("target") or config.get("url") or "").strip()
    if not raw:
        raise ActorOpsError(
            "apify_actor_target_invalid",
            "Actor validation source target is unavailable",
            status_code=422,
        )
    from .apify_actor_runtime import actor_target_for_route

    return actor_target_for_route(platform, raw)


__all__ = [
    "ApifyActorCanaryRunner",
    "CanaryResult",
    "next_reference_fingerprint",
    "reference_target_fingerprint",
]
