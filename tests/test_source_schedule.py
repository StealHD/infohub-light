from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from src.services.job_queue import JobQueue
from src.services.feed_run import SourceOutcome
from src.services.quota import QuotaService
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


SOURCE_SCHEDULE_COLUMNS = {
    "subscription_id",
    "workspace_id",
    "user_id",
    "source_id",
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


def _subscribed_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Private RSS",
        config={"name": "Private RSS", "url": "https://example.com/private.xml"},
        source_key="rss:https://example.com/private.xml",
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    return store, workspace, owner, source_id, subscription


def test_source_schedule_schema_is_additive_and_projects_missing_defaults(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )

    columns = {
        row["name"]
        for row in store.connect().execute(
            "PRAGMA table_info(user_source_schedules)"
        ).fetchall()
    }
    schedule = store.get_source_schedule(subscription["id"])

    assert columns == SOURCE_SCHEDULE_COLUMNS
    assert schedule is None


def test_source_schedule_interval_constraint_and_subscription_delete_cascade(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    now = "2026-07-13T12:00:00+00:00"

    with pytest.raises(sqlite3.IntegrityError):
        store.connect().execute(
            """
            INSERT INTO user_source_schedules (
                subscription_id, workspace_id, user_id, source_id,
                enabled, interval_minutes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, 29, ?, ?)
            """,
            (subscription["id"], workspace["id"], owner["id"], source_id, now, now),
        )
    store.connect().rollback()
    store.connect().execute(
        """
        INSERT INTO user_source_schedules (
            subscription_id, workspace_id, user_id, source_id,
            enabled, interval_minutes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, 30, ?, ?)
        """,
        (subscription["id"], workspace["id"], owner["id"], source_id, now, now),
    )
    store.connect().commit()

    assert store.get_source_schedule(subscription["id"])["interval_minutes"] == 30
    assert store.delete_subscription(subscription["id"], user_id=owner["id"]) is True
    assert store.get_source_schedule(subscription["id"]) is None


def test_deleting_subscription_cancels_queued_manual_source_fetch(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    job, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    assert created is True

    assert store.delete_subscription(subscription["id"], user_id=owner["id"]) is True

    deleted_job = JobQueue(store).get_job(job["id"])
    assert deleted_job["status"] == "cancelled"
    assert deleted_job["subscription_id"] is None


def test_source_schedule_enable_change_and_disable_time_semantics(tmp_path, monkeypatch):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    service = SourceScheduleService(store)
    first = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)

    missing = service.get_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
    )
    enabled = service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
        now=first,
    )
    changed_at = first + timedelta(minutes=5)
    changed = service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        interval_minutes=60,
        now=changed_at,
    )
    disabled = service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=False,
        now=changed_at + timedelta(minutes=1),
    )

    assert missing["enabled"] is False
    assert missing["interval_minutes"] == 60
    assert enabled["next_run_at"] == first.isoformat()
    assert changed["next_run_at"] == (changed_at + timedelta(minutes=60)).isoformat()
    assert disabled["enabled"] is False
    assert disabled["interval_minutes"] == 60
    assert disabled["next_run_at"] is None


def test_source_schedule_validates_interval_and_requires_enabled_subscription(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    service = SourceScheduleService(store)

    with pytest.raises(ValueError, match="interval_minutes"):
        service.update_subscription_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            subscription_id=subscription["id"],
            enabled=True,
            interval_minutes=29,
        )
    store.update_subscription(subscription["id"], enabled=False)
    with pytest.raises(ValueError, match="enabled subscription"):
        service.update_subscription_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            subscription_id=subscription["id"],
            enabled=True,
            interval_minutes=30,
        )


def test_disabling_source_schedule_cancels_only_queued_scheduled_job(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    service = SourceScheduleService(store)
    service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
    )
    scheduled, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "scheduled_source_fetch"},
        priority=-10,
    )
    assert created is True

    service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=False,
    )

    assert JobQueue(store).get_job(scheduled["id"])["status"] == "cancelled"


def test_two_connections_competing_for_due_source_schedule_create_one_job(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    due = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
        now=due,
    )
    store.close()
    barrier = Barrier(2)

    def enqueue_once():
        local_store = ServiceStore(tmp_path)
        local_store.initialize()
        barrier.wait()
        try:
            return SourceScheduleService(local_store).enqueue_due(now=due)
        finally:
            local_store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: enqueue_once(), range(2)))

    final_store = ServiceStore(tmp_path)
    final_store.initialize()
    jobs = final_store.connect().execute(
        """
        SELECT * FROM fetch_jobs
        WHERE subscription_id = ?
          AND job_type = 'source_fetch'
          AND status IN ('queued', 'running')
        """,
        (subscription["id"],),
    ).fetchall()

    assert len(jobs) == 1
    assert sum(result["enqueued"] for result in results) == 1
    assert final_store.get_source_schedule(subscription["id"])["next_run_at"] == (
        due + timedelta(minutes=30)
    ).isoformat()


