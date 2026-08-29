"""Zero-start observed mapping for one already-paid replacement Dataset."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..apify_actor_manifest import (
    ActorManifestError,
    actor_manifest_hash,
    parse_actor_manifest,
)
from .adapter_rows import prepare_adapter_rows
from .discovery_manifest import validate_schema_proven_manifest
from .domain import CandidateLifecycle, ReplacementStatus
from .observed_dataset_schema import observed_dataset_schema
from .ports import (
    ActorManifest,
    DiscoveryAiMapper,
    DiscoveryMapping,
    DiscoveryRevision,
    FetchWindow,
)
from .registry import AdapterNotRegistered, AdapterRegistry
from .replacement_contract_reason import output_contract_error_code
from .probe_limits import PROBE_DATASET_VALIDATION_LIMIT
from .repository_errors import ActorOpsConflict


ADAPTABLE_OUTPUT_CODES = frozenset({
    "actorops_replacement_contract_mismatch",
    "actorops_replacement_published_at_invalid",
    "actorops_replacement_target_identity_mismatch",
    "actorops_replacement_output_url_invalid",
    "actorops_replacement_output_outside_window",
    "actorops_replacement_nested_extraction_failed",
    "actorops_replacement_mixed_rows_unclassified",
    "actorops_replacement_dataset_expansion_overflow",
    "actorops_replacement_observed_mapping_required",
    "actorops_replacement_sample_dataset_empty",
})
OBSERVED_MAPPING_RULESET = "actorops-observed-dataset-mapping-v1"


@dataclass(frozen=True, slots=True)
class DatasetAdaptationResult:
    status: str
    error_code: str | None = None
    candidate_id: str | None = None
    proof_count: int = 0


class DatasetAdaptationService:
    def __init__(
        self, repository: Any, registry: AdapterRegistry, catalog: Any,
        dataset_reader: Any, *, ai_mapper: DiscoveryAiMapper | None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.catalog = catalog
        self.dataset_reader = dataset_reader
        self.ai_mapper = ai_mapper

    async def adapt(
        self, plan_id: str, sources: Mapping[str, Mapping[str, object]],
        *, cached_rows: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    ) -> DatasetAdaptationResult:
        plan = self.repository.operator.get_plan(plan_id)
        if plan.status is not ReplacementStatus.RUNNING:
            return DatasetAdaptationResult(
                "blocked", "actorops_replacement_adaptation_plan_ineligible"
            )
        origin = self.repository.get_candidate(plan.proposed_candidate_id)
        attempts = tuple(
            row
            for row in self.repository.adaptation.plan_attempts(
                plan, origin.candidate_id
            )
            if (
                str(row["status"]) == "succeeded"
                and str(row["semantic_outcome"] or "") == "valid_nonempty"
            )
            or (
                str(row["status"]) == "failed"
                and str(row["error_code"] or "") in ADAPTABLE_OUTPUT_CODES
            )
        )
        failed = tuple(
            row for row in attempts
            if str(row["status"]) == "failed"
            and str(row["error_code"] or "") in ADAPTABLE_OUTPUT_CODES
        )
        if not failed:
            return DatasetAdaptationResult("not_required")
        if any(not bool(row["cost_final"]) for row in failed):
            return DatasetAdaptationResult(
                "cost_reconciliation", "actorops_replacement_cost_pending"
            )
        if any(not row["dataset_id"] for row in failed):
            return await self._pending(
                plan, "actorops_replacement_dataset_run_unbound"
            )
        try:
            route = self.repository.get_route(plan.route_id)
            adapter = self.registry.require(route.route_key)
            if (
                not callable(getattr(adapter, "map_discovery_manifest", None))
                or not callable(getattr(self.catalog, "get_revision", None))
            ):
                return DatasetAdaptationResult("not_required")
            try:
                revision = await self.catalog.get_revision(origin.actor_id)
            except Exception as error:
                raise DatasetAdaptationFailure(
                    "actorops_replacement_revision_unavailable"
                ) from error
            self._assert_revision(origin, revision)
            failed_rows = await self._rows(failed[0], cached_rows)
            if not failed_rows:
                raise DatasetAdaptationFailure(
                    "actorops_replacement_sample_dataset_empty"
                )
            target = self._target(adapter, sources, failed[0])
            manifest_json = await self._find_manifest(
                adapter, route.route_key, revision, failed_rows,
                target, _window(failed[0]), origin,
            )
            if manifest_json is None:
                return await self._pending(
                    plan, "actorops_replacement_observed_mapping_failed"
                )
            manifest = _manifest(origin, manifest_json)
            validated = await self._validate_attempts(
                attempts, sources, adapter, manifest, cached_rows
            )
        except AdapterNotRegistered:
            return await self._pending(
                plan, "actorops_replacement_adapter_unavailable"
            )
        except DatasetAdaptationFailure as error:
            return await self._pending(plan, error.code)
        manifest_hash = actor_manifest_hash(parse_actor_manifest(manifest_json))
        try:
            with self.repository.transaction():
                current_plan = self.repository.operator.get_plan(plan.plan_id)
                current_origin = self.repository.get_candidate(origin.candidate_id)
                if (
                    current_plan.generation != plan.generation
                    or current_origin.generation != origin.generation
                    or current_plan.proposed_candidate_id != origin.candidate_id
                ):
                    raise ActorOpsConflict("adaptation facts changed")
                successor = self.repository.adaptation.persist_successor(
                    current_origin, manifest_json=manifest_json,
                    manifest_hash=manifest_hash,
                )
                for row, semantic_outcome in validated:
                    self.repository.revalidation.create_evidence(
                        origin_attempt=row, candidate_id=successor.candidate_id,
                        ruleset=OBSERVED_MAPPING_RULESET,
                        semantic_outcome=semantic_outcome,
                    )
                successor = self._promote(successor)
                self.repository.adaptation.mark_origin_superseded(current_origin)
                self.repository.adaptation.retarget_plan(
                    current_plan, current_origin, successor
                )
        except ActorOpsConflict:
            return DatasetAdaptationResult(
                "blocked", "actorops_replacement_plan_stale"
            )
        return DatasetAdaptationResult(
            "revalidated", candidate_id=successor.candidate_id,
            proof_count=len(validated),
        )

    async def _find_manifest(
        self, adapter: Any, route_key: Any, revision: DiscoveryRevision,
        rows: Sequence[Mapping[str, object]], target: Any, window: FetchWindow,
        candidate: Any,
    ) -> str | None:
        observed = observed_dataset_schema(rows)
        feedback: str | None = None
        observed_revision = _observed_revision(revision, observed)
        manifest_json, error = self._validate_proposal(
            adapter.map_discovery_manifest(observed_revision),
            observed_revision, rows, adapter, target, window, candidate,
        )
        if manifest_json:
            return manifest_json
        feedback = _feedback(error)
        for _round_index in range(2):
            if self.ai_mapper is None:
                break
            observed_revision = _observed_revision(
                revision, observed, feedback=feedback
            )
            try:
                result = await self.ai_mapper.map(route_key, (observed_revision,))
                proposal = result.mappings.get(
                    revision.actor_id,
                    DiscoveryMapping(
                        None, "actorops_discovery_ai_mapping_missing"
                    ),
                )
            except Exception:
                feedback = "observed_mapping_failed"
                continue
            manifest_json, error = self._validate_proposal(
                proposal, observed_revision, rows,
                adapter, target, window, candidate,
            )
            if manifest_json:
                return manifest_json
            feedback = _feedback(error)
        return None

    def _validate_proposal(
        self, mapping: DiscoveryMapping, revision: DiscoveryRevision,
        rows: Sequence[Mapping[str, object]], adapter: Any, target: Any,
        window: FetchWindow, candidate: Any,
    ) -> tuple[str | None, str | None]:
        manifest_json, error = validate_schema_proven_manifest(revision, mapping)
        if not manifest_json:
            return None, error
        try:
            batch = adapter.validate_output(
                prepare_adapter_rows(
                    adapter, rows, target, _manifest(candidate, manifest_json)
                ),
                target, _manifest(candidate, manifest_json), window,
            )
        except ActorManifestError as failure:
            return None, output_contract_error_code(failure.code)
        except (TypeError, ValueError):
            return None, "actorops_replacement_contract_mismatch"
        return (
            (manifest_json, None)
            if batch.semantic_outcome == "valid_nonempty"
            else (None, "actorops_replacement_observed_mapping_failed")
        )

    async def _validate_attempts(
        self, attempts: Sequence[Any], sources: Mapping[str, Mapping[str, object]],
        adapter: Any, manifest: ActorManifest,
        cached_rows: Mapping[str, Sequence[Mapping[str, object]]] | None,
    ) -> list[tuple[Any, str]]:
        output: list[tuple[Any, str]] = []
        for row in attempts:
            if not bool(row["cost_final"]):
                raise DatasetAdaptationFailure(
                    "actorops_replacement_cost_pending"
                )
            if not row["dataset_id"]:
                raise DatasetAdaptationFailure(
                    "actorops_replacement_dataset_run_unbound"
                )
            rows = await self._rows(row, cached_rows)
            target = self._target(adapter, sources, row)
            try:
                batch = adapter.validate_output(
                    prepare_adapter_rows(adapter, rows, target, manifest),
                    target, manifest, _window(row),
                )
            except ActorManifestError as error:
                raise DatasetAdaptationFailure(
                    output_contract_error_code(error.code)
                ) from None
            if batch.semantic_outcome != "valid_nonempty":
                raise DatasetAdaptationFailure(
                    "actorops_replacement_observed_mapping_failed"
                )
            output.append((row, "valid_nonempty"))
        return output

    async def _rows(
        self, row: Any,
        cached: Mapping[str, Sequence[Mapping[str, object]]] | None,
    ) -> tuple[Mapping[str, object], ...]:
        attempt_id = str(row["attempt_id"])
        if cached and attempt_id in cached:
            return tuple(cached[attempt_id])
        try:
            values = await self.dataset_reader.read_dataset(
                str(row["dataset_id"]),
                max_items=PROBE_DATASET_VALIDATION_LIMIT,
            )
        except Exception:
            raise DatasetAdaptationFailure(
                "actorops_replacement_dataset_unavailable"
            ) from None
        return tuple(values)

    @staticmethod
    def _target(adapter: Any, sources: Mapping[str, Mapping[str, object]], row: Any) -> Any:
        source = sources.get(str(row["source_id"]))
        if not isinstance(source, Mapping):
            raise DatasetAdaptationFailure(
                "actorops_replacement_source_missing"
            )
        try:
            return adapter.normalize_target(source)
        except (KeyError, TypeError, ValueError):
            raise DatasetAdaptationFailure(
                "actorops_replacement_target_invalid"
            ) from None

    @staticmethod
    def _assert_revision(candidate: Any, revision: DiscoveryRevision) -> None:
        if (
            revision.actor_id != candidate.actor_id
            or revision.publisher != candidate.publisher
            or revision.build_id != candidate.build_id
            or revision.build_number != candidate.build_number
            or _hash(revision.input_schema) != candidate.input_schema_hash
            or _hash(revision.output_schema) != candidate.output_schema_hash
        ):
            raise DatasetAdaptationFailure(
                "actorops_replacement_revision_changed"
            )

    async def _pending(self, plan: Any, code: str) -> DatasetAdaptationResult:
        try:
            with self.repository.transaction():
                current = self.repository.operator.get_plan(plan.plan_id)
                if current.status is ReplacementStatus.RUNNING:
                    if code == "actorops_replacement_cost_pending":
                        self.repository.operator.note_plan(
                            current.plan_id, status=current.status,
                            expected_generation=current.generation,
                            error_code=code,
                        )
                    else:
                        self.repository.operator.transition_plan(
                            current.plan_id,
                            current=current.status,
                            target=ReplacementStatus.FAILED,
                            expected_generation=current.generation,
                            error_code=code,
                        )
        except ActorOpsConflict:
            pass
        if code == "actorops_replacement_cost_pending":
            return DatasetAdaptationResult("cost_reconciliation", code)
        return DatasetAdaptationResult("adaptation_failed", code)

    def _promote(self, candidate: Any) -> Any:
        current = self.repository.record_candidate_outcome(
            candidate.candidate_id, expected_generation=candidate.generation,
            succeeded=True,
        )
        if current.lifecycle is CandidateLifecycle.STATIC_VALID:
            current = self.repository.transition_candidate(
                current.candidate_id, current.lifecycle,
                CandidateLifecycle.PROBATIONARY,
                expected_generation=current.generation,
            )
        return current


class DatasetAdaptationFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _observed_revision(
    revision: DiscoveryRevision, schema: Mapping[str, object],
    *, feedback: str | None = None,
) -> DiscoveryRevision:
    return DiscoveryRevision(
        actor_id=revision.actor_id, publisher=revision.publisher,
        build_id=revision.build_id, build_number=revision.build_number,
        price_per_run_usd=revision.price_per_run_usd,
        input_schema=revision.input_schema, output_schema=schema,
        mapping_feedback=feedback,
    )


def _manifest(candidate: Any, manifest_json: str) -> ActorManifest:
    parsed = parse_actor_manifest(manifest_json)
    return ActorManifest(
        candidate.actor_id, str(candidate.build_id),
        str(candidate.build_number), manifest_json,
        actor_manifest_hash(parsed),
    )


def _window(row: Any) -> FetchWindow:
    return FetchWindow(
        max_items=int(row["max_items"]),
        since=datetime.fromisoformat(str(row["window_since"]).replace("Z", "+00:00")),
        until=(
            datetime.fromisoformat(str(row["window_until"]).replace("Z", "+00:00"))
            if row["window_until"] else None
        ),
    )


def _feedback(code: str | None) -> str:
    value = str(code or "observed_mapping_failed")
    prefix = "actorops_discovery_ai_"
    safe = value.removeprefix(prefix) if value.startswith(prefix) else ""
    return safe if safe in {
        "nested_extraction_failed", "mixed_rows_unclassified",
        "dataset_expansion_overflow", "observed_mapping_failed",
    } else "observed_mapping_failed"


def _hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
__all__ = ["ADAPTABLE_OUTPUT_CODES", "DatasetAdaptationResult", "DatasetAdaptationService", "OBSERVED_MAPPING_RULESET"]
