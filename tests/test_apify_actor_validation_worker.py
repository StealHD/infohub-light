import hashlib

from src.services.apify_actor_ops import (
    ApifyActorOpsService,
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
