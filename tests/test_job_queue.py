import json

import pytest
from datetime import datetime, timedelta, timezone

from src.services.feed_run import SourceOutcome
from src.services.job_eligibility import JobIneligibleError
from src.services.job_queue import JobQueue
from src.services.quota import QuotaExceeded, QuotaService
from src.services.source_health import SourceHealthService
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


def test_job_queue_summary_omits_heavy_fields_and_keeps_active_jobs(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    active = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_fetch",
        payload={"large": "private"},
    )
    terminal = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={"large": "private"},
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET created_at = '2026-07-01T00:00:00+00:00'
        WHERE id = ?
        """,
        (active["id"],),
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'partial',
            result_json = ?,
            error_code = ?,
            error_message = ?,
            created_at = '2026-07-02T00:00:00+00:00',
            finished_at = '2026-07-02T00:01:00+00:00'
        WHERE id = ?
        """,
        (
            json.dumps(
                {
                    "message": "safe summary",
                    "snapshot_created": True,
                    "new_item_count": 2,
                    "source_outcomes": [
                        {"source_id": "one", "status": "succeeded"},
                        {"source_id": "two", "status": "failed"},
                    ],
                    "response_schemas": [{"source_id": "two", "private": "large"}],
                }
            ),
            "E" * 100,
            "M" * 400,
            terminal["id"],
        ),
    )
    store.connect().commit()

    summaries = queue.list_job_summaries(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        limit=1,
        include_active=True,
    )

    assert [job["id"] for job in summaries] == [terminal["id"], active["id"]]
    assert summaries[0]["result"] == {
        "message": "safe summary",
        "snapshot_created": True,
        "new_item_count": 2,
        "failed_source_count": 1,
    }
    assert summaries[0]["error_code"] == "E" * 64
    assert summaries[0]["error_message"] == "M" * 240
    rendered = json.dumps(summaries)
    assert "payload_json" not in rendered
    assert "result_json" not in rendered
    assert "response_schemas" not in rendered
    assert "private" not in rendered

    source_fetch_only = queue.list_job_summaries(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_types=["source_fetch"],
        limit=1,
        include_active=True,
    )
    feed_refresh_only = queue.list_job_summaries(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_types=["user_feed_refresh"],
        limit=1,
        include_active=True,
    )
    assert [job["id"] for job in source_fetch_only] == [active["id"]]
    assert [job["id"] for job in feed_refresh_only] == [terminal["id"]]

    indexes = {
        str(row["name"])
        for row in store.connect().execute("PRAGMA index_list(fetch_jobs)").fetchall()
    }
    assert "idx_fetch_jobs_workspace_created" in indexes
    assert "idx_fetch_jobs_workspace_user_created" in indexes
    query_plan = store.connect().execute(
        """
        EXPLAIN QUERY PLAN
        SELECT id FROM fetch_jobs
        WHERE workspace_id = ? AND user_id = ?
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (workspace["id"], owner["id"]),
    ).fetchall()
    assert any(
        "idx_fetch_jobs_workspace_user_created" in str(row["detail"])
        for row in query_plan
    )

    store.connect().execute(
        "UPDATE fetch_jobs SET result_json = '{invalid' WHERE id = ?",
        (terminal["id"],),
    )
    store.connect().commit()
    invalid_result_summary = queue.list_job_summaries(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        limit=1,
    )
    assert invalid_result_summary[0]["id"] == terminal["id"]
    assert "result" not in invalid_result_summary[0]


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


def test_job_queue_returns_safe_descriptors_after_stale_recovery(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Recovery Feed",
        config={"url": "https://example.com/recovery.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_fetch",
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"source_type": "rss"},
    )
    claimed = queue.claim_next_job(worker_id="worker-1", lease_seconds=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    store.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        (past.isoformat(), claimed["id"]),
    )
    store.connect().commit()

    recovered = queue.recover_stale_running_jobs()

    assert recovered == [
        {
            "job_id": job["id"],
            "workspace_id": workspace["id"],
            "user_id": owner["id"],
            "source_id": source_id,
            "subscription_id": subscription["id"],
            "attempts": 1,
            "status": "queued",
        }
    ]


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


def _source_health_job(store, workspace, owner, *, source_index=0):
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name=f"Retry Health {source_index}",
        config={"url": f"https://example.com/retry-health-{source_index}.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_fetch",
        payload={},
    )
    SourceHealthService(store).apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at="2026-07-18T01:00:00+00:00",
        outcomes=(
            SourceOutcome(
                source_id=source_id,
                subscription_id=subscription["id"],
                source_key=f"rss:retry-health-{source_index}",
                analysis_mode="full",
                status="succeeded",
                fetched_count=0,
            ),
        ),
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'partial',
            result_json = '{"fetched_count":0,"run_status":"partial","snapshot_id":"snap-old"}',
            started_at = '2026-07-18T00:59:00+00:00'
        WHERE id = ?
        """,
        (job["id"],),
    )
    store.connect().commit()
    return source_id, subscription, job


