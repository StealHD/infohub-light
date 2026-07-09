import pytest
from datetime import datetime, timedelta, timezone

from src.services.job_queue import JobQueue
from src.services.quota import QuotaExceeded, QuotaService
from src.storage.service_store import ServiceStore


def _store_with_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    return store, store.get_default_workspace(), store.get_user_by_username("owner")


def test_job_queue_claims_and_completes_job(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)

    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
    )
    claimed = queue.claim_next_job(worker_id="worker-1")
    queue.complete_job(claimed["id"], status="succeeded", result={"count": 1})

    loaded = queue.get_job(job["id"])

    assert claimed["id"] == job["id"]
    assert claimed["status"] == "running"
    assert loaded["status"] == "succeeded"
    assert loaded["result_json"] == {"count": 1}
    assert loaded["locked_until"] is None


def test_job_queue_retries_failed_job_until_max_attempts(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        max_attempts=2,
    )
    claimed = queue.claim_next_job(worker_id="worker-1", lease_seconds=60)

    retried = queue.fail_or_retry_job(
        claimed["id"],
        error_code="RuntimeError",
        error_message="temporary failure",
        retryable=True,
        retry_base_seconds=0,
    )
    second_claim = queue.claim_next_job(worker_id="worker-1", lease_seconds=60)
    failed = queue.fail_or_retry_job(
        second_claim["id"],
        error_code="RuntimeError",
        error_message="final failure",
        retryable=True,
        retry_base_seconds=0,
    )

    assert retried["id"] == job["id"]
    assert retried["status"] == "queued"
    assert retried["attempts"] == 1
    assert second_claim["attempts"] == 2
    assert failed["status"] == "failed"
    assert failed["error_message"] == "final failure"
    assert failed["locked_until"] is None


def test_job_queue_requeues_stale_running_jobs(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
    )
    claimed = queue.claim_next_job(worker_id="worker-1", lease_seconds=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    store.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        (past.isoformat(), claimed["id"]),
    )
    store.connect().commit()

    count = queue.requeue_stale_running_jobs()
    loaded = queue.get_job(job["id"])

    assert count == 1
    assert loaded["status"] == "queued"
    assert loaded["worker_id"] is None
    assert loaded["locked_until"] is None
    assert loaded["error_code"] == "lease_expired"


def test_job_queue_cancel_retry_and_prune_terminal_jobs(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        retention_days=1,
    )

    cancelled = queue.cancel_job(job["id"], user_id=owner["id"])
    retried = queue.retry_job(job["id"], user_id=owner["id"])
    claimed = queue.claim_next_job(worker_id="worker-1")
    completed = queue.complete_job(claimed["id"], status="succeeded", result={"ok": True})
    past = datetime.now(timezone.utc) - timedelta(days=2)
    store.connect().execute(
        "UPDATE fetch_jobs SET expires_at = ? WHERE id = ?",
        (past.isoformat(), completed["id"]),
    )
    store.connect().commit()

    pruned = queue.prune_terminal_jobs()

    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_at"]
    assert retried["status"] == "queued"
    assert retried["attempts"] == 0
    assert pruned == 1
    assert queue.get_job(job["id"]) is None


def test_quota_service_rejects_jobs_after_daily_limit(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    quota = QuotaService(store, max_fetch_jobs_per_day=1)

    quota.ensure_job_allowed(workspace_id=workspace["id"], user_id=owner["id"])
    store.record_usage_event(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        event_type="source_fetch",
        quantity=1,
    )

    with pytest.raises(QuotaExceeded) as excinfo:
        quota.ensure_job_allowed(workspace_id=workspace["id"], user_id=owner["id"])

    assert excinfo.value.code == "quota_exceeded"
