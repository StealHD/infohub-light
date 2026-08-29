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
    ReconciliationRunLink,
    ReconciliationRunObservation,
    ReconciliationRunResolution,
    RemoteRunResult,
    TargetSpec,
)
from src.services.actorops.reconciliation import ActorOpsReconciler
from src.services.actorops.registry import AdapterRegistry
from src.services.actorops.recovery_probe import RECOVERY_INTENT
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.repository_resilience import ResilienceRepository
from src.services.actorops.runtime import ActorOpsRuntimeError
from src.services.actorops.runtime_candidate_health import candidate_operational_states
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
    def __init__(
        self,
        outcome: object = "ok",
        run_id: str = "run-one",
        *,
        cost_final: bool = True,
    ) -> None:
        self.outcome = outcome
        self.run_id = run_id
        self.cost_final = cost_final
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
            dataset_id="dataset-one", actual_cost_usd=0.01,
            cost_final=self.cost_final,
        )


class _SettlingLedger:
    async def resolve(self, attempt):
        return ReconciliationRunResolution(ReconciliationRunLink(
            reservation_id="recovery-reservation",
            remote_run_id=str(attempt["remote_run_id"]),
            dataset_id=str(attempt["dataset_id"]),
            status="succeeded",
            created_at=str(attempt["created_at"]),
            updated_at=str(attempt["updated_at"]),
        ))

    async def read_known(self, link):
        return ReconciliationRunObservation(
            "succeeded", 0.01, True, link.dataset_id
        )

    async def prove_no_start(self, _link):
        raise AssertionError("settled recovery has a known Run")

    async def settle_proven_no_start(self, _link):
        raise AssertionError("settled recovery has a known Run")


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


def _confirmed_active(repository: ActorOpsRepository, source_id: str):
    with repository.transaction():
        candidate = repository.get_candidate("active")
        failed = repository.record_candidate_outcome(
            candidate.candidate_id,
            expected_generation=candidate.generation,
            succeeded=False,
            error_class="candidate",
            error_code="apify_actor_build_unavailable",
        )
    binding = repository.get_binding(source_id)
    repository.resilience.record_paid_candidate_failure(
        binding=binding,
        candidate_id=failed.candidate_id,
        logical_job_id="recovery-trigger",
    )
    failure_at = candidate_operational_states(repository, (failed,))[
        failed.candidate_id
    ].last_failure_at
    return failed, binding, failure_at


