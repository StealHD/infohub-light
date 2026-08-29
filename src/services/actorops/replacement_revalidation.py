"""Zero-start revalidation of paid replacement Datasets after rule upgrades."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from ..apify_actor_manifest import (
    ActorManifestError,
    actor_manifest_hash,
    parse_actor_manifest,
)
from .adapter_rows import prepare_adapter_rows
from .domain import CandidateLifecycle, ReplacementStatus
from .ports import ActorManifest, FetchWindow, ProbePreflightResult
from .probe_limits import PROBE_DATASET_VALIDATION_LIMIT
from .registry import AdapterNotRegistered, AdapterRegistry
from .replacement_contract_reason import output_contract_error_code
from .repository_errors import ActorOpsConflict


REVALIDATION_RULESET = "actorops-output-rules-x-time-v1"
_REVALIDATABLE = frozenset({
    "actorops_replacement_contract_mismatch",
    "actorops_replacement_published_at_invalid",
    "actorops_replacement_target_identity_mismatch",
    "actorops_replacement_output_url_invalid",
    "actorops_replacement_output_outside_window",
})


class DatasetReader(Protocol):
    async def read_dataset(
        self, dataset_id: str, *, max_items: int,
    ) -> tuple[dict[str, object], ...]: ...


class RevisionPreflight(Protocol):
    async def verify_candidate(
        self, candidate: object, *, max_charge_usd: float,
    ) -> ProbePreflightResult: ...


class ReplacementRevalidationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ReplacementRevalidationResult:
    plan: Any
    proof_count: int
    candidate_id: str


async def revalidate_failed_replacement(
    store: Any,
    repository: Any,
    registry: AdapterRegistry,
    reader: DatasetReader,
    preflight: RevisionPreflight,
    *,
    plan_id: str,
    expected_generation: int,
    idempotency_key: str,
    created_by_user_id: str,
) -> ReplacementRevalidationResult:
    """Revalidate settled Dataset rows without reopening or repricing history."""

    prior = repository.revalidation.plan_by_idempotency(idempotency_key)
    if prior is not None:
        return ReplacementRevalidationResult(prior, 0, prior.proposed_candidate_id)
    plan = repository.operator.get_plan(plan_id)
    if (
        plan.generation != expected_generation
        or plan.status is not ReplacementStatus.FAILED
        or plan.error_code not in _REVALIDATABLE
    ):
        raise ReplacementRevalidationError("actorops_revalidation_plan_ineligible")
    candidate = repository.get_candidate(plan.proposed_candidate_id)
    if (
        candidate.lifecycle is not CandidateLifecycle.REJECTED
        or candidate.last_error_code not in _REVALIDATABLE
    ):
        raise ReplacementRevalidationError("actorops_revalidation_candidate_ineligible")
    revision = await preflight.verify_candidate(
        candidate, max_charge_usd=plan.per_probe_cap_usd,
    )
    if not revision.allowed:
        raise ReplacementRevalidationError(
            "actorops_revalidation_revision_unavailable"
        )
    route = repository.get_route(plan.route_id)
    try:
        adapter = registry.require(route.route_key)
    except AdapterNotRegistered:
        raise ReplacementRevalidationError(
            "actorops_revalidation_adapter_unavailable"
        ) from None
    manifest = _manifest(candidate)
    bindings = set(repository.operator.binding_set(plan.route_id))
    origins = repository.revalidation.failed_dataset_attempts(plan)
    if not origins:
        raise ReplacementRevalidationError("actorops_revalidation_dataset_unavailable")
    validated: list[tuple[Any, str]] = []
    for origin in origins:
        binding = (
            str(origin["source_id"]), int(origin["binding_version"]),
            str(origin["target_fingerprint"]),
        )
        if binding not in bindings:
            raise ReplacementRevalidationError("actorops_revalidation_binding_changed")
        source = store.get_source(binding[0])
        config = source.get("config") if source else None
        if not isinstance(config, Mapping):
            raise ReplacementRevalidationError("actorops_revalidation_source_missing")
        try:
            target = adapter.normalize_target(config)
        except (KeyError, TypeError, ValueError):
            raise ReplacementRevalidationError(
                "actorops_revalidation_target_invalid"
            ) from None
        try:
            rows = await reader.read_dataset(
                str(origin["dataset_id"]),
                max_items=PROBE_DATASET_VALIDATION_LIMIT,
            )
        except Exception:
            raise ReplacementRevalidationError(
                "actorops_revalidation_dataset_unavailable"
            ) from None
        try:
            batch = adapter.validate_output(
                prepare_adapter_rows(adapter, rows, target, manifest),
                target, manifest, _window(origin),
            )
        except ActorManifestError as error:
            raise ReplacementRevalidationError(
                output_contract_error_code(error.code)
            ) from None
        except (TypeError, ValueError):
            raise ReplacementRevalidationError(
                "actorops_replacement_contract_mismatch"
            ) from None
        if batch.semantic_outcome not in {"valid_nonempty", "valid_empty"}:
            raise ReplacementRevalidationError("actorops_revalidation_no_evidence")
        if batch.semantic_outcome == "valid_empty" and not rows:
            raise ReplacementRevalidationError("actorops_revalidation_no_evidence")
        validated.append((origin, batch.semantic_outcome))
    new_plan_id = f"replacement-{uuid.uuid4().hex}"
    with repository.transaction():
        current_plan = repository.operator.get_plan(plan_id)
        current_candidate = repository.get_candidate(candidate.candidate_id)
        if (
            current_plan.generation != plan.generation
            or current_plan.status is not ReplacementStatus.FAILED
            or current_candidate.generation != candidate.generation
            or current_candidate.manifest_hash != candidate.manifest_hash
        ):
            raise ActorOpsConflict("replacement revalidation facts changed")
        for origin, semantic_outcome in validated:
            repository.revalidation.create_evidence(
                origin_attempt=origin,
                candidate_id=current_candidate.candidate_id,
                ruleset=REVALIDATION_RULESET,
                semantic_outcome=(
                    "valid_nonempty"
                    if semantic_outcome == "valid_nonempty"
                    else "no_evidence"
                ),
            )
        recovered = repository.revalidation.recover_candidate(
            current_candidate,
            proved=any(
                semantic_outcome == "valid_nonempty"
                for _origin, semantic_outcome in validated
            ),
        )
        next_plan = repository.operator.create_plan(
            plan_id=new_plan_id,
            route_id=plan.route_id,
            target_assignment=plan.target_assignment,
            target_priority=plan.target_priority,
            proposed_candidate_id=recovered.candidate_id,
            idempotency_key=idempotency_key,
            created_by_user_id=created_by_user_id,
            per_probe_cap_usd=plan.per_probe_cap_usd,
            total_cap_usd=plan.total_cap_usd,
        )
        if repository.operator.proofs_complete(next_plan):
            next_plan = repository.operator.transition_plan(
                next_plan.plan_id,
                current=ReplacementStatus.PREVIEWED,
                target=ReplacementStatus.READY,
                expected_generation=next_plan.generation,
            )
    return ReplacementRevalidationResult(
        next_plan, len(validated), recovered.candidate_id,
    )


def _manifest(candidate: Any) -> ActorManifest:
    parsed = parse_actor_manifest(str(candidate.manifest_json))
    if actor_manifest_hash(parsed) != candidate.manifest_hash:
        raise ReplacementRevalidationError("actorops_revalidation_revision_changed")
    return ActorManifest(
        candidate.actor_id, str(candidate.build_id), str(candidate.build_number),
        str(candidate.manifest_json), str(candidate.manifest_hash),
    )


def _window(row: Any) -> FetchWindow:
    return FetchWindow(
        max_items=int(row["max_items"]),
        since=datetime.fromisoformat(str(row["window_since"]).replace("Z", "+00:00")),
        until=(datetime.fromisoformat(str(row["window_until"]).replace("Z", "+00:00")) if row["window_until"] else None),
    )


__all__ = [
    "REVALIDATION_RULESET",
    "ReplacementRevalidationError",
    "ReplacementRevalidationResult",
    "revalidate_failed_replacement",
]
