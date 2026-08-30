from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.api.actorops_v2_projection import actorops_v2_candidate_projection
from src.models import ContentItem, SourceType
from src.apify_actor_identity import source_target_fingerprint
from src.services.apify_actor_manifest import ActorManifestError, actor_manifest_hash
from src.services.actorops.domain import (
    AttemptStatus, CandidateLifecycle, FailureClass, RouteHealth,
)
from src.services.actorops.ports import (
    FetchWindow,
    NativeFallbackResult,
    NormalizedBatch,
    RemoteRunResult,
    TargetSpec,
)
from src.services.actorops.registry import AdapterRegistry
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.repository_freshness import SourceFreshnessRepository
from src.services.actorops.runtime import ActorOpsRuntime, ActorOpsRuntimeError
from src.services.actorops.runtime_candidate_health import (
    candidate_operational_states,
    operational_route_summary,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


class _Adapter:
    from src.services.actorops.domain import RouteKey

    route_key = RouteKey("test", "profile", "items")

    def __init__(self, *, native: bool = False) -> None:
        self.native = native

    def normalize_target(self, source_config):
        value = str(source_config["target"])
        return TargetSpec(canonical_url=f"https://example.com/{value}", handle=value)

    def discovery_spec(self):
        raise AssertionError("discovery is out of Phase 2 scope")

    def build_actor_input(self, target, manifest, window):
        return {"target": target.handle, "limit": window.max_items}

    def validate_output(self, rows, target, manifest, window):
        semantic = str(rows[0].get("semantic") if rows else "suspicious_empty")
        if semantic == "contract_invalid":
            raise ValueError("output contract mismatch")
        if semantic == "placeholder":
            raise ActorManifestError("apify_actor_placeholder", "placeholder")
        if semantic == "stale_window":
            return NormalizedBatch(
                (), "valid_empty",
                latest_published_at="2026-08-18T00:00:00+00:00",
                latest_item_id="stale-item",
            )
        items = ()
        if semantic == "valid_nonempty":
            items = (
                ContentItem(
                    id=f"actor:test:{target.handle}",
                    source_type=SourceType.TWITTER,
                    title="item",
                    url=f"https://example.com/{target.handle}/1",
                    content="body",
                    author=target.handle,
                    published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    metadata={"native_id": "1"},
                ),
            )
        return NormalizedBatch(
            items=items,
            semantic_outcome=semantic,
            latest_published_at=(
                "2026-08-20T00:00:00+00:00" if items else None
            ),
            latest_item_id="1" if items else None,
        )

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult(supported=self.native, degraded_reason="native")


class _Remote:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.requests = []
        self.dataset_reads = []
        self.datasets = {}

    async def execute(self, request, events):
        self.requests.append(request)
        events.starting(secret_ref_id="secret-ref", secret_version=1, pool_generation=1)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        events.registered(remote_run_id=f"run-{len(self.requests)}", dataset_id="dataset")
        events.running()
        self.datasets["dataset"] = ({"semantic": outcome},)
        return RemoteRunResult(
            rows=({"semantic": outcome},),
            remote_run_id=f"run-{len(self.requests)}",
            dataset_id="dataset",
            actual_cost_usd=0.001,
            cost_final=True,
        )

    async def read_dataset(self, dataset_id, *, max_items):
        self.dataset_reads.append((dataset_id, max_items))
        return self.datasets[dataset_id]


class _DeferredCredentialRemote(_Remote):
    def __init__(self) -> None:
        super().__init__(["valid_nonempty"])
        self.deferred = True

    async def execute(self, request, events):
        if self.deferred:
            self.deferred = False
            self.requests.append(request)
            raise ActorOpsRuntimeError(
                "actorops_credential_unavailable",
                failure_class=FailureClass.CREDENTIAL,
            )
        return await super().execute(request, events)


class _NonFinalRemote(_Remote):
    async def execute(self, request, events):
        result = await super().execute(request, events)
        return RemoteRunResult(
            rows=result.rows,
            remote_run_id=result.remote_run_id,
            dataset_id=result.dataset_id,
            actual_cost_usd=result.actual_cost_usd,
            cost_final=False,
        )


class _GenerationDriftRemote(_Remote):
    def __init__(self, repository: ActorOpsRepository) -> None:
        super().__init__(["valid_nonempty"])
        self.repository = repository

    async def execute(self, request, events):
        result = await super().execute(request, events)
        with self.repository.transaction():
            self.repository.connection.execute(
                """UPDATE actor_candidates_v2
                      SET assignment_role='inactive', priority=NULL,
                          generation=generation+1
                    WHERE workspace_id=? AND candidate_id=?""",
                (self.repository.workspace_id, request.candidate_id),
            )
        return result


def _manifest(actor_id: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "actor_id": actor_id,
            "build_number": "1.0.0",
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
        }
    )