def test_policy_requires_workspace_and_route_authorization_and_counts_reserved_budget(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    workspace = repository.maintenance.get_policy(None)
    route = repository.maintenance.get_policy(route_id)
    owner = repository.connection.execute(
        "SELECT id FROM users WHERE workspace_id=? AND role='owner'", (DEFAULT_WORKSPACE_ID,)
    ).fetchone()
    assert owner is not None
    assert workspace.enabled is True and route.enabled is True
    assert workspace.authorization_origin == "system_default"
    assert route.authorization_origin == "system_default"
    with pytest.raises(ActorOpsConflict, match="authorizer_invalid"):
        with repository.transaction():
            repository.maintenance.set_enabled(
                None, True, authorized_by_user_id="not-an-operator",
                expected_generation=workspace.generation,
            )
    with repository.transaction():
        repository.maintenance.set_enabled(
            route_id, False, authorized_by_user_id=None,
            expected_generation=route.generation,
        )
    with pytest.raises(ActorOpsConflict, match="not_authorized"):
        with repository.transaction():
            policies = repository.maintenance.effective_policy(route_id)
            repository.maintenance.reserve_probe(
                route_id=route_id, candidate_id="candidate", source_id=source_id,
                binding_version=1, target_fingerprint=repository.get_binding(source_id).target_fingerprint,
                idempotency_key="probe-one", attempt_id="probe-one", attempt_group_id="slot-one",
                expected_route_generation=2, expected_candidate_generation=1,
                expected_workspace_policy_generation=policies.workspace.generation,
                expected_route_policy_generation=policies.route.generation,
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


def test_system_default_uses_the_oldest_enabled_owner_or_admin(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = str(store.connect().execute(
        "SELECT route_id FROM actor_routes_v2 ORDER BY route_id LIMIT 1"
    ).fetchone()[0])
    repository = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    assert repository.maintenance.get_policy(None).enabled is True
    assert repository.maintenance.effective_policy(route_id).authorized is False
    admin = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID, username="maintenance-admin",
        password="safe-test-password", role="admin",
    )
    effective = repository.maintenance.effective_policy(route_id)
    assert effective.authorized is True
    assert effective.principal_user_id == str(admin["id"])
    store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID, username="maintenance-owner",
        password="safe-test-password", role="owner",
    )
    effective = repository.maintenance.effective_policy(route_id)
    assert effective.authorized is True
    assert effective.principal_user_id == str(admin["id"])
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
    assert remote.requests[0].dataset_item_limit == 4
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


@pytest.mark.parametrize(
    ("preflight_code", "persisted_code", "issue_code"),
    (
        (
            "actorops_maintenance_revision_changed",
            "apify_actor_build_unavailable",
            "build_unavailable",
        ),
        (
            "actorops_v2_candidate_contract_invalid",
            "actorops_v2_candidate_contract_invalid",
            "contract_invalid",
        ),
    ),
)
def test_hard_preflight_failure_records_zero_cost_candidate_fact_and_repairs(
    tmp_path: Path,
    preflight_code: str,
    persisted_code: str,
    issue_code: str,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    remote = _Remote()
    with repository.transaction():
        manifest = _manifest("publisher/candidate-two")
        repository.create_candidate(
            candidate_id="candidate-two",
            route_id=route_id,
            actor_id="publisher/candidate-two",
            publisher="publisher",
            build_id="build-candidate-two",
            build_number="1.0.0",
            manifest_json=manifest,
            manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
            input_schema_hash="a" * 64,
            output_schema_hash="b" * 64,
            lifecycle=CandidateLifecycle.STATIC_VALID,
        )

    result = asyncio.run(_prober(repository, remote, _Preflight(False, preflight_code)).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:4",
    ))

    assert result.status == "failed"
    assert result.error_code == preflight_code
    assert remote.requests == []
    assert repository.connection.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == 0
    failed = repository.get_candidate("candidate")
    state = candidate_operational_states(repository, (failed,))["candidate"]
    assert state.status == "confirmed_failure"
    assert state.issue_code == issue_code
    row = repository.connection.execute(
        "SELECT last_error_class, last_error_code FROM actor_candidates_v2 WHERE candidate_id='candidate'"
    ).fetchone()
    assert tuple(row) == ("candidate", persisted_code)
    repair = repository.connection.execute(
        """SELECT trigger_code, status FROM actor_route_repairs_v2
             WHERE workspace_id=? AND route_id=? AND source_id=?""",
        (DEFAULT_WORKSPACE_ID, route_id, source_id),
    ).fetchone()
    assert tuple(repair) == ("actorops_candidate_preflight_failed", "queued")
    next_target = repository.maintenance.probe_target(route_id)
    assert next_target is not None and next_target[0] == "candidate-two"
    store.close()


@pytest.mark.parametrize(
    "code",
    (
        "actorops_maintenance_preflight_unavailable",
        "actorops_maintenance_price_cap_exceeded",
        "actorops_maintenance_pricing_unavailable",
    ),
)
def test_transient_preflight_failure_is_deferred_without_candidate_penalty(
    tmp_path: Path,
    code: str,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    remote = _Remote()

    result = asyncio.run(_prober(
        repository,
        remote,
        _Preflight(False, code),
    ).probe(
        route_id=route_id,
        candidate_id="candidate",
        source_id=source_id,
        source_config={"target": "openai"},
        maintenance_slot="2026-08-20:4",
    ))

    assert result.status == "skipped"
    assert result.error_code == code
    assert remote.requests == []
    current = repository.get_candidate("candidate")
    assert current.generation == 1
    assert candidate_operational_states(repository, (current,))[
        "candidate"
    ].status == "normal"
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM actor_attempts_v2"
    ).fetchone()[0] == 0
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == 0
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM actor_route_repairs_v2"
    ).fetchone()[0] == 0
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
                                           error_class="candidate", error_code="apify_actor_build_unavailable")
        active = repository.get_candidate("active")
        repository.record_candidate_outcome("active", expected_generation=active.generation,
                                            succeeded=False, error_class="candidate",
                                            error_code="apify_actor_build_unavailable")
    outcome = repository.maintenance.protect_last_unhealthy(route_id)
    current = repository.get_candidate("active")
    assert outcome == "actorops_maintenance_last_candidate_protected"
    assert current.lifecycle is CandidateLifecycle.CERTIFIED
    assert current.assignment_role is AssignmentRole.ACTIVE
    store.close()


