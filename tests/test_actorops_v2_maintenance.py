from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.apify_actor_identity import source_target_fingerprint
from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from src.services.actorops.domain import AssignmentRole, AttemptStatus, CandidateLifecycle, FailureClass
from src.services.actorops.maintenance import ActorOpsProber, ProbeResult
from src.services.actorops.ports import (
    FetchWindow,
    ProbePreflightResult,
    RemoteRunResult,
    TargetSpec,
)
from src.services.actorops.registry import AdapterRegistry
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.runtime import ActorOpsRuntimeError
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _manifest(actor_id: str) -> str:
    return json.dumps({
        "version": 1, "actor_id": actor_id, "build_number": "1.0.0",
        "input": {"target": {"$ref": "target.handle"}},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/author"], "transforms": ["to_string"]},
        },
        "semantics": {
            "identity": {"output_field": "author_handle", "target_ref": "target.handle", "match": "handle"},
            "url_host_allowlist": ["example.com"],
        },
    })


class _Adapter:
    from src.services.actorops.domain import RouteKey

    route_key = RouteKey("test", "profile", "items")

    def normalize_target(self, config):
        return TargetSpec(canonical_url=f"https://example.com/{config['target']}", handle=str(config["target"]))

    def discovery_spec(self):
        raise AssertionError("Discovery is outside this test")

    def map_discovery_manifest(self, revision):
        raise AssertionError("Discovery is outside this test")

    def build_actor_input(self, target, manifest, window):
        return {"target": target.handle, "limit": window.max_items}

    def validate_output(self, rows, target, manifest, window):
        from src.services.actorops.ports import NormalizedBatch

        if rows[0].get("empty"):
            return NormalizedBatch((), "valid_empty")
        return NormalizedBatch((object(),), "valid_nonempty", "2026-08-20T00:00:00+00:00", "item")

    async def fetch_native_fallback(self, target, window):
        raise AssertionError("Probe must not use native fallback")


@dataclass
class _Preflight:
    allowed: bool = True
    code: str | None = None
    calls: int = 0

    async def verify(self, candidate, *, max_charge_usd):
        self.calls += 1
        return ProbePreflightResult(self.allowed, self.code)


class _Remote:
    def __init__(self, outcome: object = "ok", run_id: str = "run-one") -> None:
        self.outcome = outcome
        self.run_id = run_id
        self.requests = []

    async def execute(self, request, events):
        self.requests.append(request)
        events.starting(secret_ref_id="ref", secret_version=1, pool_generation=1)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        events.registered(remote_run_id=self.run_id, dataset_id="dataset-one")
        events.running()
        return RemoteRunResult(
            rows=({"empty": self.outcome == "empty"},), remote_run_id=self.run_id,
            dataset_id="dataset-one", actual_cost_usd=0.01, cost_final=True,
        )


def _repository(tmp_path: Path):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID, username="maintenance-owner",
        password="safe-test-password", role="owner",
    )
    connection = store.connect()
    route_id = str(connection.execute("SELECT route_id FROM actor_routes_v2 WHERE platform='x'").fetchone()[0])
    connection.execute("UPDATE actor_routes_v2 SET platform='test' WHERE route_id=?", (route_id,))
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
        source_type="apify_social", display_name="Maintenance source",
        config={"target": "openai"},
    )
    fingerprint = source_target_fingerprint(DEFAULT_WORKSPACE_ID, route_id, "openai", platform="test")
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                binding_id, workspace_id, source_id, route_id, target_fingerprint,
                status, binding_version, created_at, updated_at
            ) VALUES ('binding-maintenance', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (DEFAULT_WORKSPACE_ID, source_id, route_id, fingerprint,
             "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00"),
        )
        for candidate_id, lifecycle in (("active", CandidateLifecycle.CERTIFIED), ("candidate", CandidateLifecycle.STATIC_VALID)):
            manifest = _manifest(f"publisher/{candidate_id}")
            repository.create_candidate(
                candidate_id=candidate_id, route_id=route_id, actor_id=f"publisher/{candidate_id}",
                publisher="publisher", build_id=f"build-{candidate_id}", build_number="1.0.0",
                manifest_json=manifest, manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
                input_schema_hash="a" * 64, output_schema_hash="b" * 64, lifecycle=lifecycle,
            )
        repository.assign_candidate(route_id, "active", AssignmentRole.ACTIVE, priority=0,
                                    expected_route_generation=1, expected_candidate_generation=1)
    return store, repository, route_id, source_id


def _authorize(repository: ActorOpsRepository, route_id: str) -> None:
    workspace = repository.maintenance.get_policy(None)
    route = repository.maintenance.get_policy(route_id)
    owner = repository.connection.execute(
        "SELECT id FROM users WHERE workspace_id=? AND role='owner'", (DEFAULT_WORKSPACE_ID,)
    ).fetchone()
    assert owner is not None
    with repository.transaction():
        repository.maintenance.set_enabled(None, True, authorized_by_user_id=str(owner[0]), expected_generation=workspace.generation)
        repository.maintenance.set_enabled(route_id, True, authorized_by_user_id=str(owner[0]), expected_generation=route.generation)