def _runtime(
    tmp_path: Path,
    outcomes,
    *,
    candidate_count: int = 2,
    native: bool = False,
    invalid_active: bool = False,
):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    route = connection.execute(
        "SELECT * FROM actor_routes_v2 WHERE platform = 'x'"
    ).fetchone()
    connection.execute(
        "UPDATE actor_routes_v2 SET platform='test', runtime_mode='active' WHERE route_id=?",
        (route["route_id"],),
    )
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Runtime source",
        config={"platform": "test", "kind": "profile", "target": "openai"},
    )
    fingerprint = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID, str(route["route_id"]), "openai", platform="test"
    )
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    candidates = []
    with repository.transaction():
        for index in range(candidate_count):
            candidate_id = f"candidate-{index}"
            actor_id = f"publisher/actor-{index}"
            manifest_json = _manifest(actor_id)
            repository.create_candidate(
                candidate_id=candidate_id,
                route_id=str(route["route_id"]),
                actor_id=actor_id,
                publisher=f"publisher-{index}",
                build_id=f"build-{index}",
                build_number="1.0.0",
                manifest_json=manifest_json,
                manifest_hash=(
                    "0" * 64
                    if invalid_active and index == 0
                    else actor_manifest_hash(manifest_json)
                ),
                input_schema_hash="a" * 64,
                output_schema_hash="b" * 64,
                lifecycle=CandidateLifecycle.CERTIFIED,
            )
            role = "active" if index == 0 else "standby"
            connection.execute(
                "UPDATE actor_candidates_v2 SET assignment_role=?, priority=? WHERE candidate_id=?",
                (role, index, candidate_id),
            )
            candidates.append(candidate_id)
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                binding_id, workspace_id, source_id, route_id, target_fingerprint,
                status, binding_version, created_at, updated_at
            ) VALUES ('binding-runtime', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (
                DEFAULT_WORKSPACE_ID,
                source_id,
                route["route_id"],
                fingerprint,
                "2026-08-20T00:00:00+00:00",
                "2026-08-20T00:00:00+00:00",
            ),
        )
    registry = AdapterRegistry()
    registry.register(_Adapter(native=native))
    remote = _Remote(outcomes)
    runtime = ActorOpsRuntime(repository, registry, remote, id_factory=lambda: f"id-{len(remote.requests)}")
    return store, repository, runtime, remote, str(route["route_id"]), source_id, candidates


def test_runtime_fails_over_candidate_errors_and_keeps_one_ready_degraded(tmp_path) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["placeholder", "valid_nonempty"]
    )
    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-1",
    ))
    assert [request.candidate_id for request in remote.requests] == candidates
    assert result.candidate_id == candidates[1] and len(result.items) == 1
    connection = store.connect()
    assert connection.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 2
    failed = connection.execute(
        "SELECT last_error_class, last_error_code FROM actor_candidates_v2 WHERE candidate_id=?",
        (candidates[0],),
    ).fetchone()
    assert tuple(failed) == ("candidate", "apify_actor_placeholder")
    connection.execute(
        "UPDATE actor_candidates_v2 SET lifecycle='disabled', assignment_role='inactive', priority=NULL WHERE candidate_id=?",
        (candidates[1],),
    )
    connection.commit()
    assert repository.route_health(route_id) is RouteHealth.DEGRADED
    store.close()


def test_valid_empty_stops_without_standby_or_native(tmp_path) -> None:
    store, _repository, runtime, remote, route_id, source_id, _ = _runtime(
        tmp_path, ["valid_empty", "valid_nonempty"], native=True
    )
    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-empty",
    ))
    assert result.items == ()
    assert len(remote.requests) == 1
    assert result.execution_mode == "actor"
    store.close()


