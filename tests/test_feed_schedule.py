from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from src.services.job_queue import JobQueue
from src.services.quota import QuotaService
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


ALLOWED_INTERVALS = (60, 180, 360, 720, 1440)


def _store_with_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    return store, workspace, owner


def _subscribe(store, workspace, user, *, suffix="feed"):
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=user["id"],
        source_type="rss",
        display_name=f"Feed {suffix}",
        config={"name": f"Feed {suffix}", "url": f"https://example.com/{suffix}.xml"},
        source_key=f"rss:https://example.com/{suffix}.xml",
    )
    subscription = store.create_subscription(user_id=user["id"], source_id=source_id)
    return source_id, subscription


def _schedule_service(store, *, quota=None):
    from src.services.feed_schedule import FeedScheduleService

    return FeedScheduleService(store, quota=quota)


def _active_jobs(store, user_id, job_type="user_feed_refresh"):
    return store.connect().execute(
        """
        SELECT * FROM fetch_jobs
        WHERE user_id = ? AND job_type = ? AND status IN ('queued', 'running')
        ORDER BY created_at
        """,
        (user_id, job_type),
    ).fetchall()


def test_schedule_schema_is_additive_and_missing_row_projects_defaults(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)

    columns = {
        row["name"]: row
        for row in store.connect().execute("PRAGMA table_info(user_feed_schedules)").fetchall()
    }
    schedule = _schedule_service(store).get_user_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert set(columns) == {
        "user_id",
        "workspace_id",
        "enabled",
        "interval_minutes",
        "next_run_at",
        "last_evaluated_at",
        "last_enqueued_at",
        "last_job_id",
        "last_skip_reason",
        "created_at",
        "updated_at",
    }
    assert columns["user_id"]["pk"] == 1
    assert schedule == {
        "user_id": owner["id"],
        "workspace_id": workspace["id"],
        "enabled": False,
        "interval_minutes": 360,
        "next_run_at": None,
        "last_evaluated_at": None,
        "last_enqueued_at": None,
        "last_job_id": None,
        "last_skip_reason": None,
        "created_at": None,
        "updated_at": None,
    }


def test_schedule_validates_interval_and_applies_enable_change_disable_time_semantics(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    schedules = _schedule_service(store)
    first = datetime(2026, 7, 11, 1, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="interval_minutes"):
        schedules.update_user_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            enabled=True,
            interval_minutes=61,
            now=first,
        )

    enabled = schedules.update_user_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        enabled=True,
        interval_minutes=360,
        now=first,
    )
    changed_at = first + timedelta(minutes=10)
    changed = schedules.update_user_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        interval_minutes=180,
        now=changed_at,
    )
    disabled = schedules.update_user_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        enabled=False,
        now=changed_at + timedelta(minutes=1),
    )

    assert enabled["next_run_at"] == first.isoformat()
    assert changed["next_run_at"] == (changed_at + timedelta(minutes=180)).isoformat()
    assert disabled["enabled"] is False
    assert disabled["interval_minutes"] == 180
    assert disabled["next_run_at"] is None


def test_enabling_schedule_requires_an_enabled_subscription(tmp_path, monkeypatch):
    from src.services.feed_schedule import NoEnabledSubscriptionsError

    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)

    with pytest.raises(NoEnabledSubscriptionsError) as exc_info:
        _schedule_service(store).update_user_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            enabled=True,
            interval_minutes=360,
        )

    assert exc_info.value.code == "no_enabled_subscriptions"


def test_disabling_schedule_cancels_only_queued_scheduled_refresh(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    schedules = _schedule_service(store)
    queue = JobQueue(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True
    )
    scheduled, created = queue.create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "scheduled_service_refresh"},
        priority=-10,
    )
    assert created is True

    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=False
    )

    assert queue.get_job(scheduled["id"])["status"] == "cancelled"


def test_disabling_schedule_does_not_cancel_running_scheduled_refresh(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    schedules = _schedule_service(store)
    queue = JobQueue(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True
    )
    scheduled, _ = queue.create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "scheduled_service_refresh"},
        priority=-10,
    )
    claimed = queue.claim_next_job(worker_id="worker-running")
    assert claimed["id"] == scheduled["id"]

    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=False
    )

    assert queue.get_job(scheduled["id"])["status"] == "running"


