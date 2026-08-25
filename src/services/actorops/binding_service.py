"""Central lifecycle owner for online ActorOps v2 source bindings."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .binding_evidence import (
    BindingEvidence,
    BindingEvidenceEvaluator,
    BindingTarget,
)
from .domain import BindingRecord, RouteKey, RuntimeMode
from .registry import AdapterRegistry
from .repository import ActorOpsConflict, ActorOpsNotFound, ActorOpsRepository


class ActorOpsBindingError(RuntimeError):
    """Stable, value-safe Binding lifecycle failure."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class BindingExecutionState:
    source_id: str
    route_id: str
    binding_version: int
    binding_status: str
    route_mode: str
    allowed: bool
    execution_mode: str
    reason: str | None
    retryable: bool = False


class ActorOpsBindingService:
    """Create and mutate Binding state without consulting ActorOps v1 facts."""

    def __init__(
        self,
        store: Any,
        *,
        workspace_id: str,
        registry: AdapterRegistry | None = None,
    ) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)
        if registry is None:
            from .adapters import build_default_registry

            registry = build_default_registry()
        self.registry = registry
        self.repository = ActorOpsRepository(store.connect(), self.workspace_id)
        self.evidence = BindingEvidenceEvaluator(
            self.repository, registry, workspace_id=self.workspace_id
        )

    def ensure(self, source_id: str) -> BindingRecord:
        source = self._source(source_id)
        existing = self._binding_or_none(source_id)
        target = self._target(source, existing=existing)
        if existing is not None:
            if (
                existing.route_id != target.route_id
                or existing.target_fingerprint != target.target_fingerprint
            ):
                return self.rebind(source_id)
            if existing.status != "ready" and bool(source.get("enabled")):
                with self.repository.transaction():
                    self.store.update_source(source_id, enabled=False, commit=False)
            return self.repository.get_binding(source_id)
        stamp = _now()
        with self.repository.transaction():
            self.store.update_source(source_id, enabled=False, commit=False)
            self.repository.connection.execute(
                """INSERT INTO actor_source_bindings_v2 (
                       binding_id, workspace_id, source_id, route_id,
                       target_fingerprint, status, binding_version,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 'pending', 1, ?, ?)""",
                (
                    _binding_id(self.workspace_id, source_id),
                    self.workspace_id,
                    source_id,
                    target.route_id,
                    target.target_fingerprint,
                    stamp,
                    stamp,
                ),
            )
        return self.repository.get_binding(source_id)

    def rebind(self, source_id: str) -> BindingRecord:
        source = self._source(source_id)
        current = self._binding_or_none(source_id)
        target = self._target(source, existing=current)
        if current is None:
            return self.ensure(source_id)
        if (
            current.route_id == target.route_id
            and current.target_fingerprint == target.target_fingerprint
        ):
            if current.status != "ready" and bool(source.get("enabled")):
                with self.repository.transaction():
                    self.store.update_source(source_id, enabled=False, commit=False)
            return self.repository.get_binding(source_id)
        stamp = _now()
        with self.repository.transaction():
            self.store.update_source(source_id, enabled=False, commit=False)
            changed = self.repository.connection.execute(
                """UPDATE actor_source_bindings_v2
                   SET route_id=?, target_fingerprint=?, status='pending',
                       binding_version=binding_version+1,
                       preferred_candidate_id=NULL,
                       last_known_good_candidate_id=NULL,
                       last_success_at=NULL,
                       watermark_latest_published_at=NULL,
                       watermark_item_id_hash=NULL,
                       watermark_last_advanced_at=NULL,
                       updated_at=?
                   WHERE workspace_id=? AND source_id=? AND binding_version=?""",
                (
                    target.route_id,
                    target.target_fingerprint,
                    stamp,
                    self.workspace_id,
                    source_id,
                    current.binding_version,
                ),
            ).rowcount
            if changed != 1:
                raise ActorOpsBindingError("actorops_v2_binding_conflict")
        return self.repository.get_binding(source_id)

    def verify(
        self,
        source_id: str,
        *,
        expected_binding_version: int,
        expected_target_fingerprint: str,
    ) -> BindingRecord:
        binding = self.repository.get_binding(source_id)
        if (
            binding.status != "pending"
            or binding.binding_version != int(expected_binding_version)
            or binding.target_fingerprint != str(expected_target_fingerprint)
        ):
            raise ActorOpsBindingError("actorops_v2_binding_conflict")
        source = self._source(source_id)
        target = self._target(source, existing=binding)
        if (
            target.route_id != binding.route_id
            or target.target_fingerprint != binding.target_fingerprint
        ):
            raise ActorOpsBindingError("actorops_v2_binding_conflict")
        evidence = self.evidence.assess(binding, source, target)
        if not evidence.eligible:
            raise ActorOpsBindingError("actorops_v2_binding_evidence_missing")
        try:
            with self.repository.transaction():
                return self.repository.mark_binding_ready(
                    source_id,
                    expected_binding_version=binding.binding_version,
                    expected_target_fingerprint=binding.target_fingerprint,
                )
        except ActorOpsConflict as exc:
            raise ActorOpsBindingError("actorops_v2_binding_conflict") from exc

    def assess(self, source_id: str) -> BindingEvidence:
        binding = self.repository.get_binding(source_id)
        source = self._source(source_id)
        target = self._target(source, existing=binding)
        if (
            target.route_id != binding.route_id
            or target.target_fingerprint != binding.target_fingerprint
        ):
            raise ActorOpsBindingError("actorops_v2_binding_conflict")
        return self.evidence.assess(binding, source, target)

    def disable(self, source_id: str) -> BindingRecord:
        binding = self.repository.get_binding(source_id)
        if binding.status == "disabled":
            if bool(self._source(source_id).get("enabled")):
                with self.repository.transaction():
                    self.store.update_source(source_id, enabled=False, commit=False)
            return self.repository.get_binding(source_id)
        stamp = _now()
        with self.repository.transaction():
            self.store.update_source(source_id, enabled=False, commit=False)
            changed = self.repository.connection.execute(
                """UPDATE actor_source_bindings_v2
                   SET status='disabled', binding_version=binding_version+1,
                       preferred_candidate_id=NULL, updated_at=?
                   WHERE workspace_id=? AND source_id=? AND binding_version=?""",
                (
                    stamp,
                    self.workspace_id,
                    source_id,
                    binding.binding_version,
                ),
            ).rowcount
            if changed != 1:
                raise ActorOpsBindingError("actorops_v2_binding_conflict")
        return self.repository.get_binding(source_id)

    def soft_delete(self, source_id: str) -> BindingRecord:
        return self.disable(source_id)

    def reenable(self, source_id: str) -> BindingRecord:
        binding = self.repository.get_binding(source_id)
        if binding.status == "pending":
            if bool(self._source(source_id).get("enabled")):
                with self.repository.transaction():
                    self.store.update_source(source_id, enabled=False, commit=False)
            return self.repository.get_binding(source_id)
        if binding.status != "disabled":
            raise ActorOpsBindingError("actorops_v2_binding_reenable_invalid")
        stamp = _now()
        with self.repository.transaction():
            self.store.update_source(source_id, enabled=False, commit=False)
            changed = self.repository.connection.execute(
                """UPDATE actor_source_bindings_v2
                   SET status='pending', binding_version=binding_version+1,
                       preferred_candidate_id=NULL, updated_at=?
                   WHERE workspace_id=? AND source_id=? AND status='disabled'
                     AND binding_version=?""",
                (
                    stamp,
                    self.workspace_id,
                    source_id,
                    binding.binding_version,
                ),
            ).rowcount
            if changed != 1:
                raise ActorOpsBindingError("actorops_v2_binding_conflict")
        return self.repository.get_binding(source_id)

    def enable_ready(self, source_id: str) -> BindingRecord:
        state = self.execution_state(source_id)
        if not state.allowed:
            raise ActorOpsBindingError("actorops_v2_binding_not_ready")
        with self.repository.transaction():
            current = self.repository.get_binding(source_id)
            if (
                current.status != "ready"
                or current.binding_version != state.binding_version
            ):
                raise ActorOpsBindingError("actorops_v2_binding_conflict")
            self.store.update_source(source_id, enabled=True, commit=False)
        return self.repository.get_binding(source_id)

    def execution_state(self, source_id: str) -> BindingExecutionState:
        binding = self.repository.get_binding(source_id)
        route = self.repository.get_route(binding.route_id)
        if binding.status != "ready":
            return BindingExecutionState(
                source_id,
                binding.route_id,
                binding.binding_version,
                binding.status,
                route.runtime_mode.value,
                False,
                "blocked",
                f"actorops_v2_binding_{binding.status}",
            )
        if route.runtime_mode is RuntimeMode.ACTIVE:
            return BindingExecutionState(
                source_id,
                binding.route_id,
                binding.binding_version,
                binding.status,
                route.runtime_mode.value,
                True,
                "actor",
                None,
            )
        if route.route_key == RouteKey("youtube", "channel", "items"):
            return BindingExecutionState(
                source_id,
                binding.route_id,
                binding.binding_version,
                binding.status,
                route.runtime_mode.value,
                True,
                "native_fallback",
                "actorops_v2_route_disabled_native_fallback",
            )
        return BindingExecutionState(
            source_id,
            binding.route_id,
            binding.binding_version,
            binding.status,
            route.runtime_mode.value,
            False,
            "blocked",
            "actorops_v2_route_disabled",
        )

    def _source(self, source_id: str) -> dict[str, Any]:
        source = self.store.get_source(source_id)
        if source is None or str(source.get("workspace_id")) != self.workspace_id:
            raise ActorOpsBindingError("actorops_v2_source_not_found")
        return source

    def _binding_or_none(self, source_id: str) -> BindingRecord | None:
        try:
            return self.repository.get_binding(source_id)
        except ActorOpsNotFound:
            return None

    def _target(
        self,
        source: dict[str, Any],
        *,
        existing: BindingRecord | None = None,
    ) -> BindingTarget:
        try:
            return self.evidence.target(source, existing=existing)
        except ValueError as exc:
            raise ActorOpsBindingError(str(exc)) from exc


def _binding_id(workspace_id: str, source_id: str) -> str:
    digest = hashlib.sha256(
        "\x1f".join((str(workspace_id), str(source_id))).encode("utf-8")
    ).hexdigest()[:32]
    return f"actorops-v2-binding-{digest}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ActorOpsBindingError",
    "ActorOpsBindingService",
    "BindingExecutionState",
]