def test_watermark_no_advance_stops_but_stale_regression_tries_standby(tmp_path) -> None:
    store, _repository, runtime, remote, route_id, source_id, _ = _runtime(
        tmp_path, ["valid_nonempty", "valid_nonempty", "valid_nonempty"], native=True
    )
    connection = store.connect()
    connection.execute(
        """UPDATE actor_source_bindings_v2
           SET watermark_latest_published_at=?, watermark_item_id_hash=?
           WHERE source_id=?""",
        (
            "2026-08-20T00:00:00+00:00",
            hashlib.sha256(b"1").hexdigest(),
            source_id,
        ),
    )
    connection.commit()
    kwargs = dict(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-no-advance",
    )
    result = asyncio.run(runtime.fetch(**kwargs))
    assert result.semantic_outcome == "no_advance"
    assert len(remote.requests) == 1

    connection.execute(
        "UPDATE actor_source_bindings_v2 SET watermark_latest_published_at=? WHERE source_id=?",
        ("2026-08-21T00:00:00+00:00", source_id),
    )
    connection.commit()
    result = asyncio.run(runtime.fetch(**{**kwargs, "logical_job_id": "job-stale"}))
    assert result.execution_mode == "native_fallback"
    assert len(remote.requests) == 3
    store.close()


def test_window_filtered_stale_rows_try_standby_instead_of_stopping_empty(
    tmp_path,
) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["stale_window", "valid_nonempty"]
    )
    connection = store.connect()
    connection.execute(
        """UPDATE actor_source_bindings_v2
           SET watermark_latest_published_at=?, watermark_item_id_hash=?
           WHERE source_id=?""",
        (
            "2026-08-20T00:00:00+00:00",
            hashlib.sha256(b"watermark-item").hexdigest(),
            source_id,
        ),
    )
    connection.commit()

    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-window-stale",
    ))

    assert result.candidate_id == candidates[1]
    assert [request.candidate_id for request in remote.requests] == list(candidates)
    failed = connection.execute(
        "SELECT semantic_outcome, cost_final FROM actor_attempts_v2 WHERE candidate_id=?",
        (candidates[0],),
    ).fetchone()
    assert tuple(failed) == ("stale_regression", 1)
    store.close()


def test_proven_start_rejection_settles_zero_and_tries_standby(tmp_path) -> None:
    rejected = ActorOpsRuntimeError(
        "apify_actor_start_rejected",
        failure_class=FailureClass.CANDIDATE,
        proven_no_start=True,
    )
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, [rejected, "valid_nonempty"]
    )

    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-start-rejected",
    ))

    assert result.candidate_id == candidates[1]
    first = store.connect().execute(
        """SELECT status, actual_cost_usd, cost_final, error_code
           FROM actor_attempts_v2 WHERE candidate_id=?""",
        (candidates[0],),
    ).fetchone()
    assert tuple(first) == (
        "failed", 0.0, 1, "apify_actor_start_rejected"
    )
    assert len(remote.requests) == 2
    store.close()


def test_repeated_settled_start_rejection_is_skipped_on_later_jobs(tmp_path) -> None:
    rejected = ActorOpsRuntimeError(
        "apify_actor_start_rejected",
        failure_class=FailureClass.CANDIDATE,
        proven_no_start=True,
    )
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path,
        [rejected, "valid_nonempty", rejected, "valid_nonempty", "valid_nonempty"],
    )
    kwargs = {
        "route_id": route_id,
        "source_id": source_id,
        "source_config": {"target": "openai"},
        "window": FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
    }

    asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-rejected-1"))
    recent = actorops_v2_candidate_projection(
        repository, repository.get_candidate(candidates[0])
    )
    assert recent["operational_status"] == "recent_failure"
    assert recent["issue_code"] == "candidate_failure"

    asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-rejected-2"))
    confirmed = actorops_v2_candidate_projection(
        repository, repository.get_candidate(candidates[0])
    )
    assert confirmed["operational_status"] == "confirmed_failure"
    assert confirmed["issue_code"] == "repeated_start_rejection"
    result = asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-rejected-3"))

    assert result.candidate_id == candidates[1]
    assert [request.candidate_id for request in remote.requests] == [
        candidates[0], candidates[1], candidates[0], candidates[1], candidates[1]
    ]
    store.close()