def test_exhausted_apify_pool_defers_only_apify_schedule(tmp_path, monkeypatch):
    from src.services.source_schedule import SourceScheduleService

    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner, rss_source_id, rss_subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    apify_source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Private X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
        source_key="apify:x:profile:openai",
    )
    apify_subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=apify_source_id,
    )
    due = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    service = SourceScheduleService(store)
    for subscription in (rss_subscription, apify_subscription):
        service.update_subscription_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            subscription_id=subscription["id"],
            enabled=True,
            interval_minutes=30,
            now=due,
        )

    result = service.enqueue_due(now=due)

    assert result["enqueued"] == 1
    assert {
        item["subscription_id"]: item
        for item in result["outcomes"]
    }[apify_subscription["id"]] == {
        "subscription_id": apify_subscription["id"],
        "action": "skipped",
        "reason": "apify_key_pool_exhausted",
    }
    jobs = store.connect().execute(
        "SELECT source_id FROM fetch_jobs WHERE status = 'queued'"
    ).fetchall()
    assert [row["source_id"] for row in jobs] == [rss_source_id]
    apify_schedule = store.get_source_schedule(apify_subscription["id"])
    assert apify_schedule["last_skip_reason"] == "apify_key_pool_exhausted"
    assert apify_schedule["next_run_at"] == (
        due + timedelta(minutes=30)
    ).isoformat()


def test_worker_evaluates_due_source_schedule_before_claiming_regular_job(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
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

    result = run_worker_once(data_dir=str(tmp_path), worker_id="source-schedule-worker")
    active = store.connect().execute(
        """
        SELECT * FROM fetch_jobs
        WHERE subscription_id = ?
          AND job_type = 'source_fetch'
          AND status IN ('queued', 'running')
        """,
        (subscription["id"],),
    ).fetchall()

    assert result["id"] == regular["id"]
    assert len(active) == 1


def test_full_refresh_advances_only_participating_source_schedule(tmp_path, monkeypatch):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    second_source = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Second RSS",
        config={"name": "Second RSS", "url": "https://example.com/second.xml"},
        source_key="rss:https://example.com/second.xml",
    )
    second_subscription = store.create_subscription(
        user_id=owner["id"], source_id=second_source
    )
    service = SourceScheduleService(store)
    initial = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    for item in (subscription, second_subscription):
        service.update_subscription_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            subscription_id=item["id"],
            enabled=True,
            interval_minutes=30,
            now=initial,
        )
    finished = initial + timedelta(minutes=10)
    outcome = SourceOutcome(
        source_id=source_id,
        subscription_id=subscription["id"],
        source_key="rss:https://example.com/private.xml",
        analysis_mode="full",
        status="succeeded",
        fetched_count=1,
        issue=None,
    )
    refresh_job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )

    service.advance_after_full_refresh(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_outcomes=(outcome,),
        finished_at=finished.isoformat(),
        job_id=refresh_job["id"],
    )

    assert store.get_source_schedule(subscription["id"])["next_run_at"] == (
        finished + timedelta(minutes=30)
    ).isoformat()
    assert store.get_source_schedule(second_subscription["id"])["next_run_at"] == (
        initial.isoformat()
    )


def test_role_downgrade_disables_source_schedule_and_cancels_queued_auto_job(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
    )
    job, _created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "scheduled_source_fetch"},
        priority=-10,
    )

    store.update_user(owner["id"], role="viewer")

    schedule = store.get_source_schedule(subscription["id"])
    assert schedule["enabled"] is False
    assert schedule["next_run_at"] is None
    assert schedule["last_skip_reason"] == "user_read_only"
    cancelled = JobQueue(store).get_job(job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["error_code"] == "job_invalidated"
    assert cancelled["result_json"] == {
        "invalidation_reason": "user_read_only"
    }


def test_disabling_user_cancels_all_queued_manual_feed_jobs(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    source_job, source_created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    refresh_job, refresh_created = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "manual"},
    )
    assert source_created is True
    assert refresh_created is True

    store.update_user(owner["id"], enabled=False)

    assert JobQueue(store).get_job(source_job["id"])["status"] == "cancelled"
    assert JobQueue(store).get_job(refresh_job["id"])["status"] == "cancelled"


