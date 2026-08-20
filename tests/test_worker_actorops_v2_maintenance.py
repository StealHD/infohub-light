from __future__ import annotations

import pytest

from src.apify_actor_identity import source_target_fingerprint
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle
from src.services.actorops.repository import ActorOpsRepository
from src.services.job_queue import JobQueue
from src.services.actorops.maintenance import ProbeResult
from src.services.worker_actorops_v2_maintenance import (
    WorkerActorOpsV2MaintenancePorts,
    enqueue_due_actorops_v2_maintenance,
    run_actorops_v2_maintenance,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _authorized_candidate(store: ServiceStore) -> str:
    connection = store.connect()
    owner = store.create_user(workspace_id=DEFAULT_WORKSPACE_ID, username="maintenance-owner", password="safe-test-password", role="owner")
    route_id = str(connection.execute("SELECT route_id FROM actor_routes_v2 WHERE platform='x'").fetchone()[0])
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        source_id = store.create_source(
            workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
            source_type="apify_social", display_name="maintenance source", config={"target": "openai"},
        )
        fingerprint = source_target_fingerprint(DEFAULT_WORKSPACE_ID, route_id, "openai", platform="x")
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                binding_id, workspace_id, source_id, route_id, target_fingerprint,
                status, binding_version, source_v1_generation, created_at, updated_at
            ) VALUES ('maintenance-binding', ?, ?, ?, ?, 'ready', 1, 1, ?, ?)""",
            (DEFAULT_WORKSPACE_ID, source_id, route_id, fingerprint,
             "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00"),
        )
        repository.create_candidate(candidate_id="maintenance-active", route_id=route_id,
                                    actor_id="publisher/active", publisher="publisher", build_id="build-active",
                                    build_number="1.0.0", manifest_json='{"version":1}', manifest_hash="c" * 64,
                                    input_schema_hash="d" * 64, output_schema_hash="e" * 64,
                                    lifecycle=CandidateLifecycle.CERTIFIED)
        repository.assign_candidate(route_id, "maintenance-active", AssignmentRole.ACTIVE, priority=0,
                                    expected_route_generation=1, expected_candidate_generation=1)
        repository.create_candidate(candidate_id="maintenance-candidate", route_id=route_id,
                                    actor_id="publisher/maintenance", publisher="publisher", build_id="build",
                                    build_number="1.0.0", manifest_json='{"version":1}', manifest_hash="a" * 64,
                                    input_schema_hash="b" * 64, output_schema_hash="c" * 64,
                                    lifecycle=CandidateLifecycle.STATIC_VALID)
    workspace, route = repository.maintenance.get_policy(None), repository.maintenance.get_policy(route_id)
    with repository.transaction():
        repository.maintenance.set_enabled(None, True, authorized_by_user_id=str(owner["id"]), expected_generation=workspace.generation)
        repository.maintenance.set_enabled(route_id, True, authorized_by_user_id=str(owner["id"]), expected_generation=route.generation)
    return route_id


def test_flag_off_maintenance_queue_is_inert_without_global_v2_reads(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ACTOROPS_V2_ENABLED", raising=False)
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)

    assert enqueue_due_actorops_v2_maintenance(store, JobQueue(store)) == {"enqueued": 0, "deferred": 0}
    assert not any("actor_maintenance_policies_v2" in statement for statement in statements)
    store.close()


def test_maintenance_queue_is_low_priority_and_idempotent_per_slot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    _authorized_candidate(store)
    queue = JobQueue(store)

    first = enqueue_due_actorops_v2_maintenance(store, queue)
    second = enqueue_due_actorops_v2_maintenance(store, queue)
    row = store.connect().execute("SELECT priority, job_type FROM fetch_jobs WHERE job_type='actorops_v2_maintenance'").fetchone()

    assert first["enqueued"] == 1 and second["enqueued"] == 0
    assert tuple(row) == (-10, "actorops_v2_maintenance")
    store.close()


def test_maintenance_handler_is_flag_gated_before_v2_access(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ACTOROPS_V2_ENABLED", raising=False)
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)

    with pytest.raises(RuntimeError, match="actorops_v2_disabled"):
        run_actorops_v2_maintenance({}, data_dir=str(store.data_dir), store=store)

    assert not any("actor_" in statement for statement in statements)
    store.close()


def test_maintenance_handler_uses_injected_probe_port(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = _authorized_candidate(store)
    job = {
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "payload_json": {
            "route_id": route_id, "candidate_id": "maintenance-candidate",
            "source_id": "maintenance-source", "binding_version": 1, "slot": "2026-08-20:1",
        },
    }

    async def probe(_job, _data_dir, _store):
        return ProbeResult("attempt-one", "maintenance-candidate", "promoted")

    result = run_actorops_v2_maintenance(
        job, data_dir=str(store.data_dir), store=store,
        ports=WorkerActorOpsV2MaintenancePorts(probe),
    )

    assert result["ok"] is True
    assert result["attempt_id"] == "attempt-one"
    store.close()