def test_success_resets_start_rejection_evidence_before_a_later_failure(
    tmp_path,
) -> None:
    rejected = ActorOpsRuntimeError(
        "apify_actor_start_rejected",
        failure_class=FailureClass.CANDIDATE,
        proven_no_start=True,
    )
    store, repository, runtime, _remote, route_id, source_id, candidates = _runtime(
        tmp_path,
        [rejected, "valid_nonempty", "valid_nonempty", rejected, "valid_nonempty"],
    )
    kwargs = {
        "route_id": route_id,
        "source_id": source_id,
        "source_config": {"target": "openai"},
        "window": FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
    }

    asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-reset-1"))
    asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-reset-success"))
    asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-reset-2"))

    projection = actorops_v2_candidate_projection(
        repository, repository.get_candidate(candidates[0])
    )
    assert projection["operational_status"] == "recent_failure"
    assert projection["issue_code"] == "candidate_failure"
    store.close()


def test_paid_failures_on_two_bindings_confirm_candidate_globally(tmp_path) -> None:
    store, repository, runtime, _remote, route_id, source_id, candidates = _runtime(
        tmp_path,
        ["suspicious_empty", "valid_nonempty", "suspicious_empty", "valid_nonempty"],
    )
    second_source = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Second runtime source",
        config={"platform": "test", "kind": "profile", "target": "second"},
    )
    second_fingerprint = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID, route_id, "second", platform="test"
    )
    with repository.transaction():
        repository.connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version, created_at, updated_at
               ) VALUES ('binding-runtime-second', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (
                DEFAULT_WORKSPACE_ID, second_source, route_id, second_fingerprint,
                "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00",
            ),
        )
    window = FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None)

    asyncio.run(runtime.fetch(
        route_id=route_id, source_id=source_id,
        source_config={"target": "openai"}, window=window,
        logical_job_id="job-paid-binding-1",
    ))
    asyncio.run(runtime.fetch(
        route_id=route_id, source_id=second_source,
        source_config={"target": "second"}, window=window,
        logical_job_id="job-paid-binding-2",
    ))

    state = actorops_v2_candidate_projection(
        repository, repository.get_candidate(candidates[0])
    )
    assert state["operational_status"] == "confirmed_failure"
    assert state["issue_code"] == "candidate_failure"
    summary = operational_route_summary(
        repository, repository.list_route_candidates(route_id)
    )
    assert summary.health is RouteHealth.DEGRADED
    assert summary.stable_candidate_count == 1
    store.close()


def test_cross_binding_paid_failures_must_both_be_within_twenty_four_hours(
    tmp_path,
) -> None:
    store, repository, _runtime_service, _remote, route_id, source_id, candidates = _runtime(
        tmp_path, [], candidate_count=2
    )
    second_source = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Second boundary source",
        config={"platform": "test", "kind": "profile", "target": "second"},
    )
    second_fingerprint = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID, route_id, "second", platform="test"
    )
    with repository.transaction():
        repository.connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version, created_at, updated_at
               ) VALUES ('binding-boundary-second', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (
                DEFAULT_WORKSPACE_ID, second_source, route_id, second_fingerprint,
                "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00",
            ),
        )
    now = datetime.now(timezone.utc)
    for index, (current_source, fingerprint, stamp) in enumerate((
        (source_id, repository.get_binding(source_id).target_fingerprint, now - timedelta(hours=25)),
        (second_source, second_fingerprint, now - timedelta(hours=1)),
    )):
        attempt_id = f"attempt-cross-binding-boundary-{index}"
        with repository.transaction():
            repository.create_attempt(
                attempt_id=attempt_id,
                idempotency_key=f"key-cross-binding-boundary-{index}",
                route_id=route_id,
                source_id=current_source,
                candidate_id=candidates[0],
                kind="fetch",
                attempt_group_id="group-cross-binding-boundary",
                attempt_index=index,
                route_generation=repository.get_route(route_id).generation,
                binding_version=1,
                target_fingerprint=fingerprint,
                reserved_usd=0.1,
                logical_job_id=f"job-cross-binding-boundary-{index}",
            )
            repository.transition_attempt(
                attempt_id, AttemptStatus.CREATED, AttemptStatus.STARTING
            )
            repository.complete_attempt(
                attempt_id,
                status=AttemptStatus.FAILED,
                semantic_outcome="actorops_suspicious_empty",
                actual_cost_usd=0.01,
                cost_final=True,
                failure_class=FailureClass.CANDIDATE.value,
                error_code="actorops_suspicious_empty",
            )
            repository.connection.execute(
                "UPDATE actor_attempts_v2 SET updated_at=? WHERE attempt_id=?",
                (stamp.isoformat(), attempt_id),
            )
    with repository.transaction():
        repository.connection.execute(
            """UPDATE actor_candidates_v2
                  SET last_failure_at=?, last_error_class='candidate',
                      last_error_code='actorops_suspicious_empty'
                WHERE candidate_id=?""",
            ((now - timedelta(hours=1)).isoformat(), candidates[0]),
        )

    state = candidate_operational_states(
        repository, (repository.get_candidate(candidates[0]),), now=now
    )[candidates[0]]
    assert state.status == "recent_failure"
    assert state.issue_code == "candidate_failure"
    store.close()


