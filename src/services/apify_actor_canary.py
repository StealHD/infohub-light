"""Explicitly approved paid Canary execution for one immutable revision."""

from __future__ import annotations

import json
import os
import re
import time
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
    parse_actor_manifest,
    render_actor_input,
)
from .apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    RouteExecutionSnapshot,
    RouteSlotSnapshot,
    revision_set_hash,
    source_target_fingerprint,
)
from .apify_actor_canary_compatibility import (
    CompatibilityPreflightError,
    preflight_compatibility_candidate,
    run_compatibility_if_needed,
)
from .apify_actor_candidate_authorization import route_reference_candidate_authorized
from .apify_actor_source_canary_authorization import source_canary_candidate_authorized
from .apify_actor_slot_recovery import recover_source_proven_slots
from .apify_actor_observed_probe import map_canary_output_for_revision, settled_observed_validation
from .apify_actor_canary_cost_guard import run_actor_with_charge_guard

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
            native_id="UCBR8-60-B28hp2BmDPdntcQ",
            handle="YouTube",
        ),
        ActorTarget(
            canonical_url="https://www.youtube.com/@GoogleDevelopers",
            native_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
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
_SAFE_CANARY_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
def _safe_canary_code(value: Any, fallback: str) -> str:
    code = str(value or "").strip().casefold().replace("-", "_")
    return code if _SAFE_CANARY_CODE.fullmatch(code) else fallback
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


def reference_target_for_slot(platform: str, slot: int) -> ActorTarget:
    """Resolve an internal fixed reference without exposing it in admin APIs."""

    references = _REFERENCE_TARGETS.get(str(platform).strip().casefold())
    if not references or int(slot) not in range(len(references)):
        raise ActorOpsError(
            "apify_actor_reference_unavailable",
            "No public reference target is configured for this Route",
            status_code=412,
        )
    return references[int(slot)]


def reference_target_fingerprint(
    target: ActorTarget,
    *,
    workspace_id: str,
    route_id: str,
    platform: str,
) -> str:
    """Return a stable opaque digest without persisting the reference target."""

    # Keep historical reference fingerprints stable when a public channel's
    # exact native ID is added later for Actor inputs.
    identity = (
        target.handle
        or target.native_id
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
                   profile.admission_mode,
                   revision.candidate_id, revision.actor_id,
                   revision.publisher, revision.build_id,
                   revision.build_number, revision.manifest_json,
                   revision.manifest_hash, revision.lifecycle,
                   revision.execution_mode, revision.observed_manifest,
                   revision.security_evidence_json,
                   candidate.state AS candidate_state,
                   candidate.last_error_code AS candidate_last_error_code,
                   EXISTS (
                       SELECT 1
                       FROM apify_actor_canary_batch_items AS batch_item
                       JOIN apify_actor_canary_batches AS batch
                         ON batch.workspace_id = batch_item.workspace_id
                        AND batch.batch_id = batch_item.batch_id
                       WHERE batch_item.workspace_id = validation.workspace_id
                         AND batch_item.validation_id = validation.validation_id
                         AND batch.goal = 'compatibility_single'
                   ) AS compatibility_validation
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
        compatibility_result = await run_compatibility_if_needed(
            self, row, validation_id=validation_id, job_id=job_id
        )
        if compatibility_result is not None:
            return compatibility_result
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
        timeout_seconds = int(
            row["validation_timeout_seconds"]
            or actor_canary_timeout_seconds()
        )
        sample_items = int(row["validation_sample_items"] or 1)
        runtime = ActorRuntime(
            max_items=sample_items,
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
            per_run_cap_usd=float(
                row["approved_max_cost_usd"]
                or row["cost_usd"]
                or row["per_run_cap_usd"]
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
        run_started = time.monotonic()

        def elapsed_seconds() -> int:
            return max(0, int(round(time.monotonic() - run_started)))

        try:
            run = await run_actor_with_charge_guard(
                self, validation_id=validation_id, attempt_id=attempt_id,
                snapshot=snapshot, slot=slot, actor_input=actor_input,
                max_paid_dataset_items=sample_items,
                dataset_item_limit=sample_items + 1,
                timeout_seconds=timeout_seconds, duration_seconds=elapsed_seconds,
            )
            actual_charge_usd = run.actual_charge_usd
            mapped, observed_manifest = map_canary_output_for_revision(manifest, run.items, target, runtime, row)
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
                duration_seconds=elapsed_seconds(),
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
                    duration_seconds=elapsed_seconds(),
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
                    duration_seconds=elapsed_seconds(),
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
                duration_seconds=elapsed_seconds(),
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
                duration_seconds=elapsed_seconds(),
                dataset_row_count=(len(run.items) if "run" in locals() else None),
                mapped_item_count=0,
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
                duration_seconds=elapsed_seconds(),
                dataset_row_count=len(run.items),
                mapped_item_count=0,
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
            duration_seconds=elapsed_seconds(),
            dataset_row_count=len(run.items),
            mapped_item_count=len(mapped.items),
        )
        validation = settled_observed_validation(self.ops, validation, validation_id, observed_manifest)
        if str(row["kind"]) == "route_reference":
            self._advance_revision(str(validation["revision_id"]))
        if str(row["kind"]) == "source_canary": recover_source_proven_slots(self.store, workspace_id=self.ops.workspace_id)
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

    async def _run_compatibility_single(
        self,
        row: Any,
        *,
        validation_id: str,
        job_id: str,
    ) -> CanaryResult:
        """Run one controlled X adapter and require a real nonempty result."""
        from urllib.parse import urlparse

        from ..models import (
            ApifySocialConfig,
            ApifySocialPlatform,
            ApifySocialSubscriptionConfig,
        )
        from ..scrapers.apify_social import (
            ApifySocialScraper,
            ApifySocialSemanticError,
        )
        if str(row["platform"]) != "x":
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome="compatibility_route_unsupported",
                cost_usd=0.0,
                cost_final=True,
                counts_toward_canary=False,
            )
            raise ActorOpsError(
                "compatibility_route_unsupported",
                "Compatibility single-Actor trial currently supports X only",
                status_code=412,
            )
        security_evidence = {}
        try:
            parsed_security = json.loads(str(row["security_evidence_json"] or "{}"))
            if isinstance(parsed_security, dict):
                security_evidence = parsed_security
        except (TypeError, ValueError, json.JSONDecodeError):
            security_evidence = {}
        if (
            str(row["candidate_state"]) == "disabled"
            and not bool(security_evidence.get("compatibility_trial_only"))
        ):
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome="actor_disabled",
                cost_usd=0.0,
                cost_final=True,
                counts_toward_canary=False,
            )
            raise ActorOpsError(
                "actor_disabled",
                "Selected Actor is disabled",
                status_code=412,
            )
        try:
            current_candidate = await preflight_compatibility_candidate(self, row)
        except CompatibilityPreflightError as exc:
            code = _safe_canary_code(
                getattr(exc, "code", None),
                "compatibility_preflight_failed",
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=code,
                cost_usd=0.0,
                cost_final=True,
                counts_toward_canary=False,
            )
            raise ActorOpsError(
                code,
                "Compatibility Actor failed the free paid-start preflight",
                status_code=int(getattr(exc, "status_code", 412)),
            ) from None
        try:
            target = self._target_for(row)
            expected_handle = (
                str(target.handle or "").strip().lstrip("@").casefold()
            )
            if not expected_handle:
                raise ActorOpsError(
                    "apify_actor_reference_unavailable",
                    "Compatibility reference does not have a public handle",
                    status_code=412,
                )
            sub = ApifySocialSubscriptionConfig(
                platform=ApifySocialPlatform.X,
                kind="profile",
                target=expected_handle,
                fetch_limit=1,
                enabled=True,
            )
            scraper = ApifySocialScraper(
                ApifySocialConfig(
                    enabled=True,
                    timeout_seconds=int(
                        row["validation_timeout_seconds"]
                        or actor_canary_timeout_seconds()
                    ),
                    subscriptions=[sub],
                ),
                self.client.http_client,
                apify_coordinator=self.client.coordinator,
                paid_canary=True,
            )
            actor_input = scraper._actor_input(
                sub,
                actor_id=str(row["actor_id"]),
                input_dialect=str(
                    security_evidence.get("input_dialect")
                    or "controlled_default"
                ),
                input_count_field=(
                    str(security_evidence["input_count_field"])
                    if security_evidence.get("input_count_field")
                    else None
                ),
            )
        except (ActorOpsError, ValueError) as exc:
            code = _safe_canary_code(
                getattr(exc, "code", None),
                "compatibility_input_invalid",
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=code,
                cost_usd=0.0,
                cost_final=True,
                counts_toward_canary=False,
            )
            if isinstance(exc, ActorOpsError):
                raise
            raise ActorOpsError(
                code,
                "Compatibility Actor input could not be built safely",
                status_code=422,
            ) from None
        slot = RouteSlotSnapshot(
            slot_name="primary",
            candidate_id=str(row["candidate_id"]),
            revision_id=str(row["revision_id"]),
            actor_id=str(row["actor_id"]),
            publisher=str(row["publisher"]),
            build_id=(
                str(current_candidate.build_id)
                if current_candidate.build_id
                else None
            ),
            build_number=(
                str(current_candidate.build_number)
                if current_candidate.build_number
                else None
            ),
            manifest_hash=(
                str(row["manifest_hash"]) if row["manifest_hash"] else None
            ),
            lifecycle=str(row["lifecycle"]),
            candidate_state=str(row["candidate_state"]),
            manifest=None,
        )
        key_row = self.store.connect().execute(
            "SELECT generation FROM apify_key_pool_state WHERE workspace_id = ?",
            (self.ops.workspace_id,),
        ).fetchone()
        snapshot = RouteExecutionSnapshot(
            workspace_id=self.ops.workspace_id,
            route_id=str(row["route_id"]),
            route_key=str(row["route_key"]),
            route_generation=int(row["route_generation"]),
            per_run_cap_usd=min(
                float(row["approved_max_cost_usd"] or 0.02), 0.02
            ),
            slots=(slot,),
            target_fingerprint=str(row["target_fingerprint"] or "") or None,
            key_pool_generation=(
                int(key_row["generation"]) if key_row is not None else None
            ),
        )
        attempt_id = self.ops.begin_validation_attempt(
            validation_id,
            snapshot,
            slot,
            job_id=job_id,
        )
        started = time.monotonic()

        def duration() -> int:
            return max(0, int(round(time.monotonic() - started)))

        run = None
        try:
            run = await run_actor_with_charge_guard(
                self, validation_id=validation_id, attempt_id=attempt_id,
                snapshot=snapshot, slot=slot, actor_input=actor_input,
                max_paid_dataset_items=1, dataset_item_limit=3,
                timeout_seconds=int(
                    row["validation_timeout_seconds"]
                    or actor_canary_timeout_seconds()
                ),
                duration_seconds=duration,
            )
            candidate_rows, semantic = scraper._validated_x_rows(run.items)
            if semantic != "valid_nonempty":
                raise ApifySocialSemanticError(
                    "Compatibility Canary requires real nonempty X posts",
                    code="compatibility_nonempty_required",
                    failure_scope="actor",
                    retryable=False,
                )
            identity_rows: list[dict[str, Any]] = []
            for item in candidate_rows:
                user_value = item.get("user") or item.get("author") or {}
                user = user_value if isinstance(user_value, dict) else {}
                observed = str(
                    user.get("screen_name")
                    or user.get("username")
                    or user.get("userName")
                    or user.get("handle")
                    or item.get("user_screen_name")
                    or item.get("user_username")
                    or item.get("screen_name")
                    or item.get("handle")
                    or item.get("username")
                    or ""
                ).strip().lstrip("@").casefold()
                if not observed:
                    url = str(item.get("url") or item.get("permalink") or "")
                    parsed = urlparse(url)
                    parts = [part for part in parsed.path.split("/") if part]
                    observed = parts[0].lstrip("@").casefold() if parts else ""
                if observed == expected_handle:
                    identity_rows.append(item)
            if not identity_rows:
                raise ApifySocialSemanticError(
                    "Compatibility Canary output did not prove target identity",
                    code="apify_actor_identity_mismatch",
                    failure_scope="actor",
                    retryable=False,
                )
            parsed_items = scraper._parse_candidate_rows(
                identity_rows,
                sub,
                datetime.min.replace(tzinfo=timezone.utc),
            )
            valid_items = [
                item
                for item in parsed_items
                if item.content.strip()
                and item.published_at is not None
                and str(urlparse(item.url).hostname or "").casefold()
                in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
            ]
            if not valid_items:
                raise ApifySocialSemanticError(
                    "Compatibility Canary output failed the publication fence",
                    code="apify_actor_contract_mismatch",
                    failure_scope="actor",
                    retryable=False,
                )
        except TimeoutError:
            code = "apify_actor_run_timed_out"
            cost = self.ops.finalized_actor_run_cost(attempt_id)
            self.ops.finish_attempt(
                attempt_id,
                status="actor_failed",
                semantic_outcome=code,
                actual_cost_usd=cost,
                error_code=code,
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=code,
                attempt_id=attempt_id,
                cost_usd=cost,
                duration_seconds=duration(),
            )
            raise ActorOpsError(
                code,
                "Compatibility Canary timed out",
                retryable=True,
                status_code=503,
            ) from None
        except (ApifyClientError, ApifyKeyPoolError) as exc:
            code = str(exc.code)
            unknown = code in {
                "apify_start_outcome_unknown",
                "apify_run_reconcile_required",
            }
            if unknown:
                self.ops.finish_unknown_start(
                    snapshot,
                    attempt_id=attempt_id,
                    semantic_outcome=code,
                    error_code=code,
                    validation_id=validation_id,
                )
            else:
                cost = self.ops.finalized_actor_run_cost(attempt_id)
                self.ops.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome=code,
                    actual_cost_usd=cost,
                    error_code=code,
                )
                self.ops.record_validation(
                    validation_id,
                    status="failed",
                    semantic_outcome=code,
                    attempt_id=attempt_id,
                    cost_usd=cost,
                    cost_final=cost is not None,
                    duration_seconds=duration(),
                )
            raise ActorOpsError(
                code,
                "Compatibility Canary could not complete safely",
                retryable=bool(getattr(exc, "retryable", False)),
                status_code=503 if unknown else 422,
            ) from None
        except ApifySocialSemanticError as exc:
            cost = run.actual_charge_usd if run is not None else None
            self.ops.finish_attempt(
                attempt_id,
                status="actor_failed",
                semantic_outcome=str(exc.code),
                actual_cost_usd=cost,
                error_code=str(exc.code),
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=str(exc.code),
                attempt_id=attempt_id,
                cost_usd=cost,
                cost_final=bool(run and run.cost_final),
                duration_seconds=duration(),
                dataset_row_count=len(run.items) if run is not None else None,
                mapped_item_count=0,
            )
            raise ActorOpsError(
                str(exc.code),
                "Compatibility Canary output failed validation",
                status_code=422,
            ) from None
        except Exception as exc:
            code = _safe_canary_code(
                getattr(exc, "code", None),
                "compatibility_canary_failed",
            )
            cost = run.actual_charge_usd if run is not None else None
            self.ops.finish_attempt(
                attempt_id,
                status="actor_failed",
                semantic_outcome=code,
                actual_cost_usd=cost,
                error_code=code,
            )
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome=code,
                attempt_id=attempt_id,
                cost_usd=cost,
                cost_final=bool(run and run.cost_final),
                duration_seconds=duration(),
                dataset_row_count=len(run.items) if run is not None else None,
                mapped_item_count=0,
            )
            raise ActorOpsError(
                code,
                "Compatibility Canary failed safely",
                status_code=500,
            ) from None
        assert run is not None
        self.ops.finish_attempt(
            attempt_id,
            status="succeeded",
            semantic_outcome="valid_nonempty",
            actual_cost_usd=run.actual_charge_usd,
        )
        validation = self.ops.record_validation(
            validation_id,
            status="succeeded",
            semantic_outcome="valid_nonempty",
            attempt_id=attempt_id,
            cost_usd=run.actual_charge_usd,
            cost_final=bool(run.cost_final),
            duration_seconds=duration(),
            dataset_row_count=len(run.items),
            mapped_item_count=len(valid_items),
        )
        revision_id = str(validation["revision_id"])
        if bool(validation["cost_final"]):
            revision_id = self.ops.promote_compatibility_observation(
                validation_id,
                observed_fields=(
                    "identity",
                    "url",
                    "published_at",
                    "content",
                ),
                observed_build_id=slot.build_id,
                observed_build_number=slot.build_number,
            )
        return CanaryResult(
            validation_id=str(validation["validation_id"]),
            revision_id=revision_id,
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=(
                float(validation["cost_usd"])
                if validation["cost_usd"] is not None
                else None
            ),
        )

    async def reconcile(self, validation_id: str) -> CanaryResult:
        """Read one durable Run/Dataset again without issuing an Actor POST."""

        row = self.store.connect().execute(
            """
            SELECT validation.*, profile.route_key, profile.platform,
                   revision.candidate_id, revision.actor_id,
                   revision.publisher, revision.build_id,
                   revision.build_number, revision.manifest_json,
                   revision.manifest_hash, revision.lifecycle, revision.security_evidence_json,
                   candidate.state AS candidate_state
            FROM apify_actor_validations AS validation
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = validation.workspace_id
             AND profile.route_id = validation.route_id
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = validation.workspace_id
             AND revision.revision_id = validation.revision_id
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE validation.workspace_id = ?
              AND validation.validation_id = ?
            """,
            (self.ops.workspace_id, validation_id),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_validation_not_found",
                "Actor validation was not found",
                status_code=404,
            )
        if row["attempt_id"] is None or str(row["semantic_outcome"] or "") not in {
            "apify_run_status_unavailable",
            "apify_actor_run_status_unavailable",
            "apify_run_reconcile_required", "apify_worker_restart_reconcile_required",
        }:
            raise ActorOpsError(
                "apify_actor_validation_reconcile_not_allowed",
                "This validation does not need a free status reconciliation",
                status_code=409,
            )
        manifest = parse_actor_manifest(str(row["manifest_json"]))
        target = self._target_for(row)
        runtime = ActorRuntime(
            max_items=int(row["validation_sample_items"] or 1),
            until_iso=datetime.now(timezone.utc).isoformat(),
        )
        durable_run = self.store.connect().execute(
            """
            SELECT id
            FROM apify_actor_runs
            WHERE workspace_id = ? AND logical_run_id = ?
              AND remote_run_id IS NOT NULL
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (self.ops.workspace_id, str(row["attempt_id"])),
        ).fetchone()
        if durable_run is None:
            raise ActorOpsError(
                "apify_actor_validation_reconcile_unavailable",
                "The validation has no durable Apify Run to reconcile",
                status_code=412,
            )
        started = time.monotonic()
        try:
            run = await self.client.resume_actor_detailed(
                str(durable_run["id"]),
                dataset_item_limit=int(row["validation_sample_items"] or 1) + 1,
                reserved_cost_usd=float(row["approved_max_cost_usd"]),
            )
            mapped, observed_manifest = map_canary_output_for_revision(manifest, run.items, target, runtime, row)
            semantic = str(mapped.semantic_outcome)
        except ActorManifestError as exc:
            run_value = locals().get("run")
            items = list(run_value.items) if run_value is not None else []
            cost = run_value.actual_charge_usd if run_value is not None else None
            validation = self.ops.reconcile_validation_result(
                validation_id,
                semantic_outcome=str(exc.code),
                cost_usd=cost,
                cost_final=bool(run_value and run_value.cost_final),
                duration_seconds=max(0, int(round(time.monotonic() - started))),
                dataset_row_count=len(items),
                mapped_item_count=0,
            )
            raise ActorOpsError(
                str(exc.code),
                "Reconciled Actor output failed semantic validation",
                status_code=422,
            ) from None
        except (ApifyClientError, TimeoutError, ValueError) as exc:
            raise ActorOpsError(
                str(getattr(exc, "code", None) or "apify_run_status_unavailable"),
                "The existing Actor Run is still not readable",
                retryable=True,
                status_code=503,
            ) from None
        validation = self.ops.reconcile_validation_result(
            validation_id,
            semantic_outcome=semantic,
            cost_usd=run.actual_charge_usd,
            cost_final=bool(run.cost_final),
            duration_seconds=max(0, int(round(time.monotonic() - started))),
            dataset_row_count=len(run.items),
            mapped_item_count=len(mapped.items),
        )
        validation = settled_observed_validation(self.ops, validation, validation_id, observed_manifest)
        if (
            str(row["kind"]) == "route_reference"
            and str(validation["status"]) == "succeeded"
        ):
            self._advance_revision(str(validation["revision_id"]))
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
            staged = self._staged_source_context(row)
            if (
                binding is None
                or str(binding["route_id"]) != str(row["route_id"])
                or str(binding["target_fingerprint"])
                != str(row["target_fingerprint"] or "")
                or str(binding["target_fingerprint"]) != expected_fingerprint
                or int(binding["generation"])
                != int(row["approved_generation"] or -1)
                or (active is None and staged is None)
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
        if slot is not None:
            return str(slot["slot_name"])
        staged = self._staged_source_context(row)
        return str(staged["slot_name"]) if staged is not None else "primary"

    def _approval_still_authorized(self, row: Any) -> bool:
        lifecycle, state = map(str, (row["lifecycle"], row["candidate_state"]))
        if str(row["kind"]) == "route_reference":
            return route_reference_candidate_authorized(
                self.store.connect(), self.ops.workspace_id,
                str(row["revision_id"]), lifecycle, state,
            )
        staged = self._staged_source_context(row)
        if staged is not None:
            return lifecycle in {"probationary", "certified"} and state in {
                "closed", "half_open", "probationary", "disabled"
            }
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
        if slot is None:
            return False
        return source_canary_candidate_authorized(row)

    def _staged_source_context(self, row: Any) -> dict[str, Any] | None:
        if row["source_id"] is None:
            return None
        connection = self.store.connect()
        staged = connection.execute(
            """
            SELECT stage.stage_id, stage.route_id, stage.base_generation,
                   stage.base_pool_hash, stage.status,
                   source.binding_generation, source.target_fingerprint,
                   CASE
                     WHEN source.primary_validation_id = ? THEN 'primary'
                     WHEN source.backup_1_validation_id = ? THEN 'backup_1'
                     WHEN source.backup_2_validation_id = ? THEN 'backup_2'
                   END AS slot_name,
                   CASE
                     WHEN source.primary_validation_id = ?
                       THEN stage.target_primary_revision_id
                     WHEN source.backup_1_validation_id = ?
                       THEN stage.target_backup_1_revision_id
                     WHEN source.backup_2_validation_id = ?
                       THEN stage.target_backup_2_revision_id
                   END AS staged_revision_id
            FROM apify_actor_pool_stage_sources AS source
            JOIN apify_actor_pool_stages AS stage
              ON stage.workspace_id = source.workspace_id
             AND stage.stage_id = source.stage_id
            WHERE source.workspace_id = ? AND source.source_id = ?
              AND ? IN (
                  source.primary_validation_id,
                  source.backup_1_validation_id,
                  source.backup_2_validation_id
              )
              AND stage.status IN ('validating_sources', 'apply_ready')
            LIMIT 1
            """,
            (
                str(row["validation_id"]),
                str(row["validation_id"]),
                str(row["validation_id"]),
                str(row["validation_id"]),
                str(row["validation_id"]),
                str(row["validation_id"]),
                self.ops.workspace_id,
                str(row["source_id"]),
                str(row["validation_id"]),
            ),
        ).fetchone()
        if staged is None:
            return None
        active_rows = connection.execute(
            """
            SELECT slot_name, revision_id
            FROM apify_route_active_slots
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.ops.workspace_id, str(row["route_id"])),
        ).fetchall()
        active_hash = revision_set_hash(
            {
                str(active["slot_name"]): str(active["revision_id"] or "")
                for active in active_rows
            }
        )
        if (
            str(staged["route_id"]) != str(row["route_id"])
            or int(staged["base_generation"]) != int(row["route_generation"])
            or active_hash != str(staged["base_pool_hash"])
            or int(staged["binding_generation"]) != int(row["approved_generation"])
            or str(staged["target_fingerprint"])
            != str(row["target_fingerprint"] or "")
            or str(staged["staged_revision_id"] or "")
            != str(row["revision_id"])
            or not staged["slot_name"]
        ):
            return None
        return dict(staged)

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
    "reference_target_for_slot",
]