def _prober(repository, remote, preflight):
    registry = AdapterRegistry()
    registry.register(_Adapter())
    return ActorOpsProber(repository, registry, remote, preflight, id_factory=lambda: "probe-attempt",
                           now=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc))


def test_policy_requires_workspace_and_route_authorization_and_counts_reserved_budget(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    workspace = repository.maintenance.get_policy(None)
    route = repository.maintenance.get_policy(route_id)
    owner = repository.connection.execute(
        "SELECT id FROM users WHERE workspace_id=? AND role='owner'", (DEFAULT_WORKSPACE_ID,)
    ).fetchone()
    assert owner is not None
    assert workspace.enabled is False and route.enabled is False
    with pytest.raises(ActorOpsConflict, match="authorizer_invalid"):
        with repository.transaction():
            repository.maintenance.set_enabled(
                None, True, authorized_by_user_id="not-an-operator",
                expected_generation=workspace.generation,
            )
    with repository.transaction():
        repository.maintenance.set_enabled(
            None, True, authorized_by_user_id=str(owner[0]), expected_generation=workspace.generation
        )
    with pytest.raises(ActorOpsConflict, match="not_authorized"):
        with repository.transaction():
            repository.maintenance.reserve_probe(
                route_id=route_id, candidate_id="candidate", source_id=source_id,
                binding_version=1, target_fingerprint=repository.get_binding(source_id).target_fingerprint,
                idempotency_key="probe-one", attempt_id="probe-one", attempt_group_id="slot-one",
                expected_route_generation=2, expected_candidate_generation=1,
                expected_workspace_policy_generation=2, expected_route_policy_generation=1,
                reserved_usd=0.05, now=datetime(2026, 8, 20, tzinfo=timezone.utc),
            )
    _authorize(repository, route_id)
    policies = repository.maintenance.effective_policy(route_id)
    with repository.transaction():
        repository.maintenance.reserve_probe(
            route_id=route_id, candidate_id="candidate", source_id=source_id,
            binding_version=1, target_fingerprint=repository.get_binding(source_id).target_fingerprint,
            idempotency_key="probe-one", attempt_id="probe-one", attempt_group_id="slot-one",
            expected_route_generation=2, expected_candidate_generation=1,
            expected_workspace_policy_generation=policies.workspace.generation,
            expected_route_policy_generation=policies.route.generation,
            reserved_usd=0.05, now=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
    assert repository.maintenance.probe_budget(route_id, datetime(2026, 8, 20, tzinfo=timezone.utc)).reserved_usd == pytest.approx(0.05)
    store.close()


def test_successful_probe_promotes_and_adds_standby_without_feed_publication(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    remote, preflight = _Remote(), _Preflight()

    result = asyncio.run(_prober(repository, remote, preflight).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:2",
    ))

    candidate = repository.get_candidate("candidate")
    assert result.status == "promoted"
    assert candidate.lifecycle is CandidateLifecycle.PROBATIONARY
    assert candidate.assignment_role is AssignmentRole.STANDBY
    assert len(remote.requests) == 1 and remote.requests[0].max_items == 1
    assert remote.requests[0].max_remote_starts == 1
    assert remote.requests[0].dataset_item_limit == 1
    assert store.connect().execute("SELECT COUNT(*) FROM actor_source_bindings_v2 WHERE last_known_good_candidate_id IS NOT NULL").fetchone()[0] == 0
    store.close()


def test_second_distinct_target_probe_certifies_the_same_standby(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    other_source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
        source_type="apify_social", display_name="Other maintenance source", config={"target": "other"},
    )
    fingerprint = source_target_fingerprint(DEFAULT_WORKSPACE_ID, route_id, "other", platform="test")
    with repository.transaction():
        repository.connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                binding_id, workspace_id, source_id, route_id, target_fingerprint,
                status, binding_version, created_at, updated_at
            ) VALUES ('binding-maintenance-other', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (DEFAULT_WORKSPACE_ID, other_source_id, route_id, fingerprint,
             "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00"),
        )

    first = asyncio.run(_prober(repository, _Remote(), _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:1",
    ))
    second = asyncio.run(_prober(repository, _Remote(run_id="run-two"), _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=other_source_id,
        source_config={"target": "other"}, maintenance_slot="2026-08-20:2",
    ))

    assert first.status == "promoted"
    assert second.status == "promoted", second
    candidate = repository.get_candidate("candidate")
    assert candidate.lifecycle is CandidateLifecycle.CERTIFIED
    assert candidate.assignment_role is AssignmentRole.STANDBY
    store.close()


def test_empty_probe_is_no_evidence_and_remote_unknown_never_reposts(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    empty = asyncio.run(_prober(repository, _Remote("empty"), _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:2",
    ))
    assert empty.status == "no_evidence"
    assert repository.get_candidate("candidate").lifecycle is CandidateLifecycle.STATIC_VALID

    error = ActorOpsRuntimeError("actorops_remote_unknown", failure_class=FailureClass.REMOTE_UNKNOWN)
    remote = _Remote(error)
    result = asyncio.run(_prober(repository, remote, _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:3",
    ))
    replay = asyncio.run(_prober(repository, remote, _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:3",
    ))
    assert result.status == "recovery_required" and replay.status == "recovery_required"
    assert len(remote.requests) == 1
    store.close()


def test_preflight_rejection_does_not_reserve_or_start_a_probe(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    remote = _Remote()

    result = asyncio.run(_prober(repository, remote, _Preflight(False, "actorops_maintenance_revision_changed")).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:4",
    ))

    assert result.status == "skipped"
    assert result.error_code == "actorops_maintenance_revision_changed"
    assert remote.requests == []
    assert repository.connection.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
    store.close()


def test_stale_queued_binding_version_cannot_start_a_probe(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    remote = _Remote()

    result = asyncio.run(_prober(repository, remote, _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:4",
        expected_binding_version=2,
    ))

    assert result.status == "skipped"
    assert remote.requests == []
    store.close()


def test_last_candidate_is_never_removed_by_auto_repair(tmp_path: Path) -> None:
    store, repository, route_id, _source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    with repository.transaction():
        for index in range(2):
            repository.create_attempt(
                attempt_id=f"failed-{index}", idempotency_key=f"failed-key-{index}",
                route_id=route_id, candidate_id="active", kind="probe", attempt_group_id="failed",
                attempt_index=index, route_generation=2, binding_version=None,
                target_fingerprint="f" * 64, reserved_usd=0.05,
            )
            repository.transition_attempt(f"failed-{index}", AttemptStatus.CREATED, AttemptStatus.STARTING)
            repository.transition_attempt(f"failed-{index}", AttemptStatus.STARTING, AttemptStatus.FAILED,
                                           error_class="candidate", error_code="bad_output")
        active = repository.get_candidate("active")
        repository.record_candidate_outcome("active", expected_generation=active.generation,
                                            succeeded=False, error_class="candidate", error_code="bad_output")
    outcome = repository.maintenance.protect_last_unhealthy(route_id)
    current = repository.get_candidate("active")
    assert outcome == "actorops_maintenance_last_candidate_protected"
    assert current.lifecycle is CandidateLifecycle.CERTIFIED
    assert current.assignment_role is AssignmentRole.ACTIVE
    store.close()


def test_successful_probe_replaces_an_unhealthy_non_last_candidate_atomically(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    with repository.transaction():
        manifest = _manifest("publisher/standby")
        repository.create_candidate(
            candidate_id="standby", route_id=route_id, actor_id="publisher/standby",
            publisher="publisher", build_id="build-standby", build_number="1.0.0",
            manifest_json=manifest, manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
            input_schema_hash="a" * 64, output_schema_hash="b" * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
        repository.assign_candidate(
            route_id, "standby", AssignmentRole.STANDBY, priority=1,
            expected_route_generation=2, expected_candidate_generation=1,
        )
        for index in range(2):
            repository.create_attempt(
                attempt_id=f"active-failed-{index}", idempotency_key=f"active-key-{index}",
                route_id=route_id, candidate_id="active", kind="fetch", attempt_group_id="active-failed",
                attempt_index=index, route_generation=3, binding_version=None,
                target_fingerprint="f" * 64, reserved_usd=0.05,
            )
            repository.transition_attempt(f"active-failed-{index}", AttemptStatus.CREATED, AttemptStatus.STARTING)
            repository.transition_attempt(f"active-failed-{index}", AttemptStatus.STARTING, AttemptStatus.FAILED,
                                           error_class="candidate", error_code="bad_output")
        active = repository.get_candidate("active")
        repository.record_candidate_outcome(
            "active", expected_generation=active.generation, succeeded=False,
            error_class="candidate", error_code="bad_output",
        )

    result = asyncio.run(_prober(repository, _Remote(), _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:4",
    ))

    assert result.status == "promoted"
    assert repository.get_candidate("active").lifecycle is CandidateLifecycle.QUARANTINED
    assert repository.get_candidate("active").assignment_role is AssignmentRole.INACTIVE
    assert repository.get_candidate("standby").assignment_role is AssignmentRole.ACTIVE
    assert repository.get_candidate("candidate").assignment_role is AssignmentRole.STANDBY
    store.close()


def test_generic_maintenance_has_no_platform_or_publication_knowledge() -> None:
    source = Path("src/services/actorops/maintenance.py").read_text()
    repository = Path("src/services/actorops/repository_maintenance.py").read_text()
    assert "if platform" not in source
    assert "if platform" not in repository
    assert "publish_success" not in source
    assert "fetch_native_fallback" not in source