def test_route_health_is_calculated_per_binding_with_inactive_lkg(tmp_path) -> None:
    store, repository, _runtime_service, _remote, route_id, source_id, candidates = _runtime(
        tmp_path, [], candidate_count=2
    )
    second_source = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Second health source",
        config={"platform": "test", "kind": "profile", "target": "second"},
    )
    second_fingerprint = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID, route_id, "second", platform="test"
    )
    with repository.transaction():
        repository.connection.execute(
            """UPDATE actor_candidates_v2
                  SET assignment_role='inactive', priority=NULL
                WHERE candidate_id=?""",
            (candidates[1],),
        )
        repository.connection.execute(
            """UPDATE actor_source_bindings_v2
                  SET last_known_good_candidate_id=? WHERE source_id=?""",
            (candidates[1], source_id),
        )
        repository.connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version, created_at, updated_at
               ) VALUES ('binding-health-second', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (
                DEFAULT_WORKSPACE_ID, second_source, route_id, second_fingerprint,
                "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00",
            ),
        )
    route_candidates = repository.list_route_candidates(route_id)

    lkg_binding = operational_route_summary(
        repository,
        route_candidates,
        route_id=route_id,
        source_id=source_id,
    )
    single_path_binding = operational_route_summary(
        repository,
        route_candidates,
        route_id=route_id,
        source_id=second_source,
    )
    whole_route = operational_route_summary(
        repository, route_candidates, route_id=route_id
    )

    assert lkg_binding.health is RouteHealth.HEALTHY
    assert lkg_binding.stable_candidate_count == 2
    assert single_path_binding.health is RouteHealth.DEGRADED
    assert single_path_binding.stable_candidate_count == 1
    assert whole_route.health is RouteHealth.DEGRADED
    assert whole_route.at_risk_source_count == 1
    store.close()


def test_zero_candidate_route_uses_explicit_route_fallback_evidence(tmp_path) -> None:
    store, repository, _runtime_service, _remote, route_id, source_id, _ = _runtime(
        tmp_path, [], candidate_count=0
    )
    before = operational_route_summary(
        repository, (), route_id=route_id, source_id=source_id
    )
    repository.resilience.emit(
        root_job_id="job-zero-candidate-fallback",
        route_id=route_id,
        source_id=source_id,
        phase="native_fallback",
        outcome="fallback",
    )
    after = operational_route_summary(
        repository, (), route_id=route_id, source_id=source_id
    )

    assert before.health is RouteHealth.UNAVAILABLE
    assert after.health is RouteHealth.DEGRADED
    assert after.health_reason == "source_fallback_only"
    assert after.fallback_source_count == 1
    store.close()


def test_native_fallback_still_creates_repair_and_exhaustion_is_not_retryable(
    tmp_path,
) -> None:
    store, repository, runtime, _remote, route_id, source_id, _ = _runtime(
        tmp_path, ["suspicious_empty", "suspicious_empty"], native=True
    )
    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-native-repair",
    ))

    assert result.execution_mode == "native_fallback"
    repair = repository.connection.execute(
        """SELECT trigger_code, status FROM actor_route_repairs_v2
           WHERE source_id=?""",
        (source_id,),
    ).fetchone()
    assert repair["trigger_code"] == "actorops_route_exhausted"
    assert repair["status"] in {"queued", "blocked"}

    repository.connection.execute(
        """UPDATE actor_source_candidate_freshness_v2
              SET cooldown_until=? WHERE source_id=?""",
        ((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), source_id),
    )
    repository.connection.commit()
    runtime.registry = AdapterRegistry()
    runtime.registry.register(_Adapter(native=False))
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id="job-exhausted-nonretryable",
        ))
    assert caught.value.code == "actorops_v2_route_unavailable"
    assert caught.value.retryable is False
    store.close()


