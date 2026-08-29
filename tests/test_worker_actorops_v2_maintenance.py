from __future__ import annotations

import asyncio
import json

import pytest

from src.apify_actor_identity import source_target_fingerprint
from src.services import worker_actorops_v2_maintenance as maintenance_worker
from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from src.services.apify_key_pool import ApifyKeyPoolService
from src.services.apify_pool_reconciliation import apify_coordinator_for_workspace
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.recovery_probe import recovery_job_payload
from src.services.job_queue import JobQueue
from src.services.secret_store import SecretStore
from src.services.actorops.maintenance import ProbeResult
from src.services.worker_actorops_v2_maintenance import (
    WorkerActorOpsV2MaintenancePorts,
    enqueue_due_actorops_v2_maintenance,
    run_actorops_v2_maintenance,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from src.storage.actorops_v2_single_track_schema import MIGRATION_VERSION


def _manifest(actor_id: str) -> str:
    return json.dumps({
        "version": 1,
        "actor_id": actor_id,
        "build_number": "1.0.0",
        "input": {"target": {"$ref": "target.handle"}},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {
                "pointers": ["/createdAt"],
                "transforms": ["parse_datetime"],
            },
            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
            "author_handle": {
                "pointers": ["/author"],
                "transforms": ["to_string"],
            },
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle",
                "match": "handle",
            },
            "url_host_allowlist": ["example.com"],
        },
    })


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
                status, binding_version, created_at, updated_at
            ) VALUES ('maintenance-binding', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (DEFAULT_WORKSPACE_ID, source_id, route_id, fingerprint,
             "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00"),
        )
        active_manifest = _manifest("publisher/active")
        repository.create_candidate(candidate_id="maintenance-active", route_id=route_id,
                                    actor_id="publisher/active", publisher="publisher", build_id="build-active",
                                    build_number="1.0.0", manifest_json=active_manifest,
                                    manifest_hash=actor_manifest_hash(parse_actor_manifest(active_manifest)),
                                    input_schema_hash="d" * 64, output_schema_hash="e" * 64,
                                    lifecycle=CandidateLifecycle.CERTIFIED)
        repository.assign_candidate(route_id, "maintenance-active", AssignmentRole.ACTIVE, priority=0,
                                    expected_route_generation=1, expected_candidate_generation=1)
        candidate_manifest = _manifest("publisher/maintenance")
        repository.create_candidate(candidate_id="maintenance-candidate", route_id=route_id,
                                    actor_id="publisher/maintenance", publisher="publisher", build_id="build",
                                    build_number="1.0.0", manifest_json=candidate_manifest,
                                    manifest_hash=actor_manifest_hash(parse_actor_manifest(candidate_manifest)),
                                    input_schema_hash="b" * 64, output_schema_hash="c" * 64,
                                    lifecycle=CandidateLifecycle.STATIC_VALID)
    workspace, route = repository.maintenance.get_policy(None), repository.maintenance.get_policy(route_id)
    with repository.transaction():
        repository.maintenance.set_enabled(None, True, authorized_by_user_id=str(owner["id"]), expected_generation=workspace.generation)
        repository.maintenance.set_enabled(route_id, True, authorized_by_user_id=str(owner["id"]), expected_generation=route.generation)
    return route_id


def test_maintenance_queue_requires_global_30(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    )
    store.connect().commit()
    with pytest.raises(RuntimeError, match="migration_required"):
        enqueue_due_actorops_v2_maintenance(store, JobQueue(store))
    store.close()


