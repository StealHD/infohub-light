"""Recoverable, platform-neutral ActorOps v2 Discovery orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .discovery_manifest import schema_proven_manifest
from .domain import CandidateLifecycle, DiscoveryStage, DiscoveryStatus, FailureClass
from .ports import DiscoveryAiMapper, DiscoveryCatalog, DiscoveryMapping, DiscoveryRevision
from .registry import AdapterRegistry
from .repository import ActorOpsRepository
from .repository_errors import ActorOpsNotFound


_MAX_ACTORS = 12
_MAX_AI_MAPPINGS = 1
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
        actor_ids: list[str] = []
        for query in adapter.discovery_spec().queries:
            for actor_id in await self.catalog.search(query):
                normalized = str(actor_id).strip()
                if normalized and normalized not in actor_ids:
                    actor_ids.append(normalized)
                if len(actor_ids) >= _MAX_ACTORS:
                    break
            if len(actor_ids) >= _MAX_ACTORS:
                break
        cursor = self._cursor("metadata", actor_ids=actor_ids)
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.METADATA,
            cursor=cursor, query_count=len(adapter.discovery_spec().queries),
        )

    async def _metadata(self, row: Any) -> None:
        state = self._read_cursor(row, "metadata")
        revisions = [await self.catalog.get_revision(actor_id) for actor_id in state["actor_ids"]]
        refs = [self._revision_ref(item) for item in revisions]
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.VALIDATION,
            cursor=self._cursor("validation", refs=refs, rejections=[]),
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
            if self._revision_ref(revision) != self._unscoped_ref(ref):
                rejected.append(self._rejection(ref, "actorops_discovery_revision_changed"))
            elif not self._valid_revision(revision, cap):
                rejected.append(self._rejection(ref, "actorops_discovery_validation_rejected"))
            else:
                valid.append(ref)
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.MAPPING,
            cursor=self._cursor("mapping", refs=valid, rejections=rejected),
            rejection_count=len(rejected),
        )

    async def _mapping(self, row: Any, adapter: Any, route_key: Any) -> None:
        state = self._read_cursor(row, "mapping")
        descriptors, unresolved = [], []
        for raw_ref in state["refs"]:
            ref = {**raw_ref, "route_id": str(row["route_id"])}
            revision = await self.catalog.get_revision(str(ref["actor_id"]))
            if self._revision_ref(revision) != self._unscoped_ref(ref):
                descriptors.append(self._rejection(ref, "actorops_discovery_revision_changed"))
                continue
            mapping = adapter.map_discovery_manifest(revision)
            if mapping.manifest_json is None:
                unresolved.append(revision)
            else:
                descriptors.append(self._mapped(ref, mapping, revision))
        metrics: dict[str, object] = {}
        ai_revisions = unresolved[:_MAX_AI_MAPPINGS]
        if ai_revisions and self.ai_mapper is not None:
            try:
                ai_result = await self.ai_mapper.map(route_key, tuple(ai_revisions))
                metrics = {
                    "config_id": ai_result.config_id,
                    "input_tokens": ai_result.input_tokens,
                    "completion_tokens": ai_result.completion_tokens,
                    "reasoning_tokens": ai_result.reasoning_tokens,
                    "finish_reason": ai_result.finish_reason,
                    "latency_ms": ai_result.latency_ms,
                    "response_bytes": ai_result.response_bytes,
                }
                for revision in ai_revisions:
                    ref = {**self._revision_ref(revision), "route_id": str(row["route_id"])}
                    mapping = ai_result.mappings.get(revision.actor_id)
                    descriptors.append(self._mapped(ref, mapping, revision) if mapping else self._pending(ref))
            except Exception:
                descriptors.extend(self._pending({**self._revision_ref(item), "route_id": str(row["route_id"])}) for item in ai_revisions)
        else:
            descriptors.extend(self._pending({**self._revision_ref(item), "route_id": str(row["route_id"])}) for item in ai_revisions)
        descriptors.extend(
            self._pending({**self._revision_ref(item), "route_id": str(row["route_id"])})
            for item in unresolved[_MAX_AI_MAPPINGS:]
        )
        descriptors.extend(
            {**dict(value), "route_id": str(row["route_id"])}
            for value in state.get("rejections", [])
        )
        descriptors = self._unique(descriptors)
        with self.repository.transaction():
            for item in descriptors:
                self._ensure_candidate(str(row["route_id"]), item)
            self._checkpoint(
                row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.RANKING,
                cursor=self._cursor("ranking", candidates=descriptors),
                candidate_count=len(descriptors),
                rejection_count=sum(item["status"] == "rejected" for item in descriptors),
                ai_metrics=metrics,
            )

    def _ranking(self, row: Any) -> None:
        state = self._read_cursor(row, "ranking")
        candidates = [dict(item) for item in state["candidates"]]
        accepted = sorted(
            (item for item in candidates if item["status"] == "accepted"),
            key=lambda item: (item["publisher"], item["candidate_id"]),
        )
        pending = sorted(
            (item for item in candidates if item["status"] == "pending"),
            key=lambda item: (item["publisher"], item["candidate_id"]),
        )
        rejected = sorted(
            (item for item in candidates if item["status"] == "rejected"),
            key=lambda item: (item["publisher"], item["candidate_id"]),
        )
        ranked = self._publisher_first(accepted) + pending + rejected
        for rank, item in enumerate(ranked):
            item["rank"] = rank
        self._checkpoint(
            row, status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.PERSIST,
            cursor=self._cursor("persist", candidates=ranked),
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
                cursor=self._cursor("persist", candidates=state["candidates"]),
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
            self.repository.transition_candidate(
                created.candidate_id, CandidateLifecycle.DISCOVERED, target,
                expected_generation=created.generation,
                error_class=(FailureClass.CANDIDATE.value if target is CandidateLifecycle.REJECTED else None),
                error_code=item.get("rejection_code"),
            )
            return
        if existing.route_id != route_id or existing.actor_id != item["actor_id"]:
            raise ValueError("actorops discovery candidate identity collision")

    def _mapped(self, ref: dict[str, object], mapping: DiscoveryMapping | None, revision: DiscoveryRevision) -> dict[str, object]:
        manifest_json = schema_proven_manifest(revision, mapping)
        if not manifest_json:
            return self._pending(ref)
        manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
        return {
            **ref,
            "candidate_id": self._candidate_id(ref, manifest_hash),
            "manifest_json": manifest_json,
            "manifest_hash": manifest_hash,
            "status": "accepted",
            "rejection_code": None,
        }

    def _pending(self, ref: dict[str, object]) -> dict[str, object]:
        return {
            **ref, "candidate_id": self._candidate_id(ref, "mapping_pending"),
            "manifest_json": None, "manifest_hash": None, "status": "pending",
            "rejection_code": "actorops_discovery_mapping_pending",
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
            return
        with self.repository.transaction():
            self.repository.discovery.checkpoint(str(row["discovery_id"]), **values)

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
            "input_schema_hash": ActorOpsDiscovery._hash_value(revision.input_schema),
            "output_schema_hash": ActorOpsDiscovery._hash_value(revision.output_schema),
        }

    @staticmethod
    def _valid_revision(revision: DiscoveryRevision, cap: float) -> bool:
        return bool(
            revision.actor_id and revision.publisher and revision.build_id
            and revision.build_number and revision.input_schema and revision.output_schema
            and isinstance(revision.price_per_run_usd, (int, float))
            and 0 <= float(revision.price_per_run_usd) <= cap
        )

    @staticmethod
    def _candidate_id(ref: dict[str, object], manifest: str) -> str:
        value = "\x1f".join(str(ref[key]) for key in ("route_id", "actor_id", "build_id", "build_number"))
        return "candidate_" + hashlib.sha256(f"{value}\x1f{manifest}".encode()).hexdigest()[:24]

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_value(value: object) -> str:
        return ActorOpsDiscovery._hash(json.dumps(value, sort_keys=True, separators=(",", ":")))

    @staticmethod
    def _unscoped_ref(value: dict[str, object]) -> dict[str, object]:
        return {key: item for key, item in value.items() if key != "route_id"}

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
    def _publisher_first(items: list[dict[str, object]]) -> list[dict[str, object]]:
        selected, deferred, publishers = [], [], set()
        for item in items:
            if item["publisher"] in publishers:
                deferred.append(item)
            else:
                publishers.add(item["publisher"])
                selected.append(item)
        return selected + deferred


__all__ = ["ActorOpsDiscovery", "DiscoveryCatalogError", "DiscoveryResult"]
