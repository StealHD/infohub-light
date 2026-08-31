"""Recoverable, platform-neutral ActorOps v2 Discovery orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from .input_plan import input_plan_hash
from .candidate_identity import candidate_id
from .compatibility_projection import candidate_compatibility
from .discovery_manifest import validate_schema_proven_manifest
from .discovery_mapping_repair import repair_mapping_proposal
from .discovery_route_type import store_match_is_wrong_type
from .discovery_ai_individual import resolve_ranked_candidates
from .discovery_search import (
    candidate_quality_key,
    cursor_match,
    match_cursor,
    ranked_catalog_matches,
)
from .domain import CandidateLifecycle, DiscoveryStage, DiscoveryStatus, FailureClass
from .ports import DiscoveryAiMapper, DiscoveryCatalog, DiscoveryMapping, DiscoveryRevision
from .presentation_mapping import (
    CandidatePresentationMappings,
    avatar_pointer_from_schema,
)
from .registry import AdapterRegistry
from .repository import ActorOpsRepository
from .repository_errors import ActorOpsNotFound


_MAX_ROUTE_CANDIDATES = 5
_MAX_REVISION_CHECKS = 20
_MAX_AI_MAPPINGS = 20
_MAX_CURSOR_BYTES = 16 * 1024
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{1,95}$")


class DiscoveryCatalogError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code if _SAFE_CODE.fullmatch(code) else "actorops_discovery_catalog_unavailable"
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    discovery_id: str
    status: str
    stage: str
    idempotent_replay: bool = False


class ActorOpsDiscovery:
    """Persist every stage boundary without owning SQL, secrets, or Jobs."""

    def __init__(
        self,
        repository: ActorOpsRepository,
        registry: AdapterRegistry,
        catalog: DiscoveryCatalog,
        *,
        ai_mapper: DiscoveryAiMapper | None = None,
        retry_delay_seconds: int = 30,
        now: callable | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.catalog = catalog
        self.ai_mapper = ai_mapper
        self.retry_delay_seconds = max(int(retry_delay_seconds), 0)
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def run(self, discovery_id: str) -> DiscoveryResult:
        progressed = False
        while True:
            row = self.repository.discovery.get(discovery_id)
            if str(row["status"]) in _TERMINAL:
                return DiscoveryResult(
                    discovery_id, str(row["status"]), str(row["stage"]), not progressed
                )
            if str(row["status"]) == DiscoveryStatus.RETRY_WAIT.value:
                if self._retry_after(row) > self.now().astimezone(timezone.utc):
                    return DiscoveryResult(discovery_id, "retry_wait", str(row["stage"]))
                self._checkpoint(row, status=DiscoveryStatus.RUNNING, stage=self._stage(row))
                continue
            if str(row["status"]) == DiscoveryStatus.QUEUED.value:
                self._checkpoint(row, status=DiscoveryStatus.RUNNING, stage=self._stage(row))
                continue
            try:
                progressed = True
                route = self.repository.get_route(str(row["route_id"]))
                adapter = self.registry.require(route.route_key)
                stage = self._stage(row)
                if stage is DiscoveryStage.STORE_SEARCH:
                    await self._store_search(row, adapter)
                elif stage is DiscoveryStage.METADATA:
                    await self._metadata(row)
                elif stage is DiscoveryStage.VALIDATION:
                    await self._validation(row, route.per_run_cap_usd)
                elif stage is DiscoveryStage.MAPPING:
                    await self._mapping(row, adapter, route.route_key)
                elif stage is DiscoveryStage.RANKING:
                    self._ranking(row)
                else:
                    self._persist(row)
            except DiscoveryCatalogError as error:
                if error.retryable:
                    self._retry(row, error.code)
                    return DiscoveryResult(discovery_id, "retry_wait", str(row["stage"]))
                self._fail(row, error.code, FailureClass.CONFIGURATION)
                return DiscoveryResult(discovery_id, "failed", str(row["stage"]))
            except Exception:
                self._fail(row, "actorops_discovery_internal", FailureClass.INTERNAL)
                return DiscoveryResult(discovery_id, "failed", str(row["stage"]))

    async def _store_search(self, row: Any, adapter: Any) -> None:
        spec = adapter.discovery_spec()
        groups = [await self.catalog.search(query) for query in spec.queries]
        all_matches = ranked_catalog_matches(groups, limit=80)
        eligible = tuple(
            match for match in all_matches
            if not store_match_is_wrong_type(adapter.route_key.platform, match)
        )
        matches = eligible[:_MAX_REVISION_CHECKS]
        cursor = self._cursor(
            "metadata",
            matches=[
                match_cursor(match, rank=rank)
                for rank, match in enumerate(matches)
            ],
            metrics={
                "marketplace_hits": len(all_matches),
                "revision_checks": len(matches),
                "wrong_actor_type": len(all_matches) - len(eligible),
            },
        )
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.METADATA,
            cursor=cursor, query_count=len(spec.queries),
        )

    async def _metadata(self, row: Any) -> None:
        state = self._read_cursor(row, "metadata")
        raw_matches = state.get("matches")
        if not isinstance(raw_matches, list):
            raw_matches = [
                {"actor_id": actor_id, "catalog_rank": rank}
                for rank, actor_id in enumerate(state.get("actor_ids", []))
            ]
        refs = []
        for rank, raw_match in enumerate(raw_matches):
            match = cursor_match(raw_match)
            if match is None:
                continue
            revision = await self.catalog.get_revision(match.actor_id)
            stored_rank = (
                raw_match.get("catalog_rank", rank)
                if isinstance(raw_match, dict)
                else rank
            )
            refs.append({
                **self._revision_ref(revision),
                "total_users": match.total_users,
                "rating": match.rating,
                "review_count": match.review_count,
                "bookmark_count": match.bookmark_count,
                "query_hits": match.query_hits,
                "catalog_rank": int(stored_rank),
            })
        refs.sort(key=candidate_quality_key)
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.VALIDATION,
            cursor=self._cursor(
                "validation", refs=refs, rejections=[],
                metrics=dict(state.get("metrics") or {}),
            ),
        )

    async def _validation(self, row: Any, cap: float) -> None:
        state = self._read_cursor(row, "validation")
        valid, rejected = [], list(state.get("rejections", []))
        for raw_ref in state["refs"]:
            # Validation can reject an exact revision before mapping.  Keep
            # the Route scope needed for a deterministic Candidate/rejection
            # ID, while comparing the public revision without that scope.
            ref = {**raw_ref, "route_id": str(row["route_id"])}
            revision = await self.catalog.get_revision(str(ref["actor_id"]))
            if self._revision_identity(
                self._revision_ref(revision)
            ) != self._revision_identity(ref):
                rejected.append(self._rejection(ref, "actorops_discovery_revision_changed"))
            elif not self._valid_revision(revision, cap):
                rejected.append(self._rejection(ref, "actorops_discovery_validation_rejected"))
            else:
                valid.append(ref)
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.MAPPING,
            cursor=self._cursor(
                "mapping", refs=valid, rejections=rejected,
                metrics={
                    **dict(state.get("metrics") or {}),
                    "preflight_blocked": len(rejected),
                },
            ),
            rejection_count=len(rejected),
        )

    async def _mapping(self, row: Any, adapter: Any, route_key: Any) -> None:
        state = self._read_cursor(row, "mapping")
        descriptors, unresolved = [], []
        for raw_ref in state["refs"]:
            ref = {**raw_ref, "route_id": str(row["route_id"])}
            revision = await self.catalog.get_revision(str(ref["actor_id"]))
            if self._revision_identity(
                self._revision_ref(revision)
            ) != self._revision_identity(ref):
                descriptors.append(self._rejection(ref, "actorops_discovery_revision_changed"))
                continue
            if not _usable_output_schema(revision.output_schema):
                mapper = getattr(adapter, "map_discovery_input_plan", None)
                if not callable(mapper):
                    descriptors.append(self._pending(
                        ref, "actorops_discovery_input_plan_invalid"
                    ))
                    continue
                plan_json, error_code = mapper(revision)
                if plan_json:
                    descriptors.append(self._sample_required(ref, plan_json))
                else:
                    descriptors.append(self._pending(
                        ref, error_code or "actorops_discovery_input_plan_invalid"
                    ))
                continue
            cached = self.repository.discovery.cached_manifest(
                route_id=str(row["route_id"]),
                actor_id=revision.actor_id,
                build_id=revision.build_id,
                build_number=revision.build_number,
                input_schema_hash=str(ref["input_schema_hash"]),
                output_schema_hash=str(ref["output_schema_hash"]),
            )
            if cached is not None:
                cached_item = self._mapped(
                    ref, DiscoveryMapping(cached), revision,
                    route_key=route_key,
                )
                if cached_item["status"] == "accepted":
                    descriptors.append(cached_item)
                    continue
                with self.repository.transaction():
                    self.repository.discovery.reject_invalid_static_mapping(
                        route_id=str(row["route_id"]),
                        actor_id=revision.actor_id,
                        build_id=revision.build_id,
                        build_number=revision.build_number,
                        input_schema_hash=str(ref["input_schema_hash"]),
                        output_schema_hash=str(ref["output_schema_hash"]),
                        error_code=str(cached_item["rejection_code"]),
                    )
            mapping = adapter.map_discovery_manifest(revision)
            if mapping.manifest_json is None:
                unresolved.append((revision, ref))
            else:
                deterministic = self._mapped(
                    ref, mapping, revision, route_key=route_key
                )
                if deterministic["status"] == "accepted":
                    descriptors.append(deterministic)
                else:
                    # A heuristic mapping is only a proposal.  When strict
                    # schema/semantic proof rejects it, let the bounded AI
                    # mapper inspect the exact Build instead of stranding a
                    # potentially compatible Actor as mapping_pending.
                    unresolved.append((revision, ref))
        descriptors, metrics = await resolve_ranked_candidates(
            self.ai_mapper,
            route_key,
            unresolved,
            descriptors,
            map_mapping=lambda ref, mapping, revision: self._mapped(
                ref, mapping, revision, route_key=route_key
            ),
            pending=self._pending,
            max_mappings=_MAX_AI_MAPPINGS,
            max_route_candidates=_MAX_ROUTE_CANDIDATES,
        )
        descriptors.extend(
            {**dict(value), "route_id": str(row["route_id"])}
            for value in state.get("rejections", [])
        )
        descriptors = self._ranked(self._unique(descriptors))
        discovery_metrics = {
            **dict(state.get("metrics") or {}),
            "wrong_actor_type": int(
                dict(state.get("metrics") or {}).get("wrong_actor_type") or 0
            ) + sum(
                item.get("rejection_code") == "actorops_discovery_ai_wrong_actor_type"
                for item in descriptors
            ),
            "route_relevant": sum(_route_candidate(item) for item in descriptors),
            "static_ready": sum(item.get("status") == "accepted" for item in descriptors),
            "sample_required": sum(
                item.get("rejection_code")
                == "actorops_discovery_output_sample_required"
                for item in descriptors
            ),
            "system_usable": 0,
        }
        with self.repository.transaction():
            for item in descriptors:
                self._ensure_candidate(str(row["route_id"]), item)
            usable_ids = {
                str(item["candidate_id"])
                for item in descriptors
                if _route_candidate(item)
                and bool(candidate_compatibility(
                    self.repository,
                    self.repository.get_candidate(str(item["candidate_id"])),
                )["system_usable"])
            }
            discovery_metrics["system_usable"] = len(usable_ids)
            discovery_metrics["static_ready"] = sum(
                item.get("status") == "accepted"
                and str(item["candidate_id"]) not in usable_ids
                for item in descriptors
            )
            self._checkpoint(
                row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.RANKING,
                cursor=self._cursor(
                    "ranking",
                    candidates=[self._cursor_candidate(item) for item in descriptors],
                    metrics=discovery_metrics,
                ),
                candidate_count=len(descriptors),
                rejection_count=sum(item["status"] == "rejected" for item in descriptors),
                ai_metrics=metrics,
            )

    def _ranking(self, row: Any) -> None:
        state = self._read_cursor(row, "ranking")
        candidates = [dict(item) for item in state["candidates"]]
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.PERSIST,
            cursor=self._cursor(
                "persist", candidates=candidates,
                metrics=dict(state.get("metrics") or {}),
            ),
        )

    def _persist(self, row: Any) -> None:
        state = self._read_cursor(row, "persist")
        with self.repository.transaction():
            for item in state["candidates"]:
                self.repository.discovery.link_candidate(
                    str(row["discovery_id"]), candidate_id=str(item["candidate_id"]),
                    rank=int(item["rank"]), status=str(item["status"]),
                    rejection_code=item.get("rejection_code"),
                )
            self._checkpoint(
                row, status=DiscoveryStatus.COMPLETED, stage=DiscoveryStage.PERSIST,
                cursor=self._cursor(
                    "persist", candidates=state["candidates"],
                    metrics=dict(state.get("metrics") or {}),
                ),
                candidate_count=len(state["candidates"]),
                rejection_count=sum(item["status"] == "rejected" for item in state["candidates"]),
            )

    def _ensure_candidate(self, route_id: str, item: dict[str, object]) -> None:
        try:
            existing = self.repository.get_candidate(str(item["candidate_id"]))
        except ActorOpsNotFound:
            created = self.repository.create_candidate(
                candidate_id=str(item["candidate_id"]), route_id=route_id,
                actor_id=str(item["actor_id"]), publisher=str(item["publisher"]),
                build_id=str(item["build_id"]), build_number=str(item["build_number"]),
                manifest_json=item.get("manifest_json"), manifest_hash=item.get("manifest_hash"),
                input_schema_hash=str(item["input_schema_hash"]),
                output_schema_hash=str(item["output_schema_hash"]),
                lifecycle=CandidateLifecycle.DISCOVERED,
            )
            target = {
                "accepted": CandidateLifecycle.STATIC_VALID,
                "pending": CandidateLifecycle.MAPPING_PENDING,
                "rejected": CandidateLifecycle.REJECTED,
            }[str(item["status"])]
            stored = self.repository.transition_candidate(
                created.candidate_id, CandidateLifecycle.DISCOVERED, target,
                expected_generation=created.generation,
                error_class=(FailureClass.CANDIDATE.value if target is CandidateLifecycle.REJECTED else None),
                error_code=item.get("rejection_code"),
            )
            self._supersede_pending_mapping(route_id, stored, item)
            self._persist_sampling_plan(stored, item)
            self._refresh_presentation(stored, item)
            return
        if existing.route_id != route_id or existing.actor_id != item["actor_id"]:
            raise ValueError("actorops discovery candidate identity collision")
        if (
            item.get("status") == "pending"
            and isinstance(item.get("rejection_code"), str)
        ):
            self.repository.discovery.refresh_pending_mapping_issue(
                existing.candidate_id, str(item["rejection_code"])
            )

        self._supersede_pending_mapping(route_id, existing, item)
        self._persist_sampling_plan(existing, item)
        self._refresh_presentation(existing, item)

    def _persist_sampling_plan(
        self, candidate: object, item: dict[str, object]
    ) -> None:
        value = item.get("input_plan_json")
        if isinstance(value, str):
            self.repository.sampling.upsert_ready(candidate, value)

    def _supersede_pending_mapping(
        self, route_id: str, candidate: object, item: dict[str, object]
    ) -> None:
        if item.get("status") != "accepted":
            return
        self.repository.discovery.supersede_pending_mapping(
            route_id=route_id,
            actor_id=str(item["actor_id"]),
            build_id=str(item["build_id"]),
            build_number=str(item["build_number"]),
            input_schema_hash=str(item["input_schema_hash"]),
            output_schema_hash=str(item["output_schema_hash"]),
            keep_candidate_id=str(getattr(candidate, "candidate_id")),
        )

    def _mapped(
        self,
        ref: dict[str, object],
        mapping: DiscoveryMapping | None,
        revision: DiscoveryRevision,
        *,
        route_key: object,
    ) -> dict[str, object]:
        mapping = repair_mapping_proposal(route_key, revision, mapping)
        manifest_json, error_code = validate_schema_proven_manifest(
            revision, mapping
        )
        if not manifest_json:
            return self._pending(
                ref, error_code or "actorops_discovery_mapping_pending"
            )
        # Candidate persistence and execution must agree on the exact canonical
        # Manifest identity; hashing the pre-parse JSON here would make a
        # schema-proven Candidate fail before its first paid Probe.
        manifest_hash = actor_manifest_hash(parse_actor_manifest(manifest_json))
        return {
            **ref,
            "candidate_id": self._candidate_id(ref, manifest_hash),
            "manifest_json": manifest_json,
            "manifest_hash": manifest_hash,
            "avatar_json_pointer": avatar_pointer_from_schema(
                revision.output_schema, str(getattr(route_key, "platform", ""))
            ),
            "status": "accepted",
            "rejection_code": None,
        }

    def _refresh_presentation(
        self, candidate: object, item: dict[str, object]
    ) -> None:
        if item.get("status") != "accepted":
            return
        try:
            mappings = CandidatePresentationMappings(self.repository)
            manifest_mapping = mappings.import_manifest(candidate)
            if manifest_mapping.status == "ready":
                return
            mappings.refresh_pointer(
                candidate,
                item.get("avatar_json_pointer"),
                evidence_kind="schema",
            )
        except Exception:
            # The sidecar is presentation-only; deterministic core discovery
            # remains valid when this optional evidence cannot be refreshed.
            return

    def _pending(
        self,
        ref: dict[str, object],
        code: str = "actorops_discovery_mapping_pending",
    ) -> dict[str, object]:
        return {
            **ref, "candidate_id": self._candidate_id(ref, "mapping_pending"),
            "manifest_json": None, "manifest_hash": None, "status": "pending",
            "rejection_code": code,
        }

    def _sample_required(
        self, ref: dict[str, object], input_plan_json: str
    ) -> dict[str, object]:
        digest = input_plan_hash(input_plan_json)
        return {
            **ref,
            "candidate_id": self._candidate_id(ref, f"input_plan:{digest}"),
            "manifest_json": None,
            "manifest_hash": None,
            "input_plan_json": input_plan_json,
            "input_plan_hash": digest,
            "status": "pending",
            "rejection_code": "actorops_discovery_output_sample_required",
        }

    def _rejection(self, ref: dict[str, object], code: str) -> dict[str, object]:
        return {
            **ref, "candidate_id": self._candidate_id(ref, f"rejected:{code}"),
            "manifest_json": None, "manifest_hash": None, "status": "rejected",
            "rejection_code": code,
        }

    def _checkpoint(self, row: Any, *, status: DiscoveryStatus, stage: DiscoveryStage, cursor: str | None = None, query_count: int | None = None, candidate_count: int | None = None, rejection_count: int | None = None, retry_after: str | None = None, failure_class: FailureClass | None = None, error_code: str | None = None, ai_metrics: dict[str, object] | None = None) -> None:
        values = {
            "expected_status": DiscoveryStatus(str(row["status"])),
            "expected_stage": self._stage(row),
            "expected_generation": int(row["generation"]), "status": status,
            "stage": stage, "checkpoint_hash": self._hash(cursor) if cursor else None,
            "search_cursor": cursor,
            "query_count": int(row["query_count"]) if query_count is None else query_count,
            "candidate_count": int(row["candidate_count"]) if candidate_count is None else candidate_count,
            "rejection_count": int(row["rejection_count"]) if rejection_count is None else rejection_count,
            "retry_after": retry_after,
            "failure_class": failure_class.value if failure_class else None,
            "error_code": error_code, "ai_metrics": ai_metrics,
        }
        if self.repository.connection.in_transaction:
            self.repository.discovery.checkpoint(str(row["discovery_id"]), **values)
            self._wake_terminal_repair(row, status)
            return
        with self.repository.transaction():
            self.repository.discovery.checkpoint(str(row["discovery_id"]), **values)
            self._wake_terminal_repair(row, status)

    def _wake_terminal_repair(
        self, row: Any, status: DiscoveryStatus
    ) -> None:
        if status in {
            DiscoveryStatus.COMPLETED,
            DiscoveryStatus.FAILED,
            DiscoveryStatus.CANCELLED,
        }:
            self.repository.resilience.wake_repairs_after_discovery(
                str(row["discovery_id"])
            )

    def _retry(self, row: Any, code: str) -> None:
        retry_after = self.now().astimezone(timezone.utc) + timedelta(seconds=self.retry_delay_seconds)
        self._checkpoint(row, status=DiscoveryStatus.RETRY_WAIT, stage=self._stage(row), retry_after=retry_after.isoformat(), failure_class=FailureClass.INTERNAL, error_code=code)

    def _fail(self, row: Any, code: str, failure_class: FailureClass) -> None:
        self._checkpoint(row, status=DiscoveryStatus.FAILED, stage=self._stage(row), failure_class=failure_class, error_code=code)

    @staticmethod
    def _stage(row: Any) -> DiscoveryStage:
        return DiscoveryStage(str(row["stage"]))

    @staticmethod
    def _revision_ref(revision: DiscoveryRevision) -> dict[str, object]:
        return {
            "actor_id": revision.actor_id, "publisher": revision.publisher,
            "build_id": revision.build_id, "build_number": revision.build_number,
            "price_per_run_usd": revision.price_per_run_usd,
            "account_fit_rank": revision.account_fit_rank,
            "account_fit_reason": revision.account_fit_reason,
            "input_schema_hash": ActorOpsDiscovery._hash_value(revision.input_schema),
            "output_schema_hash": ActorOpsDiscovery._hash_value(revision.output_schema),
        }

    @staticmethod
    def _valid_revision(revision: DiscoveryRevision, cap: float) -> bool:
        return bool(
            revision.actor_id and revision.publisher and revision.build_id
            and revision.build_number and revision.input_schema
            and isinstance(revision.price_per_run_usd, (int, float))
            and 0 <= float(revision.price_per_run_usd) <= cap
        )

    @staticmethod
    def _candidate_id(ref: dict[str, object], manifest: str) -> str:
        return candidate_id(
            route_id=str(ref["route_id"]), actor_id=str(ref["actor_id"]),
            build_id=str(ref["build_id"]),
            build_number=str(ref["build_number"]),
            manifest_identity=manifest,
        )

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_value(value: object) -> str:
        return ActorOpsDiscovery._hash(json.dumps(value, sort_keys=True, separators=(",", ":")))

    @staticmethod
    def _revision_identity(value: dict[str, object]) -> dict[str, object]:
        return {
            key: item for key, item in value.items()
            if key not in {
                "route_id", "catalog_rank", "total_users", "rating",
                "review_count", "bookmark_count", "query_hits",
                "display_name", "short_description",
                "account_fit_rank", "account_fit_reason",
            }
        }

    @staticmethod
    def _cursor(phase: str, **values: object) -> str:
        encoded = json.dumps({"phase": phase, **values}, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_CURSOR_BYTES:
            raise ValueError("actorops discovery checkpoint exceeds its safe bound")
        return encoded

    @staticmethod
    def _read_cursor(row: Any, phase: str) -> dict[str, object]:
        try:
            value = json.loads(str(row["search_cursor"] or ""))
        except json.JSONDecodeError as error:
            raise ValueError("actorops discovery checkpoint is invalid") from error
        if not isinstance(value, dict) or value.get("phase") != phase:
            raise ValueError("actorops discovery checkpoint stage mismatch")
        return value

    @staticmethod
    def _retry_after(row: Any) -> datetime:
        value = str(row["retry_after"] or "1970-01-01T00:00:00+00:00")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

    @staticmethod
    def _unique(items: list[dict[str, object]]) -> list[dict[str, object]]:
        return list({str(item["candidate_id"]): item for item in items}.values())

    @staticmethod
    def _ranked(items: list[dict[str, object]]) -> list[dict[str, object]]:
        ranked = sorted(items, key=candidate_quality_key)
        retained: list[dict[str, object]] = []
        selected = 0
        for item in ranked:
            if _route_candidate(item):
                if selected >= _MAX_ROUTE_CANDIDATES:
                    continue
                selected += 1
            item["rank"] = len(retained)
            retained.append(item)
        return retained

    @staticmethod
    def _cursor_candidate(item: dict[str, object]) -> dict[str, object]:
        return {
            key: value for key, value in item.items()
            if key not in {
                "manifest_json", "input_plan_json", "avatar_json_pointer",
            }
        }


def _route_candidate(item: dict[str, object]) -> bool:
    return bool(
        item.get("status") == "accepted"
        or item.get("rejection_code")
        == "actorops_discovery_output_sample_required"
    )


def _usable_output_schema(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    properties = value.get("properties")
    return isinstance(properties, dict) and bool(properties)

__all__ = ["ActorOpsDiscovery", "DiscoveryCatalogError", "DiscoveryResult"]