def test_maintenance_queue_is_low_priority_and_idempotent_per_slot(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    _authorized_candidate(store)
    queue = JobQueue(store)

    first = enqueue_due_actorops_v2_maintenance(store, queue)
    second = enqueue_due_actorops_v2_maintenance(store, queue)
    row = store.connect().execute(
        """SELECT priority, job_type, max_attempts FROM fetch_jobs
             WHERE job_type='actorops_v2_maintenance'"""
    ).fetchone()

    assert first["enqueued"] == 1 and second["enqueued"] == 0
    assert tuple(row) == (-10, "actorops_v2_maintenance", 1)
    store.close()


def test_maintenance_creates_repair_when_route_has_only_one_stable_path(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = _authorized_candidate(store)
    repository = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        candidate = repository.get_candidate("maintenance-candidate")
        repository.transition_candidate(
            candidate.candidate_id,
            CandidateLifecycle.STATIC_VALID,
            CandidateLifecycle.DISABLED,
            expected_generation=candidate.generation,
            error_class="candidate",
            error_code="actorops_test_candidate_disabled",
        )

    result = enqueue_due_actorops_v2_maintenance(store, JobQueue(store))

    source_id = str(store.connect().execute(
        """SELECT source_id FROM actor_source_bindings_v2
            WHERE binding_id='maintenance-binding'"""
    ).fetchone()[0])
    repair = store.connect().execute(
        """SELECT status, trigger_code FROM actor_route_repairs_v2
            WHERE route_id=? AND source_id=?""",
        (route_id, source_id),
    ).fetchone()
    assert result["enqueued"] == 0
    assert tuple(repair) == ("queued", "actorops_insufficient_stable_paths")
    store.close()


def test_maintenance_handler_requires_global_30(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    )
    store.connect().commit()
    with pytest.raises(RuntimeError, match="migration_required"):
        run_actorops_v2_maintenance({}, data_dir=str(store.data_dir), store=store)
    store.close()


def test_maintenance_handler_uses_injected_probe_port(tmp_path) -> None:
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


def test_maintenance_handler_requires_complete_recovery_payload(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = _authorized_candidate(store)
    payload = recovery_job_payload(
        route_id=route_id,
        candidate_id="maintenance-active",
        source_id="maintenance-source",
        binding_version=1,
        expected_route_generation=2,
        expected_candidate_generation=2,
        expected_last_failure_at="2026-08-27T00:00:00+00:00",
        idempotency_key="worker-recovery-idempotency",
    )
    payload.pop("expected_last_failure_at")

    with pytest.raises(ValueError, match="metadata is invalid"):
        run_actorops_v2_maintenance(
            {"workspace_id": DEFAULT_WORKSPACE_ID, "payload_json": payload},
            data_dir=str(store.data_dir),
            store=store,
        )
    store.close()


@pytest.mark.parametrize(
    ("probe_status", "expected_ok", "expected_job_status"),
    (
        ("recovered", True, "succeeded"),
        ("skipped", False, "failed"),
        ("no_evidence", False, "failed"),
        ("already_settled", False, "failed"),
        ("recovery_required", False, "failed"),
        ("failed", False, "failed"),
    ),
)
def test_recovery_handler_only_succeeds_after_candidate_recovered(
    tmp_path,
    probe_status: str,
    expected_ok: bool,
    expected_job_status: str,
) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = _authorized_candidate(store)
    payload = recovery_job_payload(
        route_id=route_id,
        candidate_id="maintenance-active",
        source_id="maintenance-source",
        binding_version=1,
        expected_route_generation=2,
        expected_candidate_generation=2,
        expected_last_failure_at="2026-08-27T00:00:00+00:00",
        idempotency_key="worker-recovery-final-status",
    )

    async def probe(_job, _data_dir, _store):
        return ProbeResult(
            "recovery-attempt", "maintenance-active", probe_status
        )

    result = run_actorops_v2_maintenance(
        {"workspace_id": DEFAULT_WORKSPACE_ID, "payload_json": payload},
        data_dir=str(store.data_dir),
        store=store,
        ports=WorkerActorOpsV2MaintenancePorts(probe),
    )

    assert result["ok"] is expected_ok
    assert result["_job_status"] == expected_job_status
    store.close()


def test_maintenance_worker_uses_real_validation_coordinator_before_probe(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = _authorized_candidate(store)
    source_id = str(store.connect().execute(
        "SELECT source_id FROM actor_source_bindings_v2 WHERE binding_id='maintenance-binding'"
    ).fetchone()[0])
    captured: dict[str, object] = {}
    original = maintenance_worker.apify_coordinator_for_workspace

    def coordinator(*args, **kwargs):
        captured["kwargs"] = dict(kwargs)
        value = original(*args, **kwargs)
        captured["value"] = value
        return value

    async def no_remote_probe(self, **values):
        captured["remote_coordinator"] = self.remote.client.coordinator
        captured["probe_values"] = dict(values)
        return ProbeResult(
            None,
            str(values["candidate_id"]),
            "skipped",
            "actorops_test_preflight_rejected",
        )

    monkeypatch.setattr(
        maintenance_worker, "apify_coordinator_for_workspace", coordinator
    )
    def catalog(*_args, **kwargs):
        captured["catalog_purpose"] = kwargs.get("purpose")
        return object()

    monkeypatch.setattr(maintenance_worker, "_catalog", catalog)
    monkeypatch.setattr(
        maintenance_worker.ActorOpsProber, "probe", no_remote_probe
    )
    recovery_payload = recovery_job_payload(
        route_id=route_id,
        candidate_id="maintenance-active",
        source_id=source_id,
        binding_version=1,
        expected_route_generation=2,
        expected_candidate_generation=2,
        expected_last_failure_at="2026-08-27T00:00:00+00:00",
        idempotency_key="worker-recovery-forwarding",
    )
    job = {
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "payload_json": recovery_payload,
    }

    result = asyncio.run(
        maintenance_worker._run_probe(job, str(store.data_dir), store)
    )

    kwargs = captured["kwargs"]
    actual = captured["value"]
    assert kwargs["purpose"] == "validation"
    assert kwargs["require_validation_key"] is False
    assert isinstance(actual, ApifyKeyPoolService)
    assert actual.run_purpose == "validation"
    assert actual.require_validation_key is False
    assert captured["catalog_purpose"] == "validation"
    assert captured["remote_coordinator"] is actual
    probe_values = captured["probe_values"]
    assert probe_values["intent"] == "operator_recovery"
    assert probe_values["expected_route_generation"] == 2
    assert probe_values["expected_candidate_generation"] == 2
    assert probe_values["expected_last_failure_at"] == "2026-08-27T00:00:00+00:00"
    assert result.status == "skipped"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_attempts_v2"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == 0
    store.close()


def test_maintenance_credential_unavailable_defers_without_candidate_penalty(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = _authorized_candidate(store)
    source_id = str(store.connect().execute(
        "SELECT source_id FROM actor_source_bindings_v2 WHERE binding_id='maintenance-binding'"
    ).fetchone()[0])
    monkeypatch.setattr(
        maintenance_worker,
        "apify_coordinator_for_workspace",
        lambda *_args, **_kwargs: None,
    )

    result = asyncio.run(maintenance_worker._run_probe({
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "payload_json": {
            "route_id": route_id,
            "candidate_id": "maintenance-candidate",
            "source_id": source_id,
            "binding_version": 1,
            "slot": "2026-08-27:1",
        },
    }, str(store.data_dir), store))

    assert result.status == "skipped"
    assert result.error_code == "actorops_maintenance_credential_unavailable"
    candidate = ActorOpsRepository(
        store.connect(), DEFAULT_WORKSPACE_ID
    ).get_candidate("maintenance-candidate")
    assert candidate.generation == 1
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_attempts_v2"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == 0
    store.close()


def test_maintenance_validation_coordinator_prefers_dedicated_key_and_ledger(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    secrets = SecretStore(store.data_dir)
    refs = []
    for suffix in ("ACQUISITION", "VALIDATION"):
        env_name = f"APIFY_TOKEN_{suffix}"
        refs.append(store.create_secret_ref(
            workspace_id=DEFAULT_WORKSPACE_ID,
            owner_user_id=None,
            name=f"Apify {suffix.casefold()}",
            env_name=env_name,
            kind="provider",
            provider="apify",
        ))
        secrets.set(env_name, f"test-{suffix.casefold()}-token")
    setup = ApifyKeyPoolService(store, secret_store=secrets)
    for ref in refs:
        setup.append_secret(str(ref["id"]))
    setup.set_validation_key(
        DEFAULT_WORKSPACE_ID,
        secret_id=str(refs[1]["id"]),
        expected_generation=setup.current_generation(DEFAULT_WORKSPACE_ID),
    )
    coordinator = apify_coordinator_for_workspace(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=str(store.data_dir),
        purpose="validation",
        require_validation_key=False,
    )
    assert coordinator is not None

    lease = coordinator.acquire_credential(
        logical_run_id="maintenance-validation-ledger"
    )
    assert lease.secret_id == str(refs[1]["id"])
    reserved = store.connect().execute(
        """SELECT purpose, status, remote_run_id, dataset_id
             FROM apify_actor_runs WHERE id=?""",
        (lease.reservation_id,),
    ).fetchone()
    assert tuple(reserved) == ("validation", "reserved", None, None)
    coordinator.release_reservation(lease, "actorops_test_no_remote_start")
    settled = store.connect().execute(
        """SELECT purpose, status, charge_reserved_usd,
                  charge_actual_usd, charge_final, remote_run_id, dataset_id
             FROM apify_actor_runs WHERE id=?""",
        (lease.reservation_id,),
    ).fetchone()
    assert tuple(settled) == (
        "validation", "start_rejected", 0.0, 0.0, 1, None, None
    )
    state = coordinator.public_state(DEFAULT_WORKSPACE_ID)
    assert state["status"] == "ready"
    assert state["active_secret_id"] == str(refs[0]["id"])
    assert state["validation_secret_id"] == str(refs[1]["id"])
    store.close()
