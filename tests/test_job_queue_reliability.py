import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from src.services.feed_run import SourceOutcome
from src.services.job_queue import JobQueue
from src.services.source_health import SourceHealthService
from src.services.user_feed_store import UserFeedSnapshotInput, UserFeedStore
from src.storage.service_store import ServiceStore


def _stores_with_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    first = ServiceStore(tmp_path)
    first.initialize()
    second = ServiceStore(tmp_path)
    second.initialize()
    return first, second, first.get_default_workspace(), first.get_user_by_username("owner")


def _create_job(queue, workspace, owner, **kwargs):
    return queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        **kwargs,
    )


def test_each_service_store_connection_enables_sqlite_reliability_pragmas(tmp_path, monkeypatch):
    first, second, _workspace, _owner = _stores_with_owner(tmp_path, monkeypatch)

    for store in (first, second):
        connection = store.connect()
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 5_000


def test_service_store_supports_delete_journal_for_docker_bind_mounts(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_SQLITE_JOURNAL_MODE", "DELETE")

    store = ServiceStore(tmp_path)
    store.initialize()

    assert store.connect().execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"


def test_two_process_style_connections_can_initialize_fresh_database_concurrently(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    barrier = Barrier(2)

    def initialize_store():
        store = ServiceStore(tmp_path)
        barrier.wait()
        store.initialize()
        return store.connect().execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result(timeout=10) for future in [
            executor.submit(initialize_store),
            executor.submit(initialize_store),
        ]]

    assert results == [1, 1]


def test_service_store_initializes_reliability_schema_and_feed_constraints(tmp_path, monkeypatch):
    store, _second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    connection = store.connect()
    job_columns = {
        row["name"]: row
        for row in connection.execute("PRAGMA table_info(fetch_jobs)").fetchall()
    }
    snapshot_columns = {
        row["name"]: row
        for row in connection.execute("PRAGMA table_info(user_feed_snapshots)").fetchall()
    }
    item_columns = {
        row["name"]: row
        for row in connection.execute("PRAGMA table_info(user_feed_items)").fetchall()
    }
    heartbeat_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(worker_heartbeats)").fetchall()
    }

    assert "claim_token" in job_columns
    assert snapshot_columns["schema_version"]["notnull"] == 1
    assert str(snapshot_columns["schema_version"]["dflt_value"]).strip("'\"") == "2"
    assert {"source_id", "subscription_id", "position"}.issubset(item_columns)
    assert {
        "worker_id",
        "state",
        "started_at",
        "heartbeat_at",
        "current_job_id",
        "last_job_id",
        "last_error_code",
        "updated_at",
    }.issubset(heartbeat_columns)

    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO user_feed_snapshots (
            id, workspace_id, user_id, job_id, generated_at,
            item_count, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, 0, '{}', ?)
        """,
        ("snapshot-1", workspace["id"], owner["id"], "job-once", now, now),
    )
    assert connection.execute(
        "SELECT schema_version FROM user_feed_snapshots WHERE id = 'snapshot-1'"
    ).fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO user_feed_snapshots (
                id, workspace_id, user_id, job_id, generated_at,
                item_count, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 0, '{}', ?)
            """,
            ("snapshot-2", workspace["id"], owner["id"], "job-once", now, now),
        )

    connection.execute(
        """
        INSERT INTO user_feed_items (
            id, workspace_id, user_id, snapshot_id, article_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("item-1", workspace["id"], owner["id"], "snapshot-1", "article-1", now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO user_feed_items (
                id, workspace_id, user_id, snapshot_id, article_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("item-2", workspace["id"], owner["id"], "snapshot-1", "article-1", now),
        )
    connection.rollback()


def test_two_independent_connections_claim_a_job_only_once(tmp_path, monkeypatch):
    first, second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    first_queue = JobQueue(first)
    second_queue = JobQueue(second)
    job = _create_job(first_queue, workspace, owner)
    barrier = Barrier(2)

    def claim(queue, worker_id):
        barrier.wait()
        return queue.claim_next_job(worker_id=worker_id, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(claim, first_queue, "worker-a"),
            executor.submit(claim, second_queue, "worker-b"),
        ]
        results = [future.result(timeout=5) for future in futures]

    claims = [result for result in results if result is not None]
    assert len(claims) == 1
    assert claims[0]["id"] == job["id"]
    assert claims[0]["claim_token"]
    assert first_queue.get_job(job["id"])["attempts"] == 1


def test_retry_cannot_overwrite_a_job_claimed_after_a_stale_read(tmp_path, monkeypatch):
    first, _second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(first)
    job = _create_job(queue, workspace, owner)
    claimed = queue.claim_next_job(worker_id="worker-a", lease_seconds=60)
    original_get_job = queue.get_job
    stale = {**claimed, "status": "failed"}
    calls = 0

    def stale_first_read(job_id):
        nonlocal calls
        calls += 1
        return stale if calls == 1 else original_get_job(job_id)

    monkeypatch.setattr(queue, "get_job", stale_first_read)

    with pytest.raises(ValueError, match="failed, partial, or cancelled"):
        queue.retry_job(job["id"], user_id=owner["id"])

    actual = first.connect().execute(
        "SELECT status, worker_id, claim_token FROM fetch_jobs WHERE id = ?",
        (job["id"],),
    ).fetchone()
    assert (actual["status"], actual["worker_id"], actual["claim_token"]) == (
        "running",
        "worker-a",
        claimed["claim_token"],
    )


def test_concurrent_manual_retry_reopens_health_once(tmp_path, monkeypatch):
    first, second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    source_id = first.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Concurrent Retry Health",
        config={"url": "https://example.com/concurrent-retry.xml"},
    )
    subscription = first.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    first_queue = JobQueue(first)
    second_queue = JobQueue(second)
    job = first_queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_fetch",
        payload={},
    )
    SourceHealthService(first).apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at="2026-07-18T03:00:00+00:00",
        outcomes=(
            SourceOutcome(
                source_id=source_id,
                subscription_id=subscription["id"],
                source_key="rss:concurrent-retry",
                analysis_mode="full",
                status="succeeded",
                fetched_count=0,
            ),
        ),
    )
    first.connect().execute(
        "UPDATE fetch_jobs SET status = 'partial' WHERE id = ?", (job["id"],)
    )
    first.connect().commit()
    barrier = Barrier(2)

    def retry(queue):
        barrier.wait()
        try:
            return queue.retry_job(job["id"], user_id=owner["id"])["status"]
        except ValueError:
            return "not_retryable"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in (
                executor.submit(retry, first_queue),
                executor.submit(retry, second_queue),
            )
        ]

    assert sorted(results) == ["not_retryable", "queued"]
    assert first_queue.get_job(job["id"])["status"] == "queued"
    assert SourceHealthService(first).get_health(subscription["id"])[
        "last_job_id"
    ] is None
    assert first.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 0


def test_stale_claim_token_cannot_complete_reclaimed_job(tmp_path, monkeypatch):
    first, second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    first_queue = JobQueue(first)
    second_queue = JobQueue(second)
    job = _create_job(first_queue, workspace, owner, max_attempts=2)
    stale_claim = first_queue.claim_next_job(worker_id="worker-a", lease_seconds=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    first.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        (past.isoformat(), job["id"]),
    )
    first.connect().commit()

    assert second_queue.requeue_stale_running_jobs() == 1
    current_claim = second_queue.claim_next_job(worker_id="worker-b", lease_seconds=60)

    with pytest.raises(PermissionError, match="claim"):
        first_queue.complete_job(
            job["id"],
            status="succeeded",
            result={"worker": "stale"},
            worker_id="worker-a",
            claim_token=stale_claim["claim_token"],
        )

    loaded = second_queue.get_job(job["id"])
    assert loaded["status"] == "running"
    assert loaded["worker_id"] == "worker-b"
    assert loaded["claim_token"] == current_claim["claim_token"]


def test_expired_current_claim_cannot_complete_before_requeue(tmp_path, monkeypatch):
    first, _second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(first)
    job = _create_job(queue, workspace, owner)
    claim = queue.claim_next_job(worker_id="worker-a", lease_seconds=60)
    first.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), job["id"]),
    )
    first.connect().commit()

    UserFeedStore(first).save_run_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        snapshot=UserFeedSnapshotInput(
            run_id="run-expired",
            run_status="succeeded",
            generated_at=datetime.now(timezone.utc).isoformat(),
            items=(),
        ),
        commit=False,
    )

    with pytest.raises(PermissionError, match="claim"):
        queue.complete_job(
            job["id"],
            status="succeeded",
            result={"worker": "expired"},
            worker_id="worker-a",
            claim_token=claim["claim_token"],
        )

    loaded = queue.get_job(job["id"])
    assert loaded["status"] == "running"
    assert loaded["claim_token"] == claim["claim_token"]
    assert first.connect().execute(
        "SELECT COUNT(*) FROM user_feed_snapshots WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 0


def test_expired_current_claim_cannot_fail_or_retry_before_requeue(tmp_path, monkeypatch):
    first, _second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(first)
    job = _create_job(queue, workspace, owner)
    claim = queue.claim_next_job(worker_id="worker-a", lease_seconds=60)
    first.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), job["id"]),
    )
    first.connect().commit()

    with pytest.raises(PermissionError, match="claim"):
        queue.fail_or_retry_job(
            job["id"],
            error_code="expired",
            error_message="expired worker failed late",
            retry_base_seconds=0,
            worker_id="worker-a",
            claim_token=claim["claim_token"],
        )

    loaded = queue.get_job(job["id"])
    assert loaded["status"] == "running"
    assert loaded["claim_token"] == claim["claim_token"]


def test_fail_or_retry_requires_the_current_worker_claim(tmp_path, monkeypatch):
    first, second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    first_queue = JobQueue(first)
    second_queue = JobQueue(second)
    job = _create_job(first_queue, workspace, owner, max_attempts=2)
    stale_claim = first_queue.claim_next_job(worker_id="worker-a", lease_seconds=1)
    first.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), job["id"]),
    )
    first.connect().commit()
    second_queue.requeue_stale_running_jobs()
    current_claim = second_queue.claim_next_job(worker_id="worker-b", lease_seconds=60)

    with pytest.raises(PermissionError, match="claim"):
        first_queue.fail_or_retry_job(
            job["id"],
            error_code="stale",
            error_message="stale worker failed late",
            retry_base_seconds=0,
            worker_id="worker-a",
            claim_token=stale_claim["claim_token"],
        )

    retried = second_queue.fail_or_retry_job(
        job["id"],
        error_code="current",
        error_message="retry current claim",
        retry_base_seconds=0,
        worker_id="worker-b",
        claim_token=current_claim["claim_token"],
    )
    assert retried["status"] == "failed"
    assert retried["claim_token"] is None
    assert retried["error_code"] == "current"


def test_current_claim_can_extend_lease_but_stale_token_cannot(tmp_path, monkeypatch):
    first, _second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(first)
    job = _create_job(queue, workspace, owner)
    claim = queue.claim_next_job(worker_id="worker-a", lease_seconds=10)
    original_lease = datetime.fromisoformat(claim["locked_until"])

    renewed = queue.extend_job_lease(
        job["id"],
        worker_id="worker-a",
        claim_token=claim["claim_token"],
        lease_seconds=60,
    )

    assert datetime.fromisoformat(renewed["locked_until"]) > original_lease
    with pytest.raises(PermissionError, match="claim"):
        queue.extend_job_lease(
            job["id"],
            worker_id="worker-a",
            claim_token="stale-token",
            lease_seconds=120,
        )
    assert queue.get_job(job["id"])["locked_until"] == renewed["locked_until"]


def test_worker_heartbeats_track_lifecycle_and_fixed_freshness_threshold(tmp_path, monkeypatch):
    from src.services.runtime_status import RuntimeStatusService, WORKER_STALE_AFTER_SECONDS

    first, _second, workspace, owner = _stores_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(first)
    job = _create_job(queue, workspace, owner)
    started_at = datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)

    starting = first.upsert_worker_heartbeat("worker-a", "starting", now=started_at)
    idle = first.upsert_worker_heartbeat("worker-a", "idle", now=started_at + timedelta(seconds=1))
    running = first.upsert_worker_heartbeat(
        "worker-a",
        "running",
        current_job_id=job["id"],
        now=started_at + timedelta(seconds=2),
    )
    stopping = first.upsert_worker_heartbeat(
        "worker-a",
        "stopping",
        last_job_id=job["id"],
        last_error_code="shutdown",
        now=started_at + timedelta(seconds=3),
    )
    runtime = RuntimeStatusService(first)
    fresh = runtime.get_worker("worker-a", now=started_at + timedelta(seconds=3 + WORKER_STALE_AFTER_SECONDS))
    stale = runtime.get_worker(
        "worker-a",
        now=started_at + timedelta(seconds=4 + WORKER_STALE_AFTER_SECONDS),
    )

    assert starting["started_at"] == started_at.isoformat()
    assert idle["state"] == "idle"
    assert running["current_job_id"] == job["id"]
    assert stopping["state"] == "stopping"
    assert stopping["current_job_id"] is None
    assert stopping["last_job_id"] == job["id"]
    assert stopping["last_error_code"] == "shutdown"
    assert fresh["stale_after_seconds"] == WORKER_STALE_AFTER_SECONDS
    assert fresh["is_stale"] is False
    assert stale["is_stale"] is True
    assert runtime.list_workers(now=started_at + timedelta(seconds=3))[0]["worker_id"] == "worker-a"


def test_worker_heartbeat_rejects_unknown_state(tmp_path, monkeypatch):
    first, _second, _workspace, _owner = _stores_with_owner(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="state"):
        first.upsert_worker_heartbeat("worker-a", "lost")