def test_stale_regression_cools_source_candidate_before_next_paid_job(
    tmp_path,
) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["stale_window", "stale_window", "valid_nonempty"]
    )
    repository.connection.execute(
        """UPDATE actor_source_bindings_v2
           SET watermark_latest_published_at=?, watermark_item_id_hash=?
           WHERE source_id=?""",
        (
            "2026-08-20T00:00:00+00:00",
            hashlib.sha256(b"watermark-item").hexdigest(),
            source_id,
        ),
    )
    repository.connection.commit()
    kwargs = {
        "route_id": route_id,
        "source_id": source_id,
        "source_config": {"target": "openai"},
        "window": FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
    }

    with pytest.raises(ActorOpsRuntimeError) as first:
        asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-stale-cooldown-1"))
    with pytest.raises(ActorOpsRuntimeError) as second:
        asyncio.run(runtime.fetch(**kwargs, logical_job_id="job-stale-cooldown-2"))

    assert first.value.code == "actorops_v2_route_unavailable"
    assert second.value.code == "actorops_v2_route_unavailable"
    assert [request.candidate_id for request in remote.requests] == candidates
    rows = repository.connection.execute(
        """SELECT candidate_id, state, cooldown_until, last_outcome
           FROM actor_source_candidate_freshness_v2
           WHERE source_id=? ORDER BY candidate_id""",
        (source_id,),
    ).fetchall()
    assert [tuple(row)[:2] for row in rows] == [
        (candidates[0], "source_stale"),
        (candidates[1], "source_stale"),
    ]
    assert all(row["cooldown_until"] for row in rows)
    assert {row["last_outcome"] for row in rows} == {"stale_regression"}
    store.close()


def test_unproven_start_rejection_keeps_cost_unknown_and_blocks_standby(
    tmp_path,
) -> None:
    rejected = ActorOpsRuntimeError(
        "apify_actor_start_rejected", failure_class=FailureClass.CANDIDATE
    )
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, [rejected, "valid_nonempty"]
    )

    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id="job-unproven-start-rejected",
        ))

    assert caught.value.code == "actorops_cost_settlement_required"
    attempt = store.connect().execute(
        "SELECT actual_cost_usd, cost_final FROM actor_attempts_v2"
    ).fetchone()
    assert tuple(attempt) == (None, 0)
    assert len(remote.requests) == 1
    candidate = actorops_v2_candidate_projection(
        repository, repository.get_candidate(candidates[0])
    )
    assert candidate["operational_status"] == "recent_failure"
    assert candidate["issue_code"] == "candidate_failure"
    store.close()


def test_disabled_route_never_posts_or_creates_attempt(tmp_path) -> None:
    store, repository, runtime, remote, route_id, source_id, _ = _runtime(
        tmp_path, ["valid_nonempty"], native=False
    )
    with repository.transaction():
        repository.connection.execute(
            "UPDATE actor_routes_v2 SET runtime_mode='disabled' WHERE route_id=?",
            (route_id,),
        )

    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(
            runtime.fetch(
                route_id=route_id,
                source_id=source_id,
                source_config={"target": "openai"},
                window=FetchWindow(
                    3, datetime(2026, 8, 19, tzinfo=timezone.utc), None
                ),
                logical_job_id="job-disabled-route",
            )
        )

    assert caught.value.code == "actorops_v2_route_disabled"
    assert remote.requests == []
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM actor_attempts_v2 WHERE source_id=?",
        (source_id,),
    ).fetchone()[0] == 0
    store.close()


def test_remote_unknown_never_starts_a_second_paid_candidate(tmp_path) -> None:
    error = ActorOpsRuntimeError(
        "actorops_remote_unknown", failure_class=FailureClass.REMOTE_UNKNOWN
    )
    store, _repository, runtime, remote, route_id, source_id, _ = _runtime(
        tmp_path, [error, "valid_nonempty"], native=True
    )
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id="job-unknown",
        ))
    assert len(remote.requests) == 1
    assert caught.value.failure_class is FailureClass.REMOTE_UNKNOWN
    attempt = store.connect().execute(
        "SELECT status, failure_class FROM actor_attempts_v2"
    ).fetchone()
    assert tuple(attempt) == ("start_unknown", "remote_unknown")
    candidate = store.connect().execute(
        "SELECT last_failure_at FROM actor_candidates_v2 WHERE assignment_role='active'"
    ).fetchone()
    assert candidate[0] is None
    store.close()


