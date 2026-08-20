from __future__ import annotations

import asyncio
import hashlib

from src.apify_actor_identity import source_target_fingerprint
from src.services.actorops.apify_remote import _LocalAttemptCoordinator
from src.services.actorops.domain import CandidateLifecycle
from src.services.actorops.publication import (
    ActorOpsV2RoutedList,
    proof_from_items,
    with_publication_proof,
)
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.service import (
    ActorOpsCompatibilityService,
    V2ExecutionHandle,
    build_source_actorops_service,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _seed_ready_binding(store: ServiceStore) -> tuple[str, str]:
    connection = store.connect()
    route_id = str(
        connection.execute(
            "SELECT route_id FROM actor_routes_v2 WHERE platform='x'"
        ).fetchone()[0]
    )
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="v2 source",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="v2-service-candidate",
            route_id=route_id,
            actor_id="publisher/actor",
            publisher="publisher",
            build_id="build",
            build_number="1.0.0",
            manifest_json="{}",
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.CERTIFIED,
        )
        connection.execute(
            "UPDATE actor_candidates_v2 SET assignment_role='active', priority=0 WHERE candidate_id='v2-service-candidate'"
        )
        fingerprint = source_target_fingerprint(
            DEFAULT_WORKSPACE_ID, route_id, "openai", platform="x"
        )
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                binding_id, workspace_id, source_id, route_id, target_fingerprint,
                status, binding_version, source_v1_generation, created_at, updated_at
            ) VALUES ('v2-service-binding', ?, ?, ?, ?, 'ready', 1, 1, ?, ?)""",
            (
                DEFAULT_WORKSPACE_ID,
                source_id,
                route_id,
                fingerprint,
                "2026-08-20T00:00:00+00:00",
                "2026-08-20T00:00:00+00:00",
            ),
        )
    return route_id, source_id


def test_compatibility_service_uses_v2_only_for_active_routes(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id, source_id = _seed_ready_binding(store)
    service = ActorOpsCompatibilityService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    connection = store.connect()
    connection.execute(
        "UPDATE actor_routes_v2 SET runtime_mode='active' WHERE route_id=?", (route_id,)
    )
    connection.commit()
    assert isinstance(
        service.freeze_execution(route_id, source_id=source_id), V2ExecutionHandle
    )

    sentinel = object()
    service.v1.freeze_execution = lambda *_args, **_kwargs: sentinel
    for mode in ("shadow", "disabled"):
        connection.execute(
            "UPDATE actor_routes_v2 SET runtime_mode=? WHERE route_id=?",
            (mode, route_id),
        )
        connection.commit()
        assert service.freeze_execution(route_id, source_id=source_id) is sentinel
    connection.execute(
        "UPDATE actor_source_bindings_v2 SET status='pending' WHERE source_id=?",
        (source_id,),
    )
    connection.execute(
        "UPDATE actor_routes_v2 SET runtime_mode='shadow' WHERE route_id=?",
        (route_id,),
    )
    connection.commit()
    assert service.freeze_execution(route_id, source_id=source_id) is sentinel
    assert connection.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
    store.close()


def test_disabled_factory_does_not_query_v2_tables(tmp_path, monkeypatch) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "false")
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)
    build_source_actorops_service(store, workspace_id=DEFAULT_WORKSPACE_ID)
    assert not any("_v2" in statement.casefold() for statement in statements)
    store.close()


def test_v2_publication_proof_round_trips_through_cache_transport() -> None:
    proof = {
        "version": 2,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "route_id": "route",
        "source_id": "source",
        "target_fingerprint": "a" * 64,
        "binding_version": 1,
        "candidate_id": "candidate",
        "candidate_generation": 1,
        "latest_published_at": "2026-08-20T00:00:00+00:00",
        "latest_item_id_hash": hashlib.sha256(b"item").hexdigest(),
    }
    routed = ActorOpsV2RoutedList([], proof)
    assert proof_from_items(routed) == proof
    restored = with_publication_proof([], proof)
    assert isinstance(restored, ActorOpsV2RoutedList)
    assert proof_from_items(restored) == proof


def test_local_attempt_coordinator_never_calls_workspace_unknown_barriers() -> None:
    class Base:
        async def report_start_outcome_unknown(self, *_args, **_kwargs):
            raise AssertionError("workspace start barrier must stay untouched")

        async def block_run_reconciliation(self, *_args, **_kwargs):
            raise AssertionError("workspace reconcile barrier must stay untouched")

    class Events:
        def __init__(self):
            self.values = []

        def start_unknown(self, *, error_code):
            self.values.append(("start", error_code))

        def remote_unknown(self, *, error_code):
            self.values.append(("remote", error_code))

    events = Events()
    coordinator = _LocalAttemptCoordinator(Base(), events)
    asyncio.run(coordinator.report_start_outcome_unknown(object(), "start-code"))
    asyncio.run(coordinator.block_run_reconciliation(object(), "remote-code"))
    assert events.values == [("start", "start-code"), ("remote", "remote-code")]
