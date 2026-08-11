import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

from src.scrapers.apify_client import ApifyClientError
from src.services.apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    BATCH_CANARY_CONFIRMATION,
    PAID_CANARY_CONFIRMATION,
    RouteExecutionSnapshot,
    RouteSlotSnapshot,
)
from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


def _manifest(actor_id: str) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": "1.0.1",
        "input": {
            "url": {"$ref": "target.canonical_url"},
            "maxItems": {"$ref": "runtime.max_items"},
        },
        "output": {
            "native_id": {"pointers": ["/id"]},
            "url": {
                "pointers": ["/url"],
                "transforms": ["normalize_url"],
            },
            "published_at": {
                "pointers": ["/publishedAt"],
                "transforms": ["parse_datetime"],
            },
            "title": {"pointers": ["/title"]},
            "author_handle": {"pointers": ["/handle"]},
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle",
                "match": "handle",
            },
            "url_host_allowlist": ["x.com"],
        },
    }


def _batch_manifest(actor_id: str) -> dict:
    manifest = _manifest(actor_id)
    manifest["output"].pop("author_handle")
    manifest["output"]["source_native_id"] = {"pointers": ["/channelId"]}
    manifest["semantics"] = {
        "identity": {
            "output_field": "source_native_id",
            "target_ref": "target.native_id",
            "match": "exact",
        },
        "url_host_allowlist": ["youtube.com"],
    }
    return manifest


def _queue_route_validation(store: ServiceStore, admin: dict, *, suffix: str):
    ops = ApifyActorOpsService(store)
    route = next(
        route for route in ops.list_routes() if route["route_key"] == "x/profile"
    )
    actor_id = f"worker-{suffix}/route-canary"
    candidate_id = ops.ensure_candidate(route["route_id"], actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher=f"worker-{suffix}",
        build_id=f"build-{suffix}",
        build_number="1.0.1",
        manifest=_manifest(actor_id),
        lifecycle="static_valid",
    )
    validation = ops.approve_revision_canary(
        route["route_id"],
        revision_id,
        expected_generation=route["generation"],
        approval_id=f"worker-approval-{suffix}",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(
            f"worker-reference-{suffix}".encode()
        ).hexdigest(),
    )
    job = JobQueue(store).create_job(
        workspace_id=admin["workspace_id"],
        user_id=admin["id"],
        job_type="apify_actor_validation",
        payload={"validation_id": validation["validation_id"]},
        priority=100,
        max_attempts=1,
    )
    return validation, job


def _disable_background_actor_work(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.services.worker.reconcile_all_apify_pools_sync",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "src.services.worker.MaintenanceService.run_if_due",
        lambda *_args, **_kwargs: {"ran": False},
    )