def test_disabling_subscription_disables_schedule_and_cancels_queued_auto_job(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
    )
    job, _created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "scheduled_source_fetch"},
        priority=-10,
    )

    store.update_subscription(subscription["id"], enabled=False)

    schedule = store.get_source_schedule(subscription["id"])
    assert schedule["enabled"] is False
    assert schedule["next_run_at"] is None
    assert schedule["last_skip_reason"] == "subscription_disabled"
    assert JobQueue(store).get_job(job["id"])["status"] == "cancelled"


def test_disabling_subscription_cancels_queued_manual_source_fetch(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    job, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    assert created is True

    store.update_subscription(subscription["id"], enabled=False)

    assert JobQueue(store).get_job(job["id"])["status"] == "cancelled"


def test_disabling_catalog_source_disables_schedules_and_cancels_queued_auto_jobs(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    service = SourceScheduleService(store)
    service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
    )
    job, _created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "scheduled_source_fetch"},
        priority=-10,
    )

    store.update_source(source_id, enabled=False)

    schedule = store.get_source_schedule(subscription["id"])
    assert schedule["enabled"] is False
    assert schedule["next_run_at"] is None
    assert schedule["last_skip_reason"] == "source_disabled"
    assert JobQueue(store).get_job(job["id"])["status"] == "cancelled"


def test_disabling_catalog_source_cancels_queued_manual_source_fetch(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    job, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    assert created is True

    store.update_source(source_id, enabled=False)

    assert JobQueue(store).get_job(job["id"])["status"] == "cancelled"


def test_due_source_schedule_reuses_active_fetch_without_charging_quota(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    due = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    active, _created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    service = SourceScheduleService(
        store,
        quota=QuotaService(store, max_fetch_jobs_per_day=0),
    )
    service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
        now=due,
    )

    result = service.enqueue_due(now=due)

    assert result["deduplicated"] == 1
    assert result["enqueued"] == 0
    assert result["outcomes"][0]["job_id"] == active["id"]
    assert store.get_source_schedule(subscription["id"])["next_run_at"] == (
        due + timedelta(minutes=30)
    ).isoformat()
    assert store.count_usage_since(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        event_types=["source_fetch"],
        since=due - timedelta(days=1),
    ) == 0


def test_due_source_schedule_defers_to_queued_full_refresh(tmp_path, monkeypatch):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    due = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    service = SourceScheduleService(store)
    service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
        now=due,
    )
    full = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )

    result = service.enqueue_due(now=due)

    assert result["deduplicated"] == 1
    assert result["enqueued"] == 0
    assert result["outcomes"][0]["job_id"] == full["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE job_type = 'source_fetch'"
    ).fetchone()[0] == 0


def test_full_refresh_cancels_participating_queued_scheduled_source_job(
    tmp_path, monkeypatch
):
    from src.services.source_schedule import SourceScheduleService

    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    service = SourceScheduleService(store)
    initial = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
        now=initial,
    )
    scheduled, _created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "scheduled_source_fetch"},
        priority=-10,
    )
    refresh = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )
    outcome = SourceOutcome(
        source_id=source_id,
        subscription_id=subscription["id"],
        source_key="rss:https://example.com/private.xml",
        analysis_mode="full",
        status="succeeded",
        fetched_count=1,
        issue=None,
    )

    service.advance_after_full_refresh(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_outcomes=(outcome,),
        finished_at=(initial + timedelta(minutes=5)).isoformat(),
        job_id=refresh["id"],
    )
    store.connect().commit()

    assert JobQueue(store).get_job(scheduled["id"])["status"] == "cancelled"


