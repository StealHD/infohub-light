from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.services.actorops.domain import (
    AssignmentRole,
    AttemptStatus,
    CandidateLifecycle,
    CandidateRecord,
    DiscoveryStage,
    DiscoveryStatus,
    InvalidTransition,
    RouteHealth,
    RouteKey,
    ensure_attempt_transition,
    ensure_candidate_transition,
    ensure_discovery_transition,
)
from src.services.actorops.policy import derive_route_health, ordered_candidates
from src.services.actorops.ports import (
    ActorManifest,
    DiscoverySpec,
    FetchWindow,
    NativeFallbackResult,
    NormalizedBatch,
    TargetSpec,
)
from src.services.actorops.registry import (
    AdapterAlreadyRegistered,
    AdapterNotRegistered,
    AdapterRegistry,
)


def test_route_key_normalizes_and_rejects_unsafe_parts() -> None:
    key = RouteKey(" YouTube ", "Channel", "ITEMS")
    assert key == RouteKey("youtube", "channel", "items")
    assert str(key) == "youtube/channel/items"
    with pytest.raises(ValueError):
        RouteKey("youtube/other", "channel", "items")


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, RouteHealth.UNAVAILABLE), (1, RouteHealth.DEGRADED), (2, RouteHealth.HEALTHY), (3, RouteHealth.HEALTHY)],
)
def test_route_health_is_derived_from_runnable_assignments(
    count: int, expected: RouteHealth
) -> None:
    assert derive_route_health(count) is expected


def test_candidate_order_is_active_then_standby_then_distinct_lkg() -> None:
    def candidate(candidate_id, role, priority):
        return CandidateRecord(
            candidate_id=candidate_id,
            route_id="route",
            lifecycle=CandidateLifecycle.CERTIFIED,
            assignment_role=role,
            priority=priority,
            generation=1,
            build_id="build",
            manifest_hash="a" * 64,
        )

    candidates = (
        candidate("standby", AssignmentRole.STANDBY, 1),
        candidate("lkg", AssignmentRole.INACTIVE, None),
        candidate("active", AssignmentRole.ACTIVE, 0),
    )
    assert [item.candidate_id for item in ordered_candidates(
        candidates, last_known_good_candidate_id="lkg"
    )] == ["active", "standby", "lkg"]
    assert [item.candidate_id for item in ordered_candidates(
        candidates, last_known_good_candidate_id="active"
    )] == ["active", "standby"]


def test_candidate_transitions_are_monotonic_and_terminal() -> None:
    ensure_candidate_transition(
        CandidateLifecycle.DISCOVERED, CandidateLifecycle.MAPPING_PENDING
    )
    ensure_candidate_transition(
        CandidateLifecycle.MAPPING_PENDING, CandidateLifecycle.STATIC_VALID
    )
    ensure_candidate_transition(
        CandidateLifecycle.STATIC_VALID, CandidateLifecycle.PROBATIONARY
    )
    ensure_candidate_transition(
        CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED
    )
    with pytest.raises(InvalidTransition):
        ensure_candidate_transition(
            CandidateLifecycle.CERTIFIED, CandidateLifecycle.PROBATIONARY
        )
    with pytest.raises(InvalidTransition):
        ensure_candidate_transition(
            CandidateLifecycle.DISABLED, CandidateLifecycle.STATIC_VALID
        )


def test_attempt_transitions_keep_unknown_start_local_and_terminal() -> None:
    ensure_attempt_transition(AttemptStatus.CREATED, AttemptStatus.STARTING)
    ensure_attempt_transition(AttemptStatus.STARTING, AttemptStatus.START_UNKNOWN)
    ensure_attempt_transition(AttemptStatus.START_UNKNOWN, AttemptStatus.REGISTERED)
    ensure_attempt_transition(AttemptStatus.REGISTERED, AttemptStatus.RUNNING)
    ensure_attempt_transition(AttemptStatus.RUNNING, AttemptStatus.SUCCEEDED)
    with pytest.raises(InvalidTransition):
        ensure_attempt_transition(AttemptStatus.SUCCEEDED, AttemptStatus.RUNNING)
    with pytest.raises(InvalidTransition):
        ensure_attempt_transition(AttemptStatus.START_UNKNOWN, AttemptStatus.STARTING)


def test_discovery_retry_keeps_stage_monotonic_and_terminal() -> None:
    ensure_discovery_transition(
        DiscoveryStatus.RUNNING,
        DiscoveryStage.METADATA,
        DiscoveryStatus.RETRY_WAIT,
        DiscoveryStage.METADATA,
    )
    ensure_discovery_transition(
        DiscoveryStatus.RETRY_WAIT,
        DiscoveryStage.METADATA,
        DiscoveryStatus.RUNNING,
        DiscoveryStage.VALIDATION,
    )
    with pytest.raises(InvalidTransition):
        ensure_discovery_transition(
            DiscoveryStatus.RUNNING,
            DiscoveryStage.MAPPING,
            DiscoveryStatus.RUNNING,
            DiscoveryStage.METADATA,
        )
    with pytest.raises(InvalidTransition):
        ensure_discovery_transition(
            DiscoveryStatus.COMPLETED,
            DiscoveryStage.PERSIST,
            DiscoveryStatus.RUNNING,
            DiscoveryStage.PERSIST,
        )


class _FakeAdapter:
    route_key = RouteKey("test", "profile", "items")

    def normalize_target(self, source_config):
        return TargetSpec(canonical_url=str(source_config["url"]))

    def discovery_spec(self):
        return DiscoverySpec(queries=("test profile items",))

    def build_actor_input(self, target, manifest, window):
        return {"url": target.canonical_url, "limit": window.max_items}

    def validate_output(self, rows, target, manifest, window):
        return NormalizedBatch(items=tuple(rows), semantic_outcome="valid_nonempty")

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult.unsupported()


def test_registry_rejects_duplicates_and_unknown_route_keys() -> None:
    registry = AdapterRegistry()
    adapter = _FakeAdapter()
    registry.register(adapter)
    assert registry.require(adapter.route_key) is adapter
    with pytest.raises(AdapterAlreadyRegistered):
        registry.register(adapter)
    with pytest.raises(AdapterNotRegistered):
        registry.require(RouteKey("missing", "profile", "items"))

    manifest = ActorManifest(
        actor_id="actor/test",
        build_id="build-1",
        build_number="1.0.0",
        manifest_json="{}",
        manifest_hash="a" * 64,
    )
    window = FetchWindow(
        max_items=3,
        since=datetime(2026, 8, 20, tzinfo=timezone.utc),
        until=None,
    )
    assert adapter.build_actor_input(TargetSpec("https://example.com/user"), manifest, window)["limit"] == 3


def test_generic_modules_contain_no_platform_branches_or_storage_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "services" / "actorops"
    names = (
        "domain.py", "ports.py", "registry.py", "policy.py", "repository.py",
        "runtime.py", "service.py", "apify_remote.py", "publication.py",
    )
    for name in names:
        source = (root / name).read_text(encoding="utf-8").casefold()
        assert "if platform" not in source
        assert "youtube.com" not in source
        assert "instagram.com" not in source
    for name in ("domain.py", "ports.py", "registry.py", "policy.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "import sqlite3" not in source
        assert "ServiceStore" not in source
