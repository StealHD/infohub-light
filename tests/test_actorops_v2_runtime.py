from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models import ContentItem, SourceType
from src.apify_actor_identity import source_target_fingerprint
from src.services.apify_actor_manifest import actor_manifest_hash
from src.services.actorops.domain import CandidateLifecycle, FailureClass, RouteHealth
from src.services.actorops.ports import (
    FetchWindow,
    NativeFallbackResult,
    NormalizedBatch,
    RemoteRunResult,
    TargetSpec,
)
from src.services.actorops.registry import AdapterRegistry
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.runtime import ActorOpsRuntime, ActorOpsRuntimeError
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

    async def execute(self, request, events):
        self.requests.append(request)
        events.starting(secret_ref_id="secret-ref", secret_version=1, pool_generation=1)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        events.registered(remote_run_id=f"run-{len(self.requests)}", dataset_id="dataset")
        events.running()
        return RemoteRunResult(
            rows=({"semantic": outcome},),
            remote_run_id=f"run-{len(self.requests)}",
            dataset_id="dataset",
            actual_cost_usd=0.001,
            cost_final=True,
        )


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


def _runtime(tmp_path: Path, outcomes, *, candidate_count: int = 2, native: bool = False):
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
                manifest_hash=actor_manifest_hash(manifest_json),
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
                status, binding_version, source_v1_generation, created_at, updated_at
            ) VALUES ('binding-runtime', ?, ?, ?, ?, 'ready', 1, 1, ?, ?)""",
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
        tmp_path, ["suspicious_empty", "valid_nonempty"]
    )
    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-1",
    ))
    assert [request.candidate_id for request in remote.requests] == candidates
    assert result.candidate_id == candidates[1]
    assert len(result.items) == 1
    connection = store.connect()
    assert connection.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 2
    failed = connection.execute(
        "SELECT last_error_class, last_error_code FROM actor_candidates_v2 WHERE candidate_id=?",
        (candidates[0],),
    ).fetchone()
    assert tuple(failed) == ("candidate", "actorops_suspicious_empty")
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


def test_remote_unknown_never_starts_a_second_paid_candidate(tmp_path) -> None:
    error = ActorOpsRuntimeError(
        "actorops_remote_unknown", failure_class=FailureClass.REMOTE_UNKNOWN
    )
    store, _repository, runtime, remote, route_id, source_id, _ = _runtime(
        tmp_path, [error, "valid_nonempty"], native=True
    )
    result = asyncio.run(runtime.fetch(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        logical_job_id="job-unknown",
    ))
    assert len(remote.requests) == 1
    assert result.execution_mode == "native_fallback"
    attempt = store.connect().execute(
        "SELECT status, failure_class FROM actor_attempts_v2"
    ).fetchone()
    assert tuple(attempt) == ("start_unknown", "remote_unknown")
    candidate = store.connect().execute(
        "SELECT last_failure_at FROM actor_candidates_v2 WHERE assignment_role='active'"
    ).fetchone()
    assert candidate[0] is None
    store.close()


def test_settled_logical_attempt_replay_never_posts_again(tmp_path) -> None:
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
    asyncio.run(runtime.fetch(**kwargs))
    with pytest.raises(ActorOpsRuntimeError, match="already settled") as error:
        asyncio.run(runtime.fetch(**kwargs))
    assert error.value.code == "actorops_attempt_already_settled"
    assert len(remote.requests) == 1
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