def test_retry_job_reopens_health_application_inside_caller_transaction(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    _source_id, subscription, job = _source_health_job(
        store, workspace, owner
    )
    before = SourceHealthService(store).get_health(subscription["id"])
    conn = store.connect()
    conn.execute("BEGIN IMMEDIATE")

    retried = queue.retry_job(job["id"], user_id=owner["id"], commit=False)
    during = SourceHealthService(store).get_health(subscription["id"])

    assert retried["status"] == "queued"
    assert retried["result_json"] is None
    assert retried["started_at"] is None
    assert conn.in_transaction is True
    assert during["last_job_id"] is None
    assert during["status"] == before["status"] == "healthy"
    assert during["last_fetched_count"] == before["last_fetched_count"] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 0

    conn.rollback()

    rolled_back = SourceHealthService(store).get_health(subscription["id"])
    rolled_back_job = queue.get_job(job["id"])
    assert rolled_back_job["status"] == "partial"
    assert rolled_back_job["result_json"] == {
        "fetched_count": 0,
        "run_status": "partial",
        "snapshot_id": "snap-old",
    }
    assert rolled_back_job["started_at"] == "2026-07-18T00:59:00+00:00"
    assert rolled_back["last_job_id"] == job["id"]
    assert conn.execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 1


def test_retry_user_feed_refresh_reopens_all_applied_subscription_health(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    sources = []
    subscriptions = []
    for index in range(2):
        source_id = store.create_source(
            workspace_id=workspace["id"],
            scope="public",
            owner_user_id=owner["id"],
            source_type="rss",
            display_name=f"Refresh Retry {index}",
            config={"url": f"https://example.com/refresh-retry-{index}.xml"},
        )
        sources.append(source_id)
        subscriptions.append(
            store.create_subscription(user_id=owner["id"], source_id=source_id)
        )
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )
    SourceHealthService(store).apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at="2026-07-18T02:00:00+00:00",
        outcomes=tuple(
            SourceOutcome(
                source_id=source_id,
                subscription_id=subscription["id"],
                source_key=f"rss:refresh-retry-{index}",
                analysis_mode="full",
                status="succeeded",
                fetched_count=index,
            )
            for index, (source_id, subscription) in enumerate(
                zip(sources, subscriptions, strict=True)
            )
        ),
    )
    store.connect().execute(
        "UPDATE fetch_jobs SET status = 'partial' WHERE id = ?", (job["id"],)
    )
    store.connect().commit()

    retried = queue.retry_job(job["id"], user_id=owner["id"])

    assert retried["status"] == "queued"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 0
    for index, subscription in enumerate(subscriptions):
        health = SourceHealthService(store).get_health(subscription["id"])
        assert health["last_job_id"] is None
        assert health["status"] == "healthy"
        assert health["last_fetched_count"] == index


def test_retry_without_health_or_application_still_queues_job(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={},
    )
    queue.cancel_job(job["id"], user_id=owner["id"])

    retried = queue.retry_job(job["id"], user_id=owner["id"])

    assert retried["status"] == "queued"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE last_job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 0


def test_rejected_retry_does_not_clear_health_application(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    other = store.create_user(
        workspace_id=workspace["id"],
        username="other-retry-user",
        password="other-password",
        role="member",
    )
    queue = JobQueue(store)
    _source_id, subscription, job = _source_health_job(
        store, workspace, owner
    )

    with pytest.raises(PermissionError, match="another user's job"):
        queue.retry_job(job["id"], user_id=other["id"])

    assert SourceHealthService(store).get_health(subscription["id"])[
        "last_job_id"
    ] == job["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 1

    store.connect().execute(
        "UPDATE fetch_jobs SET status = 'queued' WHERE id = ?", (job["id"],)
    )
    store.connect().commit()
    with pytest.raises(ValueError, match="failed, partial, or cancelled"):
        queue.retry_job(job["id"], user_id=owner["id"])

    assert SourceHealthService(store).get_health(subscription["id"])[
        "last_job_id"
    ] == job["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 1


def test_retry_returning_existing_active_job_preserves_terminal_health(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    source_id, subscription, terminal = _source_health_job(
        store, workspace, owner
    )
    active, created = queue.create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={},
    )

    returned = queue.retry_job(terminal["id"], user_id=owner["id"])

    assert created is True
    assert returned["id"] == active["id"] != terminal["id"]
    assert SourceHealthService(store).get_health(subscription["id"])[
        "last_job_id"
    ] == terminal["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (terminal["id"],),
    ).fetchone()[0] == 1


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
