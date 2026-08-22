"""Central lifecycle owner for online ActorOps v2 source bindings."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from ...apify_actor_identity import source_target_fingerprint
from ..apify_actor_manifest import (
    ActorManifestError,
    actor_manifest_hash,
    parse_actor_manifest,
)
from ..source_type_registry import is_youtube_channel_config
from .domain import BindingRecord, RouteKey, RuntimeMode
from .ports import ActorManifest, FetchWindow
from .registry import AdapterNotRegistered, AdapterRegistry
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


@dataclass(frozen=True, slots=True)
class _BindingTarget:
    route_id: str
    route_key: RouteKey
    raw_target: str
    target_fingerprint: str


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
                       source_v1_generation, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 'pending', 1, 1, ?, ?)""",
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
        target = self._target(source)
        if (
            target.route_id != binding.route_id
            or target.target_fingerprint != binding.target_fingerprint
        ):
            raise ActorOpsBindingError("actorops_v2_binding_conflict")
        if not (
            self._has_deterministic_proof(binding, source, target)
            or self._has_settled_probe(binding)
        ):
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
        source: Mapping[str, Any],
        *,
        existing: BindingRecord | None = None,
    ) -> _BindingTarget:
        config = source.get("config")
        if not isinstance(config, Mapping):
            raise ActorOpsBindingError("actorops_v2_target_invalid")
        source_type = str(source.get("type") or "")
        if source_type == "rss" and is_youtube_channel_config(config):
            route_key = RouteKey("youtube", "channel", "items")
            raw_target = str(config.get("url") or "")
        elif source_type == "apify_social":
            raw_target = str(config.get("target") or "")
            profile_id = str(config.get("profile_id") or "").strip()
            if profile_id:
                try:
                    route = self.repository.get_route(profile_id)
                except ActorOpsNotFound as exc:
                    if existing is None:
                        raise ActorOpsBindingError(
                            "actorops_v2_route_not_found"
                        ) from exc
                    route = self.repository.get_route(existing.route_id)
                route_key = route.route_key
            else:
                route_key = RouteKey(
                    str(config.get("platform") or "").casefold(),
                    str(config.get("kind") or "").casefold(),
                    "items",
                )
        else:
            raise ActorOpsBindingError("actorops_v2_source_unsupported")
        try:
            adapter = self.registry.require(route_key)
            adapter.normalize_target({"target": raw_target})
        except (AdapterNotRegistered, TypeError, ValueError) as exc:
            raise ActorOpsBindingError("actorops_v2_target_invalid") from exc
        row = self.repository.connection.execute(
            """SELECT route_id FROM actor_routes_v2
               WHERE workspace_id=? AND platform=? AND target_type=?
                 AND capability=?""",
            (
                self.workspace_id,
                route_key.platform,
                route_key.target_type,
                route_key.capability,
            ),
        ).fetchone()
        if row is None:
            raise ActorOpsBindingError("actorops_v2_route_not_found")
        route_id = str(row["route_id"])
        return _BindingTarget(
            route_id,
            route_key,
            raw_target,
            source_target_fingerprint(
                self.workspace_id,
                route_id,
                raw_target,
                platform=route_key.platform,
            ),
        )

    def _has_deterministic_proof(
        self,
        binding: BindingRecord,
        source: Mapping[str, Any],
        target: _BindingTarget,
    ) -> bool:
        if target.route_key == RouteKey("youtube", "channel", "items"):
            return is_youtube_channel_config(source.get("config"))
        candidates = tuple(
            candidate
            for candidate in self.repository.list_route_candidates(binding.route_id)
            if candidate.assignment_role is not None
            and candidate.assignment_role.value in {"active", "standby"}
            and candidate.lifecycle.value in {"probationary", "certified"}
        )
        if not candidates:
            return False
        adapter = self.registry.require(target.route_key)
        normalized = adapter.normalize_target({"target": target.raw_target})
        window = FetchWindow(
            max_items=1,
            since=datetime(2000, 1, 1, tzinfo=timezone.utc),
            until=datetime(2000, 1, 2, tzinfo=timezone.utc),
        )
        for candidate in candidates:
            if not all(
                (
                    candidate.build_id,
                    candidate.build_number,
                    candidate.manifest_json,
                    candidate.manifest_hash,
                )
            ):
                return False
            try:
                parsed = parse_actor_manifest(str(candidate.manifest_json))
                if (
                    parsed.actor_id != candidate.actor_id
                    or parsed.build_number != candidate.build_number
                    or actor_manifest_hash(parsed) != candidate.manifest_hash
                ):
                    return False
                adapter.build_actor_input(
                    normalized,
                    ActorManifest(
                        candidate.actor_id,
                        str(candidate.build_id),
                        str(candidate.build_number),
                        str(candidate.manifest_json),
                        str(candidate.manifest_hash),
                    ),
                    window,
                )
            except (ActorManifestError, TypeError, ValueError):
                return False
        return True

    def _has_settled_probe(self, binding: BindingRecord) -> bool:
        return self.repository.connection.execute(
            """SELECT 1 FROM actor_attempts_v2 AS attempt
               JOIN actor_candidates_v2 AS candidate
                 ON candidate.workspace_id=attempt.workspace_id
                AND candidate.candidate_id=attempt.candidate_id
               WHERE attempt.workspace_id=? AND attempt.source_id=?
                 AND attempt.route_id=? AND attempt.binding_version=?
                 AND attempt.target_fingerprint=? AND attempt.kind='probe'
                 AND attempt.status='succeeded'
                 AND attempt.semantic_outcome='valid_nonempty'
                 AND attempt.result_state='validated' AND attempt.cost_final=1
                 AND candidate.assignment_role IN ('active','standby')
               LIMIT 1""",
            (
                self.workspace_id,
                binding.source_id,
                binding.route_id,
                binding.binding_version,
                binding.target_fingerprint,
            ),
        ).fetchone() is not None


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
