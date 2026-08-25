"""Local, zero-cost evidence checks for ActorOps v2 source bindings."""

from __future__ import annotations

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
from .domain import BindingRecord, RouteKey
from .ports import ActorManifest, FetchWindow
from .registry import AdapterNotRegistered, AdapterRegistry
from .repository import ActorOpsNotFound, ActorOpsRepository


@dataclass(frozen=True, slots=True)
class BindingTarget:
    route_id: str
    route_key: RouteKey
    raw_target: str
    target_fingerprint: str


@dataclass(frozen=True, slots=True)
class BindingEvidence:
    eligible: bool
    proof_kind: str | None
    reason: str | None


class BindingEvidenceEvaluator:
    """Evaluate only persisted Route, Candidate and Probe facts."""

    def __init__(
        self,
        repository: ActorOpsRepository,
        registry: AdapterRegistry,
        *,
        workspace_id: str,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.workspace_id = str(workspace_id)

    def target(
        self,
        source: Mapping[str, Any],
        *,
        existing: BindingRecord | None = None,
    ) -> BindingTarget:
        config = source.get("config")
        if not isinstance(config, Mapping):
            raise ValueError("actorops_v2_target_invalid")
        source_type = str(source.get("type") or "")
        if source_type == "rss" and is_youtube_channel_config(config):
            route_key = RouteKey("youtube", "channel", "items")
            raw_target = str(config.get("url") or "")
        elif source_type == "apify_social":
            raw_target = str(config.get("target") or "")
            route_key = self._route_key(config, existing=existing)
        else:
            raise ValueError("actorops_v2_source_unsupported")
        try:
            self.registry.require(route_key).normalize_target({"target": raw_target})
        except (AdapterNotRegistered, TypeError, ValueError) as exc:
            raise ValueError("actorops_v2_target_invalid") from exc
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
            raise ValueError("actorops_v2_route_not_found")
        route_id = str(row["route_id"])
        return BindingTarget(
            route_id=route_id,
            route_key=route_key,
            raw_target=raw_target,
            target_fingerprint=source_target_fingerprint(
                self.workspace_id,
                route_id,
                raw_target,
                platform=route_key.platform,
            ),
        )

    def assess(
        self,
        binding: BindingRecord,
        source: Mapping[str, Any],
        target: BindingTarget,
    ) -> BindingEvidence:
        deterministic = self._deterministic(binding, source, target)
        if deterministic.eligible:
            return deterministic
        if self._has_settled_probe(binding):
            return BindingEvidence(True, "settled_probe", None)
        return deterministic

    def _route_key(
        self,
        config: Mapping[str, Any],
        *,
        existing: BindingRecord | None,
    ) -> RouteKey:
        profile_id = str(config.get("profile_id") or "").strip()
        if not profile_id:
            return RouteKey(
                str(config.get("platform") or "").casefold(),
                str(config.get("kind") or "").casefold(),
                "items",
            )
        try:
            return self.repository.get_route(profile_id).route_key
        except ActorOpsNotFound as exc:
            if existing is None:
                raise ValueError("actorops_v2_route_not_found") from exc
            try:
                return self.repository.get_route(existing.route_id).route_key
            except ActorOpsNotFound as fallback_exc:
                raise ValueError("actorops_v2_route_not_found") from fallback_exc

    def _deterministic(
        self,
        binding: BindingRecord,
        source: Mapping[str, Any],
        target: BindingTarget,
    ) -> BindingEvidence:
        if target.route_key == RouteKey("youtube", "channel", "items"):
            return BindingEvidence(
                is_youtube_channel_config(source.get("config")),
                "deterministic",
                None,
            )
        candidates = tuple(
            item
            for item in self.repository.list_route_candidates(binding.route_id)
            if item.assignment_role is not None
            and item.assignment_role.value in {"active", "standby"}
            and item.lifecycle.value in {"probationary", "certified"}
        )
        if not candidates:
            return BindingEvidence(
                False, None, "actorops_v2_binding_no_runnable_candidate"
            )
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
                return BindingEvidence(
                    False,
                    None,
                    "actorops_v2_binding_candidate_manifest_missing",
                )
            try:
                parsed = parse_actor_manifest(str(candidate.manifest_json))
                if (
                    parsed.actor_id != candidate.actor_id
                    or parsed.build_number != candidate.build_number
                    or actor_manifest_hash(parsed) != candidate.manifest_hash
                ):
                    return BindingEvidence(
                        False,
                        None,
                        "actorops_v2_binding_candidate_manifest_invalid",
                    )
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
                return BindingEvidence(
                    False,
                    None,
                    "actorops_v2_binding_candidate_input_unsupported",
                )
        return BindingEvidence(True, "deterministic", None)

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


__all__ = ["BindingEvidence", "BindingEvidenceEvaluator", "BindingTarget"]
