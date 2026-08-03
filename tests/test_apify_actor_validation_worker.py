import hashlib
from types import SimpleNamespace

from src.scrapers.apify_client import ApifyClientError
from src.services.apify_actor_ops import (
    ApifyActorOpsService,
    BATCH_CANARY_CONFIRMATION,
    PAID_CANARY_CONFIRMATION,
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