def test_successful_probe_never_auto_replaces_an_assigned_candidate(tmp_path: Path) -> None:
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
                                           error_class="candidate", error_code="apify_actor_build_unavailable")
        active = repository.get_candidate("active")
        repository.record_candidate_outcome(
            "active", expected_generation=active.generation, succeeded=False,
            error_class="candidate", error_code="apify_actor_build_unavailable",
        )

    result = asyncio.run(_prober(repository, _Remote(), _Preflight()).probe(
        route_id=route_id, candidate_id="candidate", source_id=source_id,
        source_config={"target": "openai"}, maintenance_slot="2026-08-20:4",
    ))

    assert result.status == "promoted"
    assert repository.get_candidate("active").lifecycle is CandidateLifecycle.CERTIFIED
    assert repository.get_candidate("active").assignment_role is AssignmentRole.ACTIVE
    assert repository.get_candidate("standby").assignment_role is AssignmentRole.STANDBY
    assert repository.get_candidate("candidate").assignment_role is AssignmentRole.INACTIVE
    assert repository.maintenance.get_policy(route_id).auto_replace_non_last is False
    store.close()


def test_operator_recovery_probe_restores_confirmed_assigned_candidate(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    failed, _binding, failure_at = _confirmed_active(repository, source_id)
    remote = _Remote()
    registry = AdapterRegistry()
    registry.register(_Adapter())
    prober = ActorOpsProber(
        repository,
        registry,
        remote,
        _Preflight(),
        id_factory=lambda: "recovery-attempt",
        now=lambda: datetime.now(timezone.utc),
    )
    route = repository.get_route(route_id)

    result = asyncio.run(prober.probe(
        route_id=route_id,
        candidate_id=failed.candidate_id,
        source_id=source_id,
        source_config={"target": "openai"},
        maintenance_slot="operator-recovery:success",
        expected_binding_version=1,
        intent=RECOVERY_INTENT,
        expected_route_generation=route.generation,
        expected_candidate_generation=failed.generation,
        expected_last_failure_at=failure_at,
    ))

    current = repository.get_candidate(failed.candidate_id)
    state = candidate_operational_states(repository, (current,))[current.candidate_id]
    circuit = repository.connection.execute(
        """SELECT state, cooldown_until FROM actor_source_candidate_freshness_v2
             WHERE workspace_id=? AND source_id=? AND candidate_id=?""",
        (DEFAULT_WORKSPACE_ID, source_id, current.candidate_id),
    ).fetchone()
    assert result.status == "recovered"
    assert current.assignment_role is AssignmentRole.ACTIVE
    assert current.lifecycle is CandidateLifecycle.CERTIFIED
    assert state.last_success_at > failure_at
    assert state.status == "normal"
    assert tuple(circuit) == ("neutral", None)
    assert len(remote.requests) == 1
    assert remote.requests[0].max_total_charge_usd == 0.05
    assert remote.requests[0].max_remote_starts == 1
    assert remote.requests[0].max_items == 1
    store.close()


def test_operator_recovery_waits_for_cost_then_reconciles_once(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    failed, _binding, failure_at = _confirmed_active(repository, source_id)
    registry = AdapterRegistry()
    registry.register(_Adapter())
    prober = ActorOpsProber(
        repository,
        registry,
        _Remote(cost_final=False),
        _Preflight(),
        id_factory=lambda: "pending-recovery-attempt",
        now=lambda: datetime.now(timezone.utc),
    )
    route = repository.get_route(route_id)

    result = asyncio.run(prober.probe(
        route_id=route_id,
        candidate_id=failed.candidate_id,
        source_id=source_id,
        source_config={"target": "openai"},
        maintenance_slot="operator-recovery:pending",
        expected_binding_version=1,
        intent=RECOVERY_INTENT,
        expected_route_generation=route.generation,
        expected_candidate_generation=failed.generation,
        expected_last_failure_at=failure_at,
    ))
    pending = repository.get_candidate(failed.candidate_id)
    assert result.status == "recovery_required"
    assert result.error_code == "actorops_maintenance_cost_pending"
    assert candidate_operational_states(repository, (pending,))[
        pending.candidate_id
    ].confirmed_failure

    attempt = repository.get_attempt(str(result.attempt_id))
    with repository.transaction():
        repository.reconcile_attempt(
            str(result.attempt_id),
            expected_status=AttemptStatus.SUCCEEDED,
            expected_generation=int(attempt["generation"]),
            target_status=None,
            remote_run_id=str(attempt["remote_run_id"]),
            dataset_id=str(attempt["dataset_id"]),
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.01,
            cost_final=True,
            failure_class=None,
            error_code=None,
        )
    first = repository.maintenance.reconcile_settled_candidates(route_id)
    second = repository.maintenance.reconcile_settled_candidates(route_id)
    recovered = repository.get_candidate(failed.candidate_id)
    state = candidate_operational_states(repository, (recovered,))[
        recovered.candidate_id
    ]

    assert first == 1
    assert second == 0
    assert state.status == "normal"
    assert recovered.assignment_role is AssignmentRole.ACTIVE
    assert state.last_success_at > failure_at
    store.close()


def test_reconciler_projects_pending_recovery_without_policy_and_retries_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    failed, _binding, failure_at = _confirmed_active(repository, source_id)
    registry = AdapterRegistry()
    registry.register(_Adapter())
    prober = ActorOpsProber(
        repository, registry, _Remote(cost_final=False), _Preflight(),
        id_factory=lambda: "reconciler-recovery-attempt",
        now=lambda: datetime.now(timezone.utc),
    )
    route = repository.get_route(route_id)
    result = asyncio.run(prober.probe(
        route_id=route_id, candidate_id=failed.candidate_id,
        source_id=source_id, source_config={"target": "openai"},
        maintenance_slot="operator-recovery:reconciler",
        expected_binding_version=1, intent=RECOVERY_INTENT,
        expected_route_generation=route.generation,
        expected_candidate_generation=failed.generation,
        expected_last_failure_at=failure_at,
    ))
    assert result.status == "recovery_required"
    with repository.transaction():
        workspace_policy = repository.maintenance.get_policy(None)
        route_policy = repository.maintenance.get_policy(route_id)
        repository.maintenance.set_enabled(
            None, False, authorized_by_user_id=None,
            expected_generation=workspace_policy.generation,
        )
        repository.maintenance.set_enabled(
            route_id, False, authorized_by_user_id=None,
            expected_generation=route_policy.generation,
        )
    assert repository.maintenance.effective_policy(route_id).authorized is False

    original = ResilienceRepository.record_candidate_success
    monkeypatch.setattr(
        ResilienceRepository, "record_candidate_success",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("circuit write")),
    )
    first = asyncio.run(
        ActorOpsReconciler(repository, _SettlingLedger()).reconcile()
    )
    pending_attempt = repository.get_attempt(str(result.attempt_id))
    pending_candidate = repository.get_candidate(failed.candidate_id)
    assert first.errors == 1
    assert pending_attempt["cost_final"] == 0
    assert candidate_operational_states(repository, (pending_candidate,))[
        pending_candidate.candidate_id
    ].confirmed_failure

    monkeypatch.setattr(
        ResilienceRepository, "record_candidate_success", original
    )
    second = asyncio.run(
        ActorOpsReconciler(repository, _SettlingLedger()).reconcile()
    )
    recovered = repository.get_candidate(failed.candidate_id)
    state = candidate_operational_states(repository, (recovered,))[
        recovered.candidate_id
    ]
    circuit = repository.connection.execute(
        """SELECT state, cooldown_until FROM actor_source_candidate_freshness_v2
             WHERE workspace_id=? AND source_id=? AND candidate_id=?""",
        (DEFAULT_WORKSPACE_ID, source_id, recovered.candidate_id),
    ).fetchone()
    assert second.settled == 1
    assert repository.get_attempt(str(result.attempt_id))["cost_final"] == 1
    assert state.status == "normal"
    assert state.last_success_at > failure_at
    assert tuple(circuit) == ("neutral", None)
    assert repository.maintenance.reconcile_settled_candidates(route_id) == 0
    assert asyncio.run(
        ActorOpsReconciler(repository, _SettlingLedger()).reconcile()
    ).scanned == 0
    store.close()


def test_operator_recovery_does_not_clear_a_newer_failure_during_probe(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    failed, _binding, failure_at = _confirmed_active(repository, source_id)

    class _FailingDuringProbe(_Remote):
        async def execute(self, request, events):
            result = await super().execute(request, events)
            with repository.transaction():
                current = repository.get_candidate(failed.candidate_id)
                repository.record_candidate_outcome(
                    current.candidate_id,
                    expected_generation=current.generation,
                    succeeded=False,
                    error_class="candidate",
                    error_code="apify_actor_deleted",
                )
            return result

    registry = AdapterRegistry()
    registry.register(_Adapter())
    prober = ActorOpsProber(
        repository,
        registry,
        _FailingDuringProbe(),
        _Preflight(),
        id_factory=lambda: "racing-recovery-attempt",
        now=lambda: datetime.now(timezone.utc),
    )
    route = repository.get_route(route_id)

    result = asyncio.run(prober.probe(
        route_id=route_id,
        candidate_id=failed.candidate_id,
        source_id=source_id,
        source_config={"target": "openai"},
        maintenance_slot="operator-recovery:racing-failure",
        expected_binding_version=1,
        intent=RECOVERY_INTENT,
        expected_route_generation=route.generation,
        expected_candidate_generation=failed.generation,
        expected_last_failure_at=failure_at,
    ))

    current = repository.get_candidate(failed.candidate_id)
    state = candidate_operational_states(repository, (current,))[current.candidate_id]
    assert result.status == "recovery_required"
    assert result.error_code == (
        "actorops_maintenance_candidate_reconciliation_required"
    )
    assert state.confirmed_failure
    assert state.issue_code == "actor_deleted"
    assert state.last_failure_at > failure_at
    assert current.assignment_role is AssignmentRole.ACTIVE
    assert repository.maintenance.reconcile_settled_candidates(route_id) == 0
    after_reconcile = repository.get_candidate(failed.candidate_id)
    assert candidate_operational_states(repository, (after_reconcile,))[
        after_reconcile.candidate_id
    ].issue_code == "actor_deleted"
    store.close()


def test_operator_recovery_rolls_back_health_if_circuit_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    _authorize(repository, route_id)
    failed, _binding, failure_at = _confirmed_active(repository, source_id)
    original = ResilienceRepository.record_candidate_success

    def fail_circuit(*_args, **_kwargs):
        raise OSError("injected circuit write failure")

    monkeypatch.setattr(
        ResilienceRepository, "record_candidate_success", fail_circuit
    )
    registry = AdapterRegistry()
    registry.register(_Adapter())
    prober = ActorOpsProber(
        repository,
        registry,
        _Remote(),
        _Preflight(),
        id_factory=lambda: "atomic-recovery-attempt",
        now=lambda: datetime.now(timezone.utc),
    )
    route = repository.get_route(route_id)

    result = asyncio.run(prober.probe(
        route_id=route_id,
        candidate_id=failed.candidate_id,
        source_id=source_id,
        source_config={"target": "openai"},
        maintenance_slot="operator-recovery:atomic-failure",
        expected_binding_version=1,
        intent=RECOVERY_INTENT,
        expected_route_generation=route.generation,
        expected_candidate_generation=failed.generation,
        expected_last_failure_at=failure_at,
    ))

    unchanged = repository.get_candidate(failed.candidate_id)
    state = candidate_operational_states(repository, (unchanged,))[
        unchanged.candidate_id
    ]
    circuit = repository.connection.execute(
        """SELECT state, cooldown_until FROM actor_source_candidate_freshness_v2
             WHERE workspace_id=? AND source_id=? AND candidate_id=?""",
        (DEFAULT_WORKSPACE_ID, source_id, unchanged.candidate_id),
    ).fetchone()
    assert result.status == "recovery_required"
    assert state.confirmed_failure
    assert state.last_success_at is None
    assert tuple(circuit)[0] == "source_stale"
    assert tuple(circuit)[1] is not None

    monkeypatch.setattr(
        ResilienceRepository, "record_candidate_success", original
    )
    replay = asyncio.run(prober.probe(
        route_id=route_id,
        candidate_id=failed.candidate_id,
        source_id=source_id,
        source_config={"target": "openai"},
        maintenance_slot="operator-recovery:atomic-failure",
        expected_binding_version=1,
        intent=RECOVERY_INTENT,
        expected_route_generation=route.generation,
        expected_candidate_generation=failed.generation,
        expected_last_failure_at=failure_at,
    ))
    assert replay.status == "recovered"
    assert replay.attempt_id == result.attempt_id
    assert repository.maintenance.reconcile_settled_candidates(route_id) == 0
    recovered = repository.get_candidate(failed.candidate_id)
    recovered_state = candidate_operational_states(repository, (recovered,))[
        recovered.candidate_id
    ]
    recovered_circuit = repository.connection.execute(
        """SELECT state, cooldown_until FROM actor_source_candidate_freshness_v2
             WHERE workspace_id=? AND source_id=? AND candidate_id=?""",
        (DEFAULT_WORKSPACE_ID, source_id, recovered.candidate_id),
    ).fetchone()
    assert recovered_state.status == "normal"
    assert tuple(recovered_circuit) == ("neutral", None)
    store.close()


def test_joint_probe_target_advances_past_a_candidate_without_an_unproved_binding(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    with repository.transaction():
        manifest = _manifest("publisher/candidate-two")
        repository.create_candidate(
            candidate_id="candidate-two", route_id=route_id,
            actor_id="publisher/candidate-two", publisher="publisher",
            build_id="build-candidate-two", build_number="1.0.0",
            manifest_json=manifest,
            manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
            input_schema_hash="a" * 64, output_schema_hash="b" * 64,
            lifecycle=CandidateLifecycle.STATIC_VALID,
        )
    first = repository.maintenance.probe_target(route_id)
    assert first is not None and first[0] == "candidate"
    binding = repository.get_binding(source_id)
    with repository.transaction():
        repository.create_attempt(
            attempt_id="candidate-proof", idempotency_key="candidate-proof",
            route_id=route_id, source_id=source_id, candidate_id="candidate",
            kind="probe", attempt_group_id="candidate-proof", attempt_index=0,
            route_generation=repository.get_route(route_id).generation,
            binding_version=binding.binding_version,
            target_fingerprint=binding.target_fingerprint, reserved_usd=0.05,
        )
        repository.update_attempt_start(
            "candidate-proof", expected_generation=1, secret_ref_id="ref",
            secret_version=1, pool_generation=1,
        )
        repository.register_attempt_run(
            "candidate-proof", expected_generation=2,
            remote_run_id="candidate-proof-run", dataset_id="dataset",
        )
        repository.transition_attempt(
            "candidate-proof", AttemptStatus.REGISTERED, AttemptStatus.RUNNING,
            expected_generation=3,
        )
        repository.complete_attempt(
            "candidate-proof", status=AttemptStatus.SUCCEEDED,
            semantic_outcome="valid_nonempty", actual_cost_usd=0,
            cost_final=True,
        )
    second = repository.maintenance.probe_target(route_id)
    assert second is not None and second[0] == "candidate-two"
    assert str(second[1]["source_id"]) == source_id
    store.close()


def test_generic_maintenance_has_no_platform_or_publication_knowledge() -> None:
    source = Path("src/services/actorops/maintenance.py").read_text()
    repository = Path("src/services/actorops/repository_maintenance.py").read_text()
    assert "if platform" not in source
    assert "if platform" not in repository
    assert "publish_success" not in source
    assert "fetch_native_fallback" not in source