def test_user_feed_refresh_creation_is_atomically_deduplicated(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)

    first, first_created = queue.create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"], user_id=owner["id"], payload={"reason": "manual"}
    )
    second, second_created = queue.create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "scheduled_service_refresh"},
        priority=-10,
    )

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert len(_active_jobs(store, owner["id"])) == 1


def test_retrying_terminal_refresh_reuses_another_active_refresh(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    queue = JobQueue(store)
    terminal = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )
    claimed = queue.claim_next_job(worker_id="worker-terminal")
    queue.complete_job(
        claimed["id"],
        status="failed",
        error_code="FetchFailed",
        error_message="failed",
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )
    active = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )

    retried = queue.retry_job(terminal["id"], user_id=owner["id"])

    assert retried["id"] == active["id"]
    assert len(_active_jobs(store, owner["id"])) == 1


def test_two_connections_competing_for_due_schedule_create_one_job(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    due_at = datetime(2026, 7, 11, 2, 0, tzinfo=timezone.utc)
    _schedule_service(store).update_user_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        enabled=True,
        interval_minutes=60,
        now=due_at,
    )
    store.close()
    barrier = Barrier(2)

    def enqueue():
        competing_store = ServiceStore(tmp_path)
        barrier.wait(timeout=5)
        try:
            return _schedule_service(competing_store).enqueue_due(now=due_at)
        finally:
            competing_store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: enqueue(), range(2)))

    verify_store = ServiceStore(tmp_path)
    jobs = _active_jobs(verify_store, owner["id"])
    schedule = _schedule_service(verify_store).get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )
    usage = verify_store.count_usage_since(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        event_types=["user_feed_refresh"],
        since=due_at - timedelta(days=1),
    )

    assert sum(result["enqueued"] for result in results) == 1
    assert len(jobs) == 1
    assert usage == 1
    assert schedule["last_job_id"] == jobs[0]["id"]
    assert schedule["next_run_at"] == (due_at + timedelta(minutes=60)).isoformat()


def test_due_schedule_reuses_active_refresh_without_charging_quota(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    existing, _ = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"], user_id=owner["id"], payload={"reason": "manual"}
    )

    result = schedules.enqueue_due(now=now)
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert result["deduplicated"] == 1
    assert schedule["last_job_id"] == existing["id"]
    assert schedule["last_skip_reason"] == "active_user_feed_refresh"
    assert schedule["next_run_at"] == (now + timedelta(minutes=360)).isoformat()
    assert store.count_usage_since(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        event_types=["user_feed_refresh"],
        since=now - timedelta(days=1),
    ) == 0


def test_disabling_user_closes_feed_schedule_without_future_run(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    store.update_user(owner["id"], enabled=False)

    schedules.enqueue_due(now=now)
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert not _active_jobs(store, owner["id"])
    assert schedule["enabled"] is False
    assert schedule["last_skip_reason"] == "user_disabled"
    assert schedule["next_run_at"] is None


def test_due_schedule_defensively_disables_viewer_without_enqueuing(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    store.connect().execute(
        "UPDATE users SET role = 'viewer' WHERE id = ?",
        (owner["id"],),
    )
    store.connect().commit()

    result = schedules.enqueue_due(now=now)
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert result["enqueued"] == 0
    assert result["skipped"] == 1
    assert result["outcomes"][0]["reason"] == "user_read_only"
    assert not _active_jobs(store, owner["id"])
    assert schedule["enabled"] is False
    assert schedule["next_run_at"] is None
    assert schedule["last_skip_reason"] == "user_read_only"


def test_role_downgrade_to_viewer_disables_schedule_and_cancels_queued_auto_job(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True
    )
    queued, created = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "scheduled_service_refresh"},
        priority=-10,
    )
    assert created is True

    store.update_user(owner["id"], role="viewer")
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert schedule["enabled"] is False
    assert schedule["next_run_at"] is None
    assert schedule["last_skip_reason"] == "user_read_only"
    assert JobQueue(store).get_job(queued["id"])["status"] == "cancelled"