def _queue_canary_batch(store: ServiceStore, admin: dict):
    ops = ApifyActorOpsService(store)
    route = next(
        route
        for route in ops.list_routes()
        if route["route_key"] == "youtube/channel/items"
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="batch-worker-test",
        expected_generation=int(route["generation"]),
    )
    revisions = []
    for index, publisher in enumerate(("batch-a", "batch-b", "batch-c"), start=1):
        actor_id = f"{publisher}/route-canary"
        candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
        revision_id = ops.create_adapter_revision(
            candidate_id=candidate_id,
            actor_id=actor_id,
            publisher=publisher,
            build_id=f"batch-build-{index}",
            build_number="1.0.1",
            manifest=_batch_manifest(actor_id),
            lifecycle="static_valid",
            discovery_run_id=str(run["run_id"]),
        )
        revisions.append(revision_id)
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    plan = ops.get_canary_plan(str(run["run_id"]))
    batch = ops.create_canary_batch(
        str(run["run_id"]),
        expected_generation=int(route["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id="batch-worker-approval-0001",
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=3,
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=str(admin["id"]),
        reference_fingerprints={
            revision_id: hashlib.sha256(
                f"batch-reference-{revision_id}".encode()
            ).hexdigest()
            for revision_id in revisions
        },
    )
    job = JobQueue(store).create_job(
        workspace_id=admin["workspace_id"],
        user_id=admin["id"],
        job_type="apify_actor_canary_batch",
        payload={"batch_id": batch["batch_id"]},
        priority=100,
        max_attempts=1,
    )
    return ops, batch, job


def test_worker_executes_confirmed_actor_validation_for_disabled_pending_source(
    tmp_path,
    monkeypatch,
):
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="actorops-worker-admin",
        password="safe-test-password",
        role="admin",
    )
    source_id = store.create_source(
        workspace_id="default",
        scope="workspace",
        owner_user_id=admin["id"],
        source_type="apify_social",
        display_name="Pending Actor source",
        config={
            "profile_id": "apify-route-test",
            "target": "@pending",
        },
        source_key="apify_social:route:pending",
        enabled=False,
    )
    job = JobQueue(store).create_job(
        workspace_id="default",
        user_id=admin["id"],
        source_id=source_id,
        job_type="apify_actor_validation",
        payload={"validation_id": "apify-validation-test"},
        priority=100,
        max_attempts=1,
    )
    store.close()
    calls = []

    monkeypatch.setattr(
        "src.services.worker.reconcile_all_apify_pools_sync",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "src.services.worker._run_apify_actor_validation",
        lambda claimed, *, data_dir, store: calls.append(
            (claimed["id"], data_dir)
        )
        or {
            "ok": True,
            "job_type": "apify_actor_validation",
            "validation_id": "apify-validation-test",
        },
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="actorops-validation-worker",
        enqueue_schedules=False,
    )

    assert calls == [(job["id"], str(tmp_path))]
    assert result["status"] == "succeeded"
    assert result["result_json"]["validation_id"] == "apify-validation-test"


def test_disabled_admin_cancels_unstarted_paid_validation_atomically(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="disabled-canary-admin",
        password="safe-test-password",
        role="admin",
    )
    validation, job = _queue_route_validation(store, admin, suffix="disabled")
    store.connect().execute(
        "UPDATE users SET enabled = 0 WHERE id = ?",
        (admin["id"],),
    )
    store.connect().commit()
    store.close()
    _disable_background_actor_work(monkeypatch)

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="disabled-canary-worker",
        enqueue_schedules=False,
    )

    verification_store = ServiceStore(tmp_path)
    verification_store.initialize()
    row = verification_store.connect().execute(
        """
        SELECT status, semantic_outcome, cost_usd, attempt_id, completed_at
        FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()
    assert result["id"] == job["id"]
    assert result["status"] == "cancelled"
    assert tuple(row) == (
        "cancelled",
        "user_disabled",
        0.0,
        None,
        row["completed_at"],
    )
    assert row["completed_at"]


def test_pre_attempt_paid_validation_failure_releases_queued_approval(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="unavailable-canary-admin",
        password="safe-test-password",
        role="admin",
    )
    validation, job = _queue_route_validation(store, admin, suffix="unavailable")
    store.close()
    _disable_background_actor_work(monkeypatch)
    monkeypatch.setattr(
        "src.services.worker.apify_coordinator_for_workspace",
        lambda *_args, **_kwargs: None,
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="unavailable-canary-worker",
        enqueue_schedules=False,
    )

    verification_store = ServiceStore(tmp_path)
    verification_store.initialize()
    row = verification_store.connect().execute(
        """
        SELECT status, semantic_outcome, cost_usd, attempt_id, completed_at
        FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()
    assert result["id"] == job["id"]
    assert result["status"] == "failed"
    assert tuple(row) == (
        "failed",
        "apify_actor_routing_disabled",
        0.0,
        None,
        row["completed_at"],
    )
    assert row["completed_at"]


def test_batch_worker_stops_after_two_publishers_and_finalizes_unused_as_free(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="batch-canary-admin",
        password="safe-test-password",
        role="admin",
    )
    _ops, batch, job = _queue_canary_batch(store, admin)
    store.close()
    _disable_background_actor_work(monkeypatch)
    calls: list[tuple[str, str]] = []

    class Coordinator:
        def public_state(self, _workspace_id):
            return {"active_secret_id": "secret-batch"}

        def quota_candidate(self, _secret_id):
            return SimpleNamespace(
                env_name="APIFY_TOKEN_BATCH_TEST",
                token="test-token-not-persisted",
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def preflight_actor_revision(
            self,
            actor_id,
            *,
            build_id,
            build_number,
        ):
            calls.append(("preflight", actor_id))
            assert build_id.startswith("batch-build-")
            assert build_number == "1.0.1"

    class FakeRunner:
        def __init__(self, _store, ops, _client):
            self.ops = ops

        async def run(self, validation_id, *, job_id, skip_preflight):
            calls.append(("run", validation_id))
            assert job_id == job["id"]
            assert skip_preflight is True
            validation = self.ops.record_validation(
                validation_id,
                status="succeeded",
                semantic_outcome="valid_nonempty",
                cost_usd=0.001,
                cost_final=True,
                counts_toward_canary=True,
            )
            self.ops.transition_revision(
                str(validation["revision_id"]),
                expected_lifecycle="static_valid",
                lifecycle="probationary",
            )
            return SimpleNamespace(
                semantic_outcome="valid_nonempty",
                cost_usd=0.001,
            )

    monkeypatch.setattr(
        "src.services.worker.apify_coordinator_for_workspace",
        lambda *_args, **_kwargs: Coordinator(),
    )
    monkeypatch.setattr("src.scrapers.apify_client.ApifyClient", FakeClient)
    monkeypatch.setattr(
        "src.services.apify_actor_canary.ApifyActorCanaryRunner",
        FakeRunner,
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="batch-canary-worker",
        enqueue_schedules=False,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert [kind for kind, _value in calls].count("preflight") == 2
    assert [kind for kind, _value in calls].count("run") == 2
    verification_store = ServiceStore(tmp_path)
    verification_store.initialize()
    persisted = ApifyActorOpsService(verification_store).get_canary_batch(
        str(batch["batch_id"])
    )
    assert persisted["status"] == "activation_ready"
    assert persisted["success_count"] == 2
    assert persisted["publisher_count"] == 2
    assert persisted["actual_cost_usd"] == 0.002
    assert persisted["cost_final"] is True
    assert [item["status"] for item in persisted["items"]] == [
        "succeeded",
        "succeeded",
        "not_needed_no_charge",
    ]
    assert persisted["items"][2]["actual_cost_usd"] == 0
    unused = verification_store.connect().execute(
        """
        SELECT cost_usd, cost_final, counts_toward_canary
        FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (persisted["items"][2]["validation_id"],),
    ).fetchone()
    assert tuple(unused) == (0.0, 1, 0)


def test_legacy_stage_worker_validates_all_three_current_actors_without_switching_pool(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="legacy-stage-worker-admin",
        password="safe-test-password",
        role="admin",
    )
    ops = ApifyActorOpsService(store)
    route = next(
        item for item in ops.list_routes() if item["route_key"] == "x/profile"
    )
    old_slots = [slot["revision_id"] for slot in ops.get_route(str(route["route_id"]))["slots"]]
    source_id = store.create_source(
        workspace_id="default",
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Legacy stage source",
        config={"platform": "x", "kind": "profile", "target": "stage-source"},
    )
    ops.bind_source(
        source_id=source_id,
        route_id=str(route["route_id"]),
        target_fingerprint=hashlib.sha256(b"legacy-stage-source").hexdigest(),
        mode="primary",
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="legacy-stage-worker-test",
        expected_generation=int(route["generation"]),
    )
    revision_ids: list[str] = []
    current_slots = ops.get_route(str(route["route_id"]))["slots"]
    for index, slot in enumerate(current_slots, start=1):
        publisher = str(slot["publisher"])
        actor_id = str(slot["actor_id"])
        candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
        revision_ids.append(
            ops.create_adapter_revision(
                candidate_id=candidate_id,
                actor_id=actor_id,
                publisher=publisher,
                build_id=f"stage-build-{index}",
                build_number="1.0.1",
                manifest=_manifest(actor_id),
                lifecycle="static_valid",
                discovery_run_id=str(run["run_id"]),
            )
        )
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    plan = ops.get_canary_plan(str(run["run_id"]), goal="upgrade_legacy")
    assert plan["source_count"] == 1
    assert plan["source_validation_count"] == 3
    batch = ops.create_canary_batch(
        str(run["run_id"]),
        goal="upgrade_legacy",
        expected_generation=int(route["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id="legacy-stage-worker-approval-0001",
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=int(plan["max_candidates"]),
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=str(admin["id"]),
        reference_fingerprints={
            revision_id: hashlib.sha256(
                f"legacy-stage-reference-{revision_id}".encode()
            ).hexdigest()
            for revision_id in revision_ids
        },
    )
    job = JobQueue(store).create_job(
        workspace_id=admin["workspace_id"],
        user_id=admin["id"],
        job_type="apify_actor_canary_batch",
        payload={"batch_id": batch["batch_id"]},
        priority=100,
        max_attempts=1,
    )
    store.close()
    _disable_background_actor_work(monkeypatch)
    calls: list[tuple[str, str]] = []

    class Coordinator:
        def public_state(self, _workspace_id):
            return {"active_secret_id": "secret-legacy-stage"}

        def quota_candidate(self, _secret_id):
            return SimpleNamespace(
                env_name="APIFY_TOKEN_LEGACY_STAGE_TEST",
                token="test-token-not-persisted",
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def preflight_actor_revision(
            self,
            actor_id,
            *,
            build_id,
            build_number,
        ):
            calls.append(("preflight", actor_id))
            assert build_id.startswith("stage-build-")
            assert build_number == "1.0.1"

    class FakeRunner:
        def __init__(self, _store, stage_ops, _client):
            self.ops = stage_ops

        async def run(self, validation_id, *, job_id, skip_preflight):
            calls.append(("run", validation_id))
            assert job_id == job["id"]
            current = self.ops.get_validation(validation_id)
            assert skip_preflight is (current["source_id"] is None)
            validation = self.ops.record_validation(
                validation_id,
                status="succeeded",
                semantic_outcome="valid_nonempty",
                cost_usd=0.001,
                cost_final=True,
                counts_toward_canary=True,
            )
            if current["source_id"] is None:
                self.ops.transition_revision(
                    str(validation["revision_id"]),
                    expected_lifecycle="static_valid",
                    lifecycle="probationary",
                )
            return SimpleNamespace(
                semantic_outcome="valid_nonempty",
                cost_usd=0.001,
            )

    monkeypatch.setattr(
        "src.services.worker.apify_coordinator_for_workspace",
        lambda *_args, **_kwargs: Coordinator(),
    )
    monkeypatch.setattr("src.scrapers.apify_client.ApifyClient", FakeClient)
    monkeypatch.setattr(
        "src.services.apify_actor_canary.ApifyActorCanaryRunner",
        FakeRunner,
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="legacy-stage-canary-worker",
        enqueue_schedules=False,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert [kind for kind, _value in calls].count("run") == 6
    verification_store = ServiceStore(tmp_path)
    verification_store.initialize()
    verification_ops = ApifyActorOpsService(verification_store)
    persisted = verification_ops.get_canary_batch(str(batch["batch_id"]))
    assert persisted["status"] == "activation_ready"
    assert persisted["pool_stage"]["status"] == "apply_ready"
    assert [
        slot["revision_id"]
        for slot in verification_ops.get_route(str(route["route_id"]))["slots"]
    ] == old_slots
    assert persisted["success_count"] == 3
    assert persisted["publisher_count"] >= 2
    assert persisted["actual_cost_usd"] == 0.006
    assert persisted["cost_final"] is True
    assert [item["status"] for item in persisted["items"]] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    source_validations = verification_store.connect().execute(
        """
        SELECT status, cost_final FROM apify_actor_validations
        WHERE workspace_id = 'default' AND source_id = ?
          AND kind = 'source_canary'
        ORDER BY revision_id
        """,
        (source_id,),
    ).fetchall()
    assert [tuple(row) for row in source_validations] == [
        ("succeeded", 1),
        ("succeeded", 1),
        ("succeeded", 1),
    ]
    assert persisted["pool_stage"]["source_summary"] == {
        "source_count": 1,
        "required_count": 3,
        "passed_count": 3,
        "succeeded_sources": 1,
        "failed_sources": 0,
        "active_sources": 0,
    }


def test_batch_unknown_start_is_a_failed_job_and_never_runs_next_candidate(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="batch-unknown-start-admin",
        password="safe-test-password",
        role="admin",
    )
    _ops, batch, job = _queue_canary_batch(store, admin)
    store.close()
    _disable_background_actor_work(monkeypatch)
    calls: list[str] = []

    class Coordinator:
        def public_state(self, _workspace_id):
            return {"active_secret_id": "secret-batch"}

        def quota_candidate(self, _secret_id):
            return SimpleNamespace(
                env_name="APIFY_TOKEN_BATCH_TEST",
                token="test-token-not-persisted",
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def preflight_actor_revision(
            self,
            actor_id,
            *,
            build_id,
            build_number,
        ):
            calls.append(f"preflight:{actor_id}")
            assert build_id.startswith("batch-build-")
            assert build_number == "1.0.1"

    class UnknownRunner:
        def __init__(self, _store, ops, _client):
            self.ops = ops

        async def run(self, validation_id, *, job_id, skip_preflight):
            calls.append(f"run:{validation_id}")
            assert job_id == job["id"]
            assert skip_preflight is True
            self.ops.record_validation(
                validation_id,
                status="failed",
                semantic_outcome="apify_start_outcome_unknown",
                cost_usd=None,
                cost_final=False,
                counts_toward_canary=True,
            )
            raise ActorOpsError(
                "apify_start_outcome_unknown",
                "unknown start",
                retryable=False,
            )

    monkeypatch.setattr(
        "src.services.worker.apify_coordinator_for_workspace",
        lambda *_args, **_kwargs: Coordinator(),
    )
    monkeypatch.setattr("src.scrapers.apify_client.ApifyClient", FakeClient)
    monkeypatch.setattr(
        "src.services.apify_actor_canary.ApifyActorCanaryRunner",
        UnknownRunner,
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="batch-unknown-start-worker",
        enqueue_schedules=False,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "failed"
    assert len([value for value in calls if value.startswith("run:")]) == 1
    verification_store = ServiceStore(tmp_path)
    verification_store.initialize()
    persisted = ApifyActorOpsService(verification_store).get_canary_batch(
        str(batch["batch_id"])
    )
    assert persisted["status"] == "blocked_unknown_start"
    assert [item["status"] for item in persisted["items"]] == [
        "blocked_unknown_start",
        "not_needed_no_charge",
        "not_needed_no_charge",
    ]


def test_proven_no_start_releases_batch_budget_without_paid_retry(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="batch-no-start-proof-admin",
        password="safe-test-password",
        role="admin",
    )
    ops, batch, job = _queue_canary_batch(store, admin)
    persisted = ops.get_canary_batch(str(batch["batch_id"]))
    item = persisted["items"][0]
    revision = ops.get_revision(str(item["revision_id"]))
    route = ops.get_route(str(batch["route_id"]))
    slot = RouteSlotSnapshot(
        slot_name="primary",
        candidate_id=str(revision["candidate_id"]),
        revision_id=str(revision["revision_id"]),
        actor_id=str(revision["actor_id"]),
        publisher=str(revision["publisher"]),
        build_id=str(revision["build_id"]),
        build_number=str(revision["build_number"]),
        manifest_hash=str(revision["manifest_hash"]),
        lifecycle=str(revision["lifecycle"]),
        candidate_state="closed",
        manifest=None,
    )
    snapshot = RouteExecutionSnapshot(
        workspace_id="default",
        route_id=str(route["route_id"]),
        route_key=str(route["route_key"]),
        route_generation=int(route["generation"]),
        per_run_cap_usd=float(route["per_run_cap_usd"]),
        slots=(slot,),
    )
    attempt_id = ops.begin_validation_attempt(
        str(item["validation_id"]),
        snapshot,
        slot,
        job_id=str(job["id"]),
    )
    ops.finish_unknown_start(
        snapshot,
        attempt_id=attempt_id,
        semantic_outcome="apify_start_outcome_unknown",
        error_code="apify_start_outcome_unknown",
        validation_id=str(item["validation_id"]),
    )
    ops.set_canary_batch_status(
        str(batch["batch_id"]),
        expected_statuses=("queued",),
        status="preflighting",
    )
    ops.set_canary_batch_status(
        str(batch["batch_id"]),
        expected_statuses=("preflighting",),
        status="running",
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        1,
        status="blocked_unknown_start",
        semantic_outcome="apify_start_outcome_unknown",
    )
    ops.set_canary_batch_status(
        str(batch["batch_id"]),
        expected_statuses=("running",),
        status="blocked_unknown_start",
        stop_reason="apify_start_outcome_unknown",
    )
    now = datetime.now(timezone.utc).isoformat()
    store.connect().execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, status, last_error_code,
            charge_reserved_usd, charge_actual_usd, charge_final,
            created_at, terminal_at, updated_at
        ) VALUES (
            'batch-no-start-run', 'default', ?, 'secret-proof', 1, 1,
            'start_rejected', 'apify_start_not_created', 0, 0, 1, ?, ?, ?
        )
        """,
        (attempt_id, now, now, now),
    )
    store.connect().execute(
        "UPDATE fetch_jobs SET status = 'succeeded' WHERE id = ?",
        (job["id"],),
    )
    store.connect().commit()

    result = ops.reconcile_proven_no_start_attempts()

    assert result["attempts"] == 1
    validation = ops.get_validation(str(item["validation_id"]))
    assert validation["cost_usd"] == 0
    assert validation["cost_final"] == 1
    assert validation["counts_toward_canary"] == 0
    reconciled_batch = ops.get_canary_batch(str(batch["batch_id"]))
    assert reconciled_batch["status"] == "partial"
    assert reconciled_batch["actual_cost_usd"] == 0
    assert reconciled_batch["cost_final"] is False
    assert reconciled_batch["stop_reason"] == "apify_start_not_created"
    assert reconciled_batch["items"][0]["status"] == "failed"
    assert JobQueue(store).get_job(str(job["id"]))["status"] == "failed"
    assert ops.get_route(str(route["route_id"]))["status"] == "discovery_required"


def test_batch_worker_failure_during_preflight_releases_every_unstarted_item(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="batch-preflight-failure-admin",
        password="safe-test-password",
        role="admin",
    )
    _ops, batch, job = _queue_canary_batch(store, admin)
    store.close()
    _disable_background_actor_work(monkeypatch)

    class Coordinator:
        def public_state(self, _workspace_id):
            return {"active_secret_id": "secret-batch"}

        def quota_candidate(self, _secret_id):
            return SimpleNamespace(
                env_name="APIFY_TOKEN_BATCH_TEST",
                token="test-token-not-persisted",
            )

    class BrokenClient:
        def __init__(self, **_kwargs):
            raise RuntimeError("bounded test failure before any remote start")

    monkeypatch.setattr(
        "src.services.worker.apify_coordinator_for_workspace",
        lambda *_args, **_kwargs: Coordinator(),
    )
    monkeypatch.setattr("src.scrapers.apify_client.ApifyClient", BrokenClient)

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="batch-preflight-failure-worker",
        enqueue_schedules=False,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "failed"
    verification_store = ServiceStore(tmp_path)
    verification_store.initialize()
    persisted = ApifyActorOpsService(verification_store).get_canary_batch(
        str(batch["batch_id"])
    )
    assert persisted["status"] == "failed"
    assert persisted["actual_cost_usd"] == 0
    assert persisted["cost_final"] is True
    assert [item["status"] for item in persisted["items"]] == [
        "not_needed_no_charge",
        "not_needed_no_charge",
        "not_needed_no_charge",
    ]
    validations = verification_store.connect().execute(
        """
        SELECT status, cost_usd, cost_final, counts_toward_canary, attempt_id
        FROM apify_actor_validations
        WHERE validation_id IN (
            SELECT validation_id
            FROM apify_actor_canary_batch_items
            WHERE batch_id = ?
        )
        ORDER BY validation_id
        """,
        (batch["batch_id"],),
    ).fetchall()
    assert len(validations) == 3
    assert all(tuple(row) == ("failed", 0.0, 1, 0, None) for row in validations)


def test_batch_worker_keeps_one_success_and_queues_replacement_discovery(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id="default",
        username="batch-replenishment-admin",
        password="safe-test-password",
        role="admin",
    )
    _ops, batch, job = _queue_canary_batch(store, admin)
    store.close()
    _disable_background_actor_work(monkeypatch)
    preflight_calls = 0

    class Coordinator:
        def public_state(self, _workspace_id):
            return {"active_secret_id": "secret-batch"}

        def quota_candidate(self, _secret_id):
            return SimpleNamespace(
                env_name="APIFY_TOKEN_BATCH_TEST",
                token="test-token-not-persisted",
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def preflight_actor_revision(
            self,
            _actor_id,
            *,
            build_id,
            build_number,
        ):
            nonlocal preflight_calls
            preflight_calls += 1
            assert build_id.startswith("batch-build-")
            assert build_number == "1.0.1"
            if preflight_calls > 1:
                raise ApifyClientError(
                    "apify_actor_revision_unavailable",
                    "exact build no longer exists",
                    retryable=False,
                    status_code=404,
                )

    class FakeRunner:
        def __init__(self, _store, ops, _client):
            self.ops = ops

        async def run(self, validation_id, *, job_id, skip_preflight):
            assert job_id == job["id"]
            assert skip_preflight is True
            validation = self.ops.record_validation(
                validation_id,
                status="succeeded",
                semantic_outcome="valid_nonempty",
                cost_usd=0.001,
                cost_final=True,
                counts_toward_canary=True,
            )
            self.ops.transition_revision(
                str(validation["revision_id"]),
                expected_lifecycle="static_valid",
                lifecycle="probationary",
            )
            return SimpleNamespace(
                semantic_outcome="valid_nonempty",
                cost_usd=0.001,
            )

    monkeypatch.setattr(
        "src.services.worker.apify_coordinator_for_workspace",
        lambda *_args, **_kwargs: Coordinator(),
    )
    monkeypatch.setattr("src.scrapers.apify_client.ApifyClient", FakeClient)
    monkeypatch.setattr(
        "src.services.apify_actor_canary.ApifyActorCanaryRunner",
        FakeRunner,
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="batch-replenishment-worker",
        enqueue_schedules=False,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert result["result_json"]["status"] == "partial"
    assert result["result_json"]["replenishment_job_id"]
    assert preflight_calls == 3
    verification_store = ServiceStore(tmp_path)
    verification_store.initialize()
    persisted = ApifyActorOpsService(verification_store).get_canary_batch(
        str(batch["batch_id"])
    )
    assert persisted["status"] == "partial"
    assert persisted["success_count"] == 1
    assert persisted["actual_cost_usd"] == 0.001
    assert [item["status"] for item in persisted["items"]] == [
        "succeeded",
        "preflight_failed",
        "preflight_failed",
    ]
    replacement = verification_store.connect().execute(
        """
        SELECT job.status, run.stage, run.trigger_reason
        FROM fetch_jobs AS job
        JOIN apify_actor_discovery_runs AS run
          ON run.run_id = json_extract(job.payload_json, '$.run_id')
        WHERE job.id = ? AND job.job_type = 'apify_actor_discovery'
        """,
        (result["result_json"]["replenishment_job_id"],),
    ).fetchone()
    assert tuple(replacement) == (
        "queued",
        "queued",
        "canary_batch_replenishment",
    )