def test_settled_logical_attempt_replays_dataset_without_posting_again(tmp_path) -> None:
    store, _repository, runtime, remote, route_id, source_id, _ = _runtime(
        tmp_path, ["valid_nonempty"]
    )
    kwargs = dict(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-replay",
    )
    first = asyncio.run(runtime.fetch(**kwargs))
    replay = asyncio.run(runtime.fetch(**{
        **kwargs,
        "window": FetchWindow(
            99,
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 22, tzinfo=timezone.utc),
        ),
    }))
    assert [item.id for item in replay.items] == [item.id for item in first.items]
    assert len(remote.requests) == 1
    assert remote.dataset_reads == [("dataset", 3)]
    attempt = store.connect().execute(
        """SELECT logical_job_id, request_schema_version, window_since,
                  window_until, max_items, result_state, result_observed_at
           FROM actor_attempts_v2"""
    ).fetchone()
    assert tuple(attempt[:2]) == ("job-replay", 2)
    assert attempt[2] == "2026-08-19T00:00:00+00:00"
    assert attempt[3] is None
    assert attempt[4] == 3
    assert attempt[5] == "validated"
    assert attempt[6]
    store.close()


def test_candidate_reordering_does_not_change_attempt_identity(tmp_path) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["valid_nonempty"]
    )
    kwargs = dict(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-reordered",
    )
    asyncio.run(runtime.fetch(**kwargs))
    with repository.transaction():
        repository.promote_standby_candidate(
            route_id,
            candidates[1],
            expected_route_generation=repository.get_route(route_id).generation,
            expected_candidate_generation=repository.get_candidate(
                candidates[1]
            ).generation,
        )
    connection = store.connect()
    asyncio.run(runtime.fetch(**kwargs))
    assert len(remote.requests) == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM actor_attempts_v2 WHERE logical_job_id='job-reordered'"
    ).fetchone()[0] == 1
    store.close()


def test_output_failure_preserves_observed_dataset_and_known_cost(tmp_path) -> None:
    store, _repository, runtime, remote, route_id, source_id, _ = _runtime(
        tmp_path, ["contract_invalid"], candidate_count=1
    )
    with pytest.raises(ActorOpsRuntimeError):
        asyncio.run(runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id="job-contract-failure",
        ))
    row = store.connect().execute(
        """SELECT status, dataset_id, actual_cost_usd, cost_final, result_state
           FROM actor_attempts_v2"""
    ).fetchone()
    assert tuple(row) == ("failed", "dataset", pytest.approx(0.001), 1, "observed")
    store.close()


def test_created_attempt_without_credential_reuses_frozen_request(tmp_path) -> None:
    store, repository, runtime, _remote, route_id, source_id, _ = _runtime(
        tmp_path, []
    )
    remote = _DeferredCredentialRemote()
    runtime.remote = remote
    kwargs = dict(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-created-recovery",
    )
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(**kwargs))
    assert caught.value.failure_class is FailureClass.CREDENTIAL
    result = asyncio.run(runtime.fetch(**{
        **kwargs,
        "window": FetchWindow(
            50,
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 22, tzinfo=timezone.utc),
        ),
    }))
    assert result.execution_mode == "actor"
    assert len(remote.requests) == 2
    assert {request.attempt_id for request in remote.requests} == {"id-0"}
    assert remote.requests[-1].actor_input["limit"] == 3
    assert remote.requests[-1].max_remote_starts == 1
    assert repository.get_attempt("id-0")["max_items"] == 3
    store.close()


def test_invalid_active_manifest_falls_through_to_standby(tmp_path) -> None:
    store, _repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["valid_nonempty"], invalid_active=True
    )

    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-invalid-active",
    ))

    assert result.candidate_id == candidates[1]
    assert [request.candidate_id for request in remote.requests] == [candidates[1]]
    store.close()