def test_due_schedule_skips_when_enabled_subscriptions_disappear(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _source_id, subscription = _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    store.update_subscription(subscription["id"], enabled=False)

    schedules.enqueue_due(now=now)
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert not _active_jobs(store, owner["id"])
    assert schedule["last_skip_reason"] == "no_enabled_subscriptions"
    assert schedule["next_run_at"] == (now + timedelta(minutes=360)).isoformat()


def test_due_schedule_skips_exhausted_quota_and_advances_interval(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    quota = QuotaService(store, max_fetch_jobs_per_day=1)
    schedules = _schedule_service(store, quota=quota)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    store.record_usage_event(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        event_type="source_fetch",
        quantity=1,
    )

    schedules.enqueue_due(now=now)
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert not _active_jobs(store, owner["id"])
    assert schedule["last_skip_reason"] == "quota_exceeded"
    assert schedule["next_run_at"] == (now + timedelta(minutes=360)).isoformat()


def test_due_schedule_defers_for_feed_migration_without_enqueuing(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"], user_id=owner["id"], job_type="source_fetch"
    )
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 2")
    store.connect().commit()
    assert store.feed_v2_migration_required() is True

    schedules.enqueue_due(now=now)
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert not _active_jobs(store, owner["id"])
    assert schedule["last_skip_reason"] == "migration_required"
    assert schedule["next_run_at"] == (now + timedelta(minutes=5)).isoformat()


def test_due_schedule_defers_for_active_source_fetch_without_hot_loop(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    source_id, _subscription = _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_fetch",
    )

    first = schedules.enqueue_due(now=now)
    second = schedules.enqueue_due(now=now + timedelta(minutes=1))
    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )

    assert first["evaluated"] == 1
    assert second["evaluated"] == 0
    assert not _active_jobs(store, owner["id"])
    assert schedule["last_skip_reason"] == "active_source_fetch"
    assert schedule["next_run_at"] == (now + timedelta(minutes=5)).isoformat()


def test_overdue_schedule_backfills_only_one_job_and_preserves_full_window(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    schedules = _schedule_service(store)
    now = datetime.now(timezone.utc)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    store.connect().execute(
        "UPDATE user_feed_schedules SET next_run_at = ? WHERE user_id = ?",
        ((now - timedelta(days=3)).isoformat(), owner["id"]),
    )
    store.connect().commit()

    first = schedules.enqueue_due(now=now)
    second = schedules.enqueue_due(now=now)
    jobs = _active_jobs(store, owner["id"])

    assert first["enqueued"] == 1
    assert second["evaluated"] == 0
    assert len(jobs) == 1
    assert jobs[0]["priority"] == -10
    assert store._job(jobs[0])["payload_json"] == {"reason": "scheduled_service_refresh"}
    assert not (tmp_path / "site").exists()


@pytest.mark.parametrize("terminal_status", ["partial", "failed"])
def test_scheduled_partial_or_failed_job_does_not_disable_plan(
    tmp_path, monkeypatch, terminal_status
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    schedules = _schedule_service(store)
    schedules.update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    schedules.enqueue_due(now=now)
    queue = JobQueue(store)
    claimed = queue.claim_next_job(worker_id=f"worker-{terminal_status}")

    queue.complete_job(
        claimed["id"],
        status=terminal_status,
        result={"run_status": terminal_status},
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )

    schedule = schedules.get_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"]
    )
    assert schedule["enabled"] is True
    assert schedule["next_run_at"] == (now + timedelta(minutes=360)).isoformat()


def test_worker_once_enqueues_due_schedules_before_claiming_regular_job(tmp_path, monkeypatch):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    _subscribe(store, workspace, owner)
    now = datetime.now(timezone.utc)
    _schedule_service(store).update_user_schedule(
        workspace_id=workspace["id"], user_id=owner["id"], enabled=True, now=now
    )
    regular = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        priority=0,
    )
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda _payload: {"ok": True, "source_type": "rss"},
    )

    result = run_worker_once(data_dir=str(tmp_path), worker_id="schedule-order-worker")

    assert result["id"] == regular["id"]
    scheduled = _active_jobs(store, owner["id"])
    assert len(scheduled) == 1
    assert store._job(scheduled[0])["payload_json"] == {
        "reason": "scheduled_service_refresh"
    }


def test_schedule_path_has_no_legacy_scheduler_or_publisher_dependency():
    from src.services import feed_schedule, worker

    schedule_source = inspect.getsource(feed_schedule)
    worker_source = inspect.getsource(worker)

    assert "services.scheduler" not in schedule_source
    assert "LegacyPublisher" not in schedule_source
    assert "HorizonOrchestrator.run(" not in schedule_source
    assert "data/site" not in schedule_source
    assert "services.scheduler" not in worker_source
    assert "LegacyPublisher" not in worker_source
    assert "HorizonOrchestrator.run(" not in worker_source
