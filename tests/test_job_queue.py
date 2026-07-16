import pytest
from datetime import datetime, timedelta, timezone

from src.services.job_eligibility import JobIneligibleError
from src.services.job_queue import JobQueue
from src.services.quota import QuotaExceeded, QuotaService
from src.services.usage_attempt_meter import UsageAttemptMeter
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
    queue.complete_job(
        claimed["id"],
        status="succeeded",
        result={"count": 1},
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )

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
    first_diagnostics = {
        "run_id": "run_retry",
        "run_status": "failed",
        "item_count": 0,
        "source_outcomes": [],
        "issues": [],
    }

    retried = queue.fail_or_retry_job(
        claimed["id"],
        error_code="RuntimeError",
        error_message="temporary failure",
        retryable=True,
        retry_base_seconds=0,
        result=first_diagnostics,
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )
    second_claim = queue.claim_next_job(worker_id="worker-1", lease_seconds=60)
    final_diagnostics = {**first_diagnostics, "run_id": "run_final"}
    failed = queue.fail_or_retry_job(
        second_claim["id"],
        error_code="RuntimeError",
        error_message="final failure",
        retryable=True,
        retry_base_seconds=0,
        result=final_diagnostics,
        worker_id=second_claim["worker_id"],
        claim_token=second_claim["claim_token"],
    )

    assert retried["id"] == job["id"]
    assert retried["status"] == "queued"
    assert retried["attempts"] == 1
    assert retried["result_json"] == first_diagnostics
    assert second_claim["attempts"] == 2
    assert failed["status"] == "failed"
    assert failed["error_message"] == "final failure"
    assert failed["result_json"] == final_diagnostics
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
    completed = queue.complete_job(
        claimed["id"],
        status="succeeded",
        result={"ok": True},
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )
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


def test_retry_job_can_join_caller_transaction(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
    )
    queue.cancel_job(job["id"], user_id=owner["id"])

    conn = store.connect()
    conn.execute("BEGIN IMMEDIATE")
    retried = queue.retry_job(job["id"], user_id=owner["id"], commit=False)
    assert retried["status"] == "queued"
    conn.rollback()

    assert queue.get_job(job["id"])["status"] == "cancelled"


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


def test_quota_service_atomically_caps_workspace_and_provider_fetch_attempts(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
    )
    quota = QuotaService(
        store,
        max_workspace_fetch_attempts_per_day=1,
        max_provider_fetch_attempts_per_day=1,
    )

    quota.admit_fetch_attempt(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        provider="rss",
        source_id="src_shared",
    )

    with pytest.raises(QuotaExceeded, match="workspace fetch attempt quota exceeded"):
        quota.admit_fetch_attempt(
            workspace_id=workspace["id"],
            user_id=member["id"],
            provider="github",
            source_id="src_other",
        )
    usage = store.connect().execute(
        "SELECT COUNT(*) AS total FROM usage_events WHERE event_type = 'fetch_attempt'"
    ).fetchone()
    assert int(usage["total"]) == 1


def test_fetch_attempt_rechecks_job_source_eligibility_before_charging(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Attempt Eligibility",
        config={"url": "https://example.com/attempt-eligibility.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    queue = JobQueue(store)
    job, _created = queue.create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    queue.claim_next_job(worker_id="attempt-worker")
    store.connect().execute(
        "UPDATE user_subscriptions SET enabled = 0 WHERE id = ?",
        (subscription["id"],),
    )
    store.connect().commit()

    meter = UsageAttemptMeter(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
    )
    with pytest.raises(JobIneligibleError, match="subscription_disabled"):
        meter.before_fetch_attempt(provider="rss", source_id=source_id)

    usage = store.connect().execute(
        "SELECT COUNT(*) AS total FROM usage_events WHERE event_type = 'fetch_attempt'"
    ).fetchone()
    assert int(usage["total"]) == 0