def test_non_final_candidate_cost_blocks_paid_standby(tmp_path) -> None:
    store, _repository, runtime, _remote, route_id, source_id, _ = _runtime(
        tmp_path, []
    )
    remote = _NonFinalRemote(["suspicious_empty", "valid_nonempty"])
    runtime.remote = remote

    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id="job-non-final",
        ))

    assert caught.value.code == "actorops_cost_settlement_required"
    assert len(remote.requests) == 1
    store.close()


def test_attempt_creation_rechecks_unsettled_cost_after_planning(
    tmp_path, monkeypatch
) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["valid_nonempty"], candidate_count=1
    )
    original = SourceFreshnessRepository.plan_candidates
    injected = False

    def inject_concurrent_attempt(self, **values):
        nonlocal injected
        plan = original(self, **values)
        if injected:
            return plan
        injected = True
        binding = values["binding"]
        with repository.transaction():
            repository.create_attempt(
                attempt_id="attempt-concurrent-cost",
                idempotency_key="key-concurrent-cost",
                route_id=route_id,
                source_id=source_id,
                candidate_id=candidates[0],
                kind="fetch",
                attempt_group_id="group-concurrent-cost",
                attempt_index=0,
                route_generation=repository.get_route(route_id).generation,
                binding_version=binding.binding_version,
                target_fingerprint=binding.target_fingerprint,
                reserved_usd=0.1,
                logical_job_id="other-source-job",
            )
        return plan

    monkeypatch.setattr(
        SourceFreshnessRepository, "plan_candidates", inject_concurrent_attempt
    )
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id="racing-source-job",
        ))

    assert caught.value.code == "actorops_cost_settlement_required"
    assert remote.requests == []
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM actor_attempts_v2"
    ).fetchone()[0] == 1
    store.close()


def test_runtime_outcome_survives_assignment_generation_drift(tmp_path) -> None:
    store, repository, runtime, _remote, route_id, source_id, candidates = _runtime(
        tmp_path, [], candidate_count=1
    )
    remote = _GenerationDriftRemote(repository)
    runtime.remote = remote

    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-generation-drift",
    ))

    row = repository.connection.execute(
        """SELECT assignment_role, priority, last_success_at, last_error_code
             FROM actor_candidates_v2 WHERE candidate_id=?""",
        (candidates[0],),
    ).fetchone()
    assert result.candidate_id == candidates[0]
    assert tuple(row[:2]) == ("inactive", None)
    assert row["last_success_at"]
    assert row["last_error_code"] is None
    store.close()


def test_terminal_non_final_cost_is_reconciler_only(tmp_path) -> None:
    store, _repository, runtime, _remote, route_id, source_id, _ = _runtime(
        tmp_path, []
    )
    remote = _NonFinalRemote(["valid_nonempty"])
    runtime.remote = remote
    kwargs = dict(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-terminal-non-final",
    )
    assert asyncio.run(runtime.fetch(**kwargs)).execution_mode == "actor"

    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(**kwargs))

    assert caught.value.code == "actorops_cost_settlement_required"
    assert len(remote.requests) == 1
    assert remote.dataset_reads == []
    store.close()


def test_publication_fence_is_local_to_binding_target_and_actual_candidate(tmp_path) -> None:
    store, repository, _runtime_service, _remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["valid_nonempty"]
    )
    snapshot = repository.freeze_execution(
        route_id,
        source_id,
        source_target_fingerprint(
            DEFAULT_WORKSPACE_ID, route_id, "openai", platform="test"
        ),
    )
    proof = repository.publication_proof(snapshot, candidates[0])
    connection = store.connect()
    connection.execute("UPDATE actor_routes_v2 SET generation=generation+1 WHERE route_id=?", (route_id,))
    connection.execute(
        "UPDATE actor_candidates_v2 SET assignment_role='inactive', priority=NULL WHERE candidate_id=?",
        (candidates[0],),
    )
    connection.commit()
    repository.assert_publishable(proof)
    connection.execute(
        "UPDATE actor_candidates_v2 SET lifecycle='disabled' WHERE candidate_id=?",
        (candidates[0],),
    )
    connection.commit()
    with pytest.raises(ActorOpsConflict):
        repository.assert_publishable(proof)
    connection.execute(
        "UPDATE actor_source_bindings_v2 SET binding_version=binding_version+1 WHERE source_id=?",
        (source_id,),
    )
    connection.commit()
    with pytest.raises(ActorOpsConflict):
        repository.assert_publishable(proof)
    store.close()