def test_actor_route_gate_applies_only_to_apify_x_profile(
    tmp_path,
    monkeypatch,
):
    from src.services.apify_actor_route import ApifyActorScheduleGate
    from src.services.source_schedule import SourceScheduleService

    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner, _rss_id, rss_subscription = _subscribed_owner(
        tmp_path,
        monkeypatch,
    )
    subscriptions = [rss_subscription]
    for platform, kind in (("x", "profile"), ("instagram", "profile")):
        source_id = store.create_source(
            workspace_id=workspace["id"],
            scope="private",
            owner_user_id=owner["id"],
            source_type="apify_social",
            display_name=f"{platform}-{kind}",
            config={
                "platform": platform,
                "kind": kind,
                "target": f"{platform}-target",
            },
        )
        subscriptions.append(
            store.create_subscription(
                user_id=owner["id"],
                source_id=source_id,
            )
        )
    due = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    service = SourceScheduleService(store)
    for subscription in subscriptions:
        service.update_subscription_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            subscription_id=subscription["id"],
            enabled=True,
            interval_minutes=30,
            now=due,
        )

    monkeypatch.setattr(
        "src.services.source_schedule.ApifyKeyPoolService.schedule_gate",
        lambda *_args, **_kwargs: {
            "blocked": False,
            "code": None,
            "retry_at": None,
        },
    )
    actor_gate_sources = []

    class ActorRoute:
        def schedule_gate(self, source_id=None):
            actor_gate_sources.append(source_id)
            return ApifyActorScheduleGate(
                allowed=False,
                status="exhausted",
                retry_at=due + timedelta(hours=1),
                error_code="apify_actor_route_exhausted",
            )

        def stage_pending_transitions(self):
            return None

    monkeypatch.setattr(
        "src.services.source_schedule.build_apify_actor_route",
        lambda *_args, **_kwargs: ActorRoute(),
    )

    result = service.enqueue_due(now=due)

    x_source_id = subscriptions[1]["source_id"]
    assert actor_gate_sources == [x_source_id]
    assert result["enqueued"] == 2
    assert result["skipped"] == 1
    assert [
        outcome["reason"]
        for outcome in result["outcomes"]
        if outcome["action"] == "skipped"
    ] == ["apify_actor_route_exhausted"]


def test_x_profile_schedule_releases_budget_incident_through_alert_bridge(
    tmp_path,
    monkeypatch,
):
    from src.services.apify_actor_alerts import ApifyActorAlertService
    from src.services.source_schedule import SourceScheduleService

    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner, _rss_id, _rss_subscription = _subscribed_owner(
        tmp_path,
        monkeypatch,
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="X profile",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "example",
        },
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    quota_ref = store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=None,
        name="Apify schedule quota",
        env_name="APIFY_SCHEDULE_QUOTA_TOKEN",
        kind="provider",
        provider="apify",
    )
    store.initialize()
    due = datetime.now(timezone.utc)
    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET status = 'active',
            remaining_included_credits_usd = 5,
            last_checked_at = ?,
            updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (due.isoformat(), due.isoformat(), workspace["id"], quota_ref["id"]),
    )
    store.connect().execute(
        """
        UPDATE apify_key_pool_state
        SET status = 'ready',
            active_secret_id = ?,
            updated_at = ?
        WHERE workspace_id = ?
        """,
        (quota_ref["id"], due.isoformat(), workspace["id"]),
    )
    store.connect().commit()
    service = SourceScheduleService(store)
    service.update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=30,
        now=due,
    )
    monkeypatch.setattr(
        "src.services.source_schedule.ApifyKeyPoolService.schedule_gate",
        lambda *_args, **_kwargs: {
            "blocked": False,
            "code": None,
            "retry_at": None,
        },
    )

    alerts = ApifyActorAlertService(store, data_dir=tmp_path)
    alerts.open_incident(
        workspace_id=workspace["id"],
        route_key="x/profile",
        incident_key="budget_blocked",
        event_type="budget_blocked",
        severity="critical",
        payload={"reason_code": "failed_spend_limit"},
    )
    store.connect().execute(
        """
        UPDATE apify_actor_routes
        SET status = 'budget_blocked',
            last_switch_reason = 'failed_spend_limit',
            budget_blocked_until = ?
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (
            (due - timedelta(minutes=1)).isoformat(),
            workspace["id"],
        ),
    )
    store.connect().commit()

    result = service.enqueue_due(now=due)

    assert result["enqueued"] == 1
    incident = store.connect().execute(
        """
        SELECT status, resolved_at
        FROM apify_actor_alert_incidents
        WHERE workspace_id = ? AND incident_key = 'budget_blocked'
        """,
        (workspace["id"],),
    ).fetchone()
    assert dict(incident)["status"] == "resolved"
    assert dict(incident)["resolved_at"] is not None


def test_retrying_terminal_source_fetch_reuses_another_active_subscription_job(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _subscribed_owner(
        tmp_path, monkeypatch
    )
    queue = JobQueue(store)
    terminal = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_fetch",
    )
    claimed = queue.claim_next_job(worker_id="terminal-source-worker")
    queue.complete_job(
        claimed["id"],
        status="failed",
        error_code="FetchFailed",
        error_message="failed",
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )
    active, _created = queue.create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "scheduled_source_fetch"},
    )

    retried = queue.retry_job(terminal["id"], user_id=owner["id"])

    assert retried["id"] == active["id"]
    assert queue.get_job(terminal["id"])["status"] == "failed"
