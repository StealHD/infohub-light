import json
import os
from datetime import datetime, timezone

import httpx

from src.models import ContentItem, SourceType
from src.services.feed_run import (
    FeedRunResult,
    RunIssue,
    SourceAvatarHint,
    SourceOutcome,
)
from src.services.job_eligibility import JobIneligibleError
from src.services.job_queue import JobQueue
from src.services.secret_store import SecretStore
from src.services.source_health import SourceHealthService
from src.services.source_schedule import SourceScheduleService
from src.services.user_feed_store import UserFeedStore
from src.services.worker import _is_retryable_exception, run_worker_once
from src.storage.service_store import ServiceStore


def test_worker_reconciles_actor_attempts_after_key_pool_before_claiming(
    tmp_path,
    monkeypatch,
):
    events = []
    workspace_id = "default"

    def reconcile_keys(_store, *, data_dir):
        events.append(("keys", data_dir))
        return [{"workspace_id": workspace_id, "ok": True, "status": "ready"}]

    class _Route:
        def reconcile_unfinished_attempts(self):
            events.append(("route", workspace_id))
            return {
                "cancelled": 1,
                "blocked_attempts": 0,
                "route_blocked": False,
            }

        def public_state(self):
            return {
                "quota": {
                    "estimated_days_remaining": None,
                }
            }

    monkeypatch.setattr(
        "src.services.worker.reconcile_all_apify_pools_sync",
        reconcile_keys,
    )
    monkeypatch.setattr(
        "src.services.worker.build_apify_actor_route",
        lambda _store, *, data_dir, workspace_id: _Route(),
    )
    monkeypatch.setattr(
        "src.services.worker.sync_apify_actor_quota_alert",
        lambda _store, *, data_dir, workspace_id, route_state: events.append(
            ("quota", workspace_id)
        ),
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="reconcile-worker",
        enqueue_schedules=False,
    )

    assert result is None
    assert events == [
        ("keys", str(tmp_path)),
        ("route", workspace_id),
        ("quota", workspace_id),
    ]


def test_worker_source_test_job_builds_payload_from_catalog_source(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_SHARED_ACQUISITION_ENABLED", "true")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Public Feed",
        config={"name": "Public Feed", "url": "https://example.com/feed.xml"},
    )
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={},
    )
    calls = []
    operation_events = []

    def fake_run_source_test(payload):
        calls.append(payload)
        return {"ok": True, "source_type": payload["source_type"]}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)
    monkeypatch.setattr(
        "src.services.worker.safe_emit_operation_event",
        lambda **event: operation_events.append(event) or True,
    )
    caplog.set_level("INFO", logger="src.services.worker")

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert calls == [
        {
            "source_type": "rss",
            "source_id": source_id,
            "source_display_name": "Public Feed",
            "catalog_source_type": "rss",
            "name": "Public Feed",
            "url": "https://example.com/feed.xml",
            "enabled": True,
            "keep_latest_item": False,
            "enforce_public_network": False,
        }
    ]
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        f"job_id={job['id']} job_type=source_test" in message
        and "status=succeeded" in message
        and "duration_ms=" in message
        for message in messages
    )
    assert all("feed.xml" not in message and "claim_token" not in message for message in messages)
    assert [
        (event["category"], event["action"], event["outcome"])
        for event in operation_events
    ] == [
        ("job", "claim", "running"),
        ("job", "finish", "succeeded"),
        ("acquisition", "test", "succeeded"),
    ]
    assert all(
        event["workspace_id"] == workspace["id"]
        and event["subject_user_id"] == owner["id"]
        and event["job_id"] == job["id"]
        and event["source_id"] == source_id
        for event in operation_events
    )
    attempt_usage = store.connect().execute(
        """
        SELECT provider, quantity
        FROM usage_events
        WHERE user_id = ? AND event_type = 'fetch_attempt'
        """,
        (owner["id"],),
    ).fetchall()
    assert [tuple(row) for row in attempt_usage] == [("rss", 1)]


def test_worker_hot_loads_secret_file_before_running_job(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    SecretStore(tmp_path).set("APIFY_TOKEN", "worker-private-value")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"], scope="private", owner_user_id=owner["id"],
        source_type="apify_social", display_name="Private X",
        config={"platform": "x", "kind": "profile", "target": "example", "fetch_limit": 20},
        source_key="apify_social:x:profile:example", secret_env="APIFY_TOKEN",
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"], user_id=owner["id"], source_id=source_id,
        job_type="source_test", payload={},
    )

    def fake_run_source_test(payload):
        assert os.environ["APIFY_TOKEN"] == "worker-private-value"
        return {"ok": True, "source_type": payload["source_type"]}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert result["status"] == "succeeded"


def test_worker_ignores_member_job_rss_overrides_and_enforces_public_network(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=member["id"],
        source_type="rss",
        display_name="Member Feed",
        config={"name": "Member Feed", "url": "https://example.com/member.xml"},
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        job_type="source_test",
        payload={
            "source_type": "rss",
            "url": "http://127.0.0.1:8080/override",
            "reason": "test",
        },
    )
    calls = []

    def fake_run_source_test(payload):
        calls.append(payload)
        return {"ok": True, "source_type": payload["source_type"]}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert result["status"] == "succeeded"
    assert calls == [{
        "source_type": "rss",
        "source_id": source_id,
        "source_display_name": "Member Feed",
        "catalog_source_type": "rss",
        "name": "Member Feed",
        "url": "https://example.com/member.xml",
        "enabled": True,
        "keep_latest_item": False,
        "enforce_public_network": True,
        "reason": "test",
    }]


def test_worker_source_test_payload_uses_registry_and_secret_env_name(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("APIFY_TOKEN", "real-token-value")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="OpenAI on X",
        config={"platform": "x", "kind": "profile", "target": "openai"},
        secret_env="APIFY_TOKEN",
        source_key="apify_social:x:profile:openai",
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={"reason": "test"},
    )
    calls = []

    def fake_run_source_test(payload):
        calls.append(payload)
        return {"ok": True, "source_type": payload["source_type"]}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert result["status"] == "succeeded"
    assert calls[0]["source_type"] == "apify_social"
    assert calls[0]["platform"] == "x"
    assert calls[0]["kind"] == "profile"
    assert calls[0]["target"] == "openai"
    assert calls[0]["token_env"] == "APIFY_TOKEN"
    assert "real-token-value" not in repr(calls[0])


def test_worker_source_test_uses_workspace_apify_pool_without_source_key_reference(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    secret = store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=None,
        name="Workspace Apify",
        env_name="APIFY_WORKSPACE_TOKEN",
        kind="provider",
        provider="apify",
    )
    SecretStore(tmp_path).set("APIFY_WORKSPACE_TOKEN", "private-workspace-token")
    store.initialize()
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="OpenAI on X",
        config={"platform": "x", "kind": "profile", "target": "openai"},
        secret_env="LEGACY_SOURCE_TOKEN",
        source_key="apify_social:x:profile:openai",
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={"reason": "test"},
    )
    calls = []

    def fake_run_source_test(
        payload,
        *,
        apify_coordinator,
        apify_actor_route,
        route_job_id,
        forced_candidate_id,
        forced_route_generation,
        paid_canary,
    ):
        calls.append(
            (
                payload,
                apify_coordinator,
                apify_actor_route,
                route_job_id,
                forced_candidate_id,
                forced_route_generation,
                paid_canary,
            )
        )
        return {"ok": True, "source_type": payload["source_type"]}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="pool-worker")

    assert result["status"] == "succeeded"
    assert len(calls) == 1
    (
        payload,
        coordinator,
        actor_route,
        route_job_id,
        forced_candidate_id,
        forced_route_generation,
        paid_canary,
    ) = calls[0]
    assert coordinator.workspace_id == workspace["id"]
    assert actor_route.workspace_id == workspace["id"]
    assert route_job_id == result["id"]
    assert forced_candidate_id is None
    assert forced_route_generation is None
    assert paid_canary is False
    assert coordinator.public_state(workspace["id"])["active_secret_id"] == secret["id"]
    assert "token_env" not in payload
    assert "secret_env" not in payload
    assert "private-workspace-token" not in repr(payload)


def test_worker_paid_canary_fails_closed_when_actor_routing_is_disabled(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "false")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="OpenAI on X",
        config={"platform": "x", "kind": "profile", "target": "openai"},
        source_key="apify_social:x:profile:openai-canary-disabled",
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={
            "reason": "apify_actor_canary",
            "apify_actor_candidate_id": "candidate-id",
            "apify_actor_route_generation": 1,
        },
        max_attempts=1,
    )
    calls = []

    def fake_run_source_test(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="canary-disabled-worker",
        retry_base_seconds=0,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "failed"
    assert result["error_code"] == "apify_actor_routing_disabled"
    assert calls == []


def test_worker_rejects_paid_canary_without_dedicated_job_limits(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="OpenAI on X",
        config={"platform": "x", "kind": "profile", "target": "openai"},
        source_key="apify_social:x:profile:openai-canary-bypass",
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={
            "reason": "apify_actor_canary",
            "apify_actor_candidate_id": "candidate-id",
            "apify_actor_route_generation": 1,
        },
        priority=100,
        max_attempts=3,
    )
    calls = []

    def fake_run_source_test(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="canary-bypass-worker",
        retry_base_seconds=0,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "failed"
    assert result["error_code"] == "apify_actor_canary_unavailable"
    assert calls == []


def test_worker_does_not_accept_canary_metadata_from_source_config(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Injected X source",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "openai",
            "reason": "apify_actor_canary",
            "apify_actor_candidate_id": "injected-candidate",
            "apify_actor_route_generation": 1,
        },
        source_key="apify_social:x:profile:injected-canary-config",
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={},
        priority=100,
        max_attempts=1,
    )
    calls = []

    def fake_run_source_test(payload, **kwargs):
        calls.append((payload, kwargs))
        return {"ok": True}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="canary-source-injection-worker",
        retry_base_seconds=0,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert len(calls) == 1
    payload, kwargs = calls[0]
    assert "reason" not in payload
    assert "apify_actor_candidate_id" not in payload
    assert "apify_actor_route_generation" not in payload
    assert kwargs["paid_canary"] is False
    assert kwargs["forced_candidate_id"] is None
    assert kwargs["forced_route_generation"] is None


def test_worker_source_fetch_with_catalog_source_uses_catalog_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Fetch RSS",
        config={"name": "Fetch RSS", "url": "https://github.blog/feed/"},
        source_key="rss:https://github.blog/feed/",
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    queue = JobQueue(store)
    job, created = queue.create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"hours": 12},
    )
    assert created is True
    calls = []

    def fake_run_catalog_source_fetch(catalog_job, *, data_dir, store, commit):
        assert commit is False
        calls.append(
            {
                "job_id": catalog_job["id"],
                "source_id": catalog_job["source_id"],
                "hours": catalog_job["payload_json"]["hours"],
                "data_dir": data_dir,
            }
        )
        return {
            "ok": True,
            "job_type": "source_fetch",
            "source_id": catalog_job["source_id"],
            "source_type": "rss",
            "source_key": "rss:https://github.blog/feed/",
            "snapshot_id": "snap_worker",
            "item_count": 2,
        }

    monkeypatch.setattr(
        "src.services.catalog_source_runner.run_catalog_source_fetch",
        fake_run_catalog_source_fetch,
    )

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert calls == [
        {
            "job_id": job["id"],
            "source_id": source_id,
            "hours": 12,
            "data_dir": str(tmp_path),
        }
    ]
    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert result["result_json"]["snapshot_id"] == "snap_worker"
    assert result["result_json"]["source_key"] == "rss:https://github.blog/feed/"


def test_worker_invalidates_claimed_source_fetch_before_network_when_subscription_is_disabled(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Disabled Subscription Feed",
        config={"url": "https://example.com/disabled.xml"},
        source_key="rss:https://example.com/disabled.xml",
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    job, created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )
    assert created is True
    store.connect().execute(
        "UPDATE user_subscriptions SET enabled = 0 WHERE id = ?",
        (subscription["id"],),
    )
    store.connect().commit()
    calls = []

    def unexpected_runner(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("invalidated job reached the source runner")

    monkeypatch.setattr(
        "src.services.catalog_source_runner.run_catalog_source_fetch",
        unexpected_runner,
    )

    result = run_worker_once(data_dir=str(tmp_path), worker_id="eligibility-worker")

    assert calls == []
    assert result["id"] == job["id"]
    assert result["status"] == "cancelled"
    assert result["error_code"] == "job_invalidated"
    assert result["result_json"] == {
        "invalidation_reason": "subscription_disabled"
    }


def test_worker_cancels_stale_scheduled_global_refresh_when_no_source_follows_global(
    tmp_path, monkeypatch
):
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
        display_name="Custom-only Feed",
        config={"url": "https://example.com/custom-only.xml"},
        source_key="rss:https://example.com/custom-only.xml",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=60,
        now=datetime.now(timezone.utc).replace(year=2036),
    )
    job, created = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "scheduled_service_refresh"},
        priority=-10,
    )
    assert created is True

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="no-global-worker",
    )

    assert result["id"] == job["id"]
    assert result["status"] == "cancelled"
    assert result["error_code"] == "job_invalidated"
    assert result["result_json"] == {
        "invalidation_reason": "no_global_subscriptions"
    }


def test_worker_discards_source_fetch_result_invalidated_during_network(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Race Feed",
        config={"url": "https://example.com/race.xml"},
        source_key="rss:https://example.com/race.xml",
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    job, _created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )

    def invalidating_runner(*_args, **_kwargs):
        runner_store = ServiceStore(tmp_path)
        runner_store.initialize()
        runner_store.connect().execute(
            "UPDATE user_subscriptions SET enabled = 0 WHERE id = ?",
            (subscription["id"],),
        )
        runner_store.connect().commit()
        runner_store.close()
        return {
            "ok": True,
            "snapshot_id": "must-not-be-published",
            "item_count": 1,
        }

    monkeypatch.setattr(
        "src.services.catalog_source_runner.run_catalog_source_fetch",
        invalidating_runner,
    )

    result = run_worker_once(data_dir=str(tmp_path), worker_id="race-worker")

    assert result["id"] == job["id"]
    assert result["status"] == "cancelled"
    assert result["result_json"] == {
        "invalidation_reason": "subscription_disabled"
    }


def test_worker_cancels_attempt_rejected_after_claim_as_job_invalidated(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Rejected Attempt Feed",
        config={"url": "https://example.com/rejected-attempt.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    job, _created = JobQueue(store).create_source_fetch_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"reason": "manual"},
    )

    def rejected_runner(*_args, **_kwargs):
        concurrent_store = ServiceStore(tmp_path)
        concurrent_store.initialize()
        concurrent_store.connect().execute(
            "UPDATE user_subscriptions SET enabled = 0 WHERE id = ?",
            (subscription["id"],),
        )
        concurrent_store.connect().commit()
        concurrent_store.close()
        raise JobIneligibleError("subscription_disabled")

    monkeypatch.setattr(
        "src.services.catalog_source_runner.run_catalog_source_fetch",
        rejected_runner,
    )

    result = run_worker_once(data_dir=str(tmp_path), worker_id="rejected-worker")

    assert result["id"] == job["id"]
    assert result["status"] == "cancelled"
    assert result["error_code"] == "job_invalidated"
    assert result["result_json"] == {
        "invalidation_reason": "subscription_disabled"
    }


def test_worker_retries_failed_job_before_final_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        max_attempts=2,
    )

    class TemporarySourceError(RuntimeError):
        retryable = True
        code = "apify_key_drain_pending"

    def failing_run_source_test(_payload):
        raise TemporarySourceError("temporary source failure")

    monkeypatch.setattr("src.services.worker.run_source_test", failing_run_source_test)

    first = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1", retry_base_seconds=0)
    second = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1", retry_base_seconds=0)

    assert first["id"] == job["id"]
    assert first["status"] == "queued"
    assert first["attempts"] == 1
    assert second["status"] == "failed"
    assert second["attempts"] == 2
    assert second["error_code"] == "apify_key_drain_pending"


def test_worker_does_not_retry_deterministic_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        max_attempts=3,
    )

    def invalid_source_test(_payload):
        raise ValueError("deterministic invalid source configuration")

    monkeypatch.setattr("src.services.worker.run_source_test", invalid_source_test)

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="deterministic-worker",
        retry_base_seconds=0,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "failed"
    assert result["attempts"] == 1
    assert result["error_code"] == "ValueError"


def test_worker_retry_classification_allows_only_transient_http_failures():
    request = httpx.Request("GET", "https://example.com/feed")
    server_error = httpx.HTTPStatusError(
        "server error",
        request=request,
        response=httpx.Response(503, request=request),
    )
    client_error = httpx.HTTPStatusError(
        "client error",
        request=request,
        response=httpx.Response(400, request=request),
    )

    assert _is_retryable_exception(httpx.ConnectError("offline", request=request)) is True
    assert _is_retryable_exception(server_error) is True
    assert _is_retryable_exception(client_error) is False


def test_worker_user_feed_refresh_saves_user_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_SHARED_ACQUISITION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {
                    "enabled": False,
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "api_key_env": "OPENAI_API_KEY",
                },
                "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
                "filtering": {"time_window_hours": 24},
            }
        ),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )

    acquisition_coordinators = []
    apify_coordinators = []

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        def set_service_acquisition_coordinator(self, coordinator):
            acquisition_coordinators.append(coordinator)

        def set_service_apify_coordinator(self, coordinator):
            apify_coordinators.append(coordinator)

        async def execute(self, **_kwargs):
            assert _kwargs["force_hours"] is None
            item = ContentItem(
                id="rss:item:worker",
                source_type=SourceType.RSS,
                title="Worker Item",
                url="https://example.com/worker",
                published_at=datetime.now(timezone.utc),
                metadata={"source_id": "src_worker", "channel": "AI", "topics": ["Codex"]},
            )
            return FeedRunResult(
                run_id="run_worker",
                status="succeeded",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                items=(item,),
            )

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1")
    latest = UserFeedStore(store).latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert result["result_json"]["snapshot_id"] == latest["id"]
    assert result["result_json"]["item_count"] == 1
    assert result["result_json"]["new_item_count"] == 1
    assert result["result_json"]["run_id"] == "run_worker"
    assert result["result_json"]["run_status"] == "succeeded"
    assert result["result_json"]["source_outcomes"] == []
    assert result["result_json"]["issues"] == []
    assert len(acquisition_coordinators) == 1
    assert acquisition_coordinators[0].user_id == owner["id"]
    assert len(apify_coordinators) == 1
    assert apify_coordinators[0].workspace_id == workspace["id"]
    assert latest["payload"]["items"][0]["id"] == "rss:item:worker"
    assert latest["payload"]["schema_version"] == 2
    assert latest["payload"]["today_items"] == latest["payload"]["items"]
    assert not (tmp_path / "site" / "radar-data.json").exists()


def test_scheduled_global_refresh_excludes_custom_sources_but_preserves_their_feed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {
                    "enabled": False,
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "api_key_env": "OPENAI_API_KEY",
                },
                "sources": {
                    "rss": [],
                    "github": [],
                    "hackernews": {"enabled": False},
                },
                "filtering": {"time_window_hours": 24},
            }
        ),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    sources: dict[str, tuple[str, dict]] = {}
    for mode in ("global", "custom"):
        source_id = store.create_source(
            workspace_id=workspace["id"],
            scope="private",
            owner_user_id=owner["id"],
            source_type="rss",
            display_name=f"{mode.title()} Feed",
            config={
                "name": f"{mode.title()} Feed",
                "url": f"https://example.com/{mode}.xml",
            },
            source_key=f"rss:https://example.com/{mode}.xml",
        )
        sources[mode] = (
            source_id,
            store.create_subscription(user_id=owner["id"], source_id=source_id),
        )
    custom_source_id, custom_subscription = sources["custom"]
    custom_schedule = SourceScheduleService(
        store
    ).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=custom_subscription["id"],
        enabled=True,
        interval_minutes=60,
        now=datetime(2036, 7, 28, 10, 0, tzinfo=timezone.utc),
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": now_iso,
            "items": [
                {
                    "id": "rss:item:custom-retained",
                    "source_type": "rss",
                    "source_id": custom_source_id,
                    "subscription_id": custom_subscription["id"],
                    "title": "Retained custom item",
                    "url": "https://example.com/custom-retained",
                    "published_at": now_iso,
                }
            ],
        },
    )
    queue = JobQueue(store)
    scheduled, created = queue.create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "scheduled_service_refresh"},
        priority=-10,
    )
    assert created is True
    configured_runs: list[list[str]] = []

    class FakeOrchestrator:
        def __init__(self, config, _storage):
            self.entries = list(config.sources.rss)
            self.run_number = len(configured_runs) + 1
            configured_runs.append(
                [str(entry.source_id) for entry in self.entries]
            )

        async def execute(self, **_kwargs):
            finished_at = datetime.now(timezone.utc).isoformat()
            items = tuple(
                ContentItem(
                    id=f"rss:item:{entry.source_id}:{self.run_number}",
                    source_type=SourceType.RSS,
                    title=f"Fetched {entry.source_id}",
                    url=f"https://example.com/items/{entry.source_id}",
                    published_at=datetime.now(timezone.utc),
                    metadata={
                        "source_id": entry.source_id,
                        "subscription_id": entry.subscription_id,
                    },
                )
                for entry in self.entries
            )
            outcomes = tuple(
                SourceOutcome(
                    str(entry.source_id),
                    str(entry.subscription_id),
                    str(entry.source_key),
                    "full",
                    "succeeded",
                    1,
                )
                for entry in self.entries
            )
            return FeedRunResult(
                run_id=f"run_{self.run_number}",
                status="succeeded",
                started_at=finished_at,
                finished_at=finished_at,
                items=items,
                source_outcomes=outcomes,
            )

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)

    scheduled_result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="scheduled-global-worker",
    )
    scheduled_snapshot = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert scheduled_result["id"] == scheduled["id"]
    assert configured_runs == [[sources["global"][0]]]
    assert {
        item["id"] for item in scheduled_snapshot["payload"]["items"]
    } == {
        "rss:item:custom-retained",
        f"rss:item:{sources['global'][0]}:1",
    }
    assert SourceHealthService(store).get_health(
        custom_subscription["id"]
    ) is None
    assert SourceHealthService(store).get_health(
        sources["global"][1]["id"]
    ) is not None
    assert store.get_source_schedule(custom_subscription["id"])[
        "next_run_at"
    ] == custom_schedule["next_run_at"]

    manual, created = queue.create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "manual"},
    )
    assert created is True
    manual_result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="manual-full-worker",
    )

    assert manual_result["id"] == manual["id"]
    assert set(configured_runs[1]) == {sources["global"][0], custom_source_id}
    assert store.get_source_schedule(custom_subscription["id"])[
        "last_job_id"
    ] == manual["id"]


def test_full_refresh_discards_source_disabled_during_run_before_feed_and_health(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {
                    "enabled": False,
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "api_key_env": "OPENAI_API_KEY",
                },
                "sources": {
                    "rss": [],
                    "github": [],
                    "hackernews": {"enabled": False},
                },
                "filtering": {"time_window_hours": 24},
            }
        ),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Disable During Full Refresh",
        config={"url": "https://example.com/disable-during-full.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            concurrent_store = ServiceStore(tmp_path)
            concurrent_store.initialize()
            concurrent_store.update_source(source_id, enabled=False)
            concurrent_store.close()
            item = ContentItem(
                id="rss:item:invalidated-full",
                source_type=SourceType.RSS,
                title="Must Be Discarded",
                url="https://example.com/invalidated-full",
                published_at=datetime.now(timezone.utc),
                metadata={
                    "source_id": source_id,
                    "subscription_id": subscription["id"],
                },
            )
            return FeedRunResult(
                run_id="run_invalidated_full",
                status="succeeded",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                items=(item,),
                source_outcomes=(
                    SourceOutcome(
                        source_id,
                        subscription["id"],
                        "rss:disable-during-full",
                        "full",
                        "succeeded",
                        1,
                    ),
                ),
            )

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="full-race-worker")
    latest = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert latest["payload"]["items"] == []
    assert SourceHealthService(store).get_health(subscription["id"]) is None


def test_worker_partial_feed_run_persists_snapshot_and_terminal_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {"enabled": False, "provider": "openai", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"},
                "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
                "filtering": {"time_window_hours": 24},
            }
        ),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"], user_id=owner["id"], job_type="user_feed_refresh", payload={}
    )
    issue = RunIssue(
        "fetch",
        "TimeoutError",
        "failed https://alice:pass@example.com/feed?token=url-secret Bearer bearer-secret",
        True,
    )

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            item = ContentItem(
                id="rss:item:partial",
                source_type=SourceType.RSS,
                title="Partial",
                url="https://example.com/partial",
                published_at=datetime.now(timezone.utc),
                metadata={"source_id": "src_ok", "subscription_id": "sub_ok"},
            )
            return FeedRunResult(
                run_id="run_partial",
                status="partial",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                items=(item,),
                source_outcomes=(
                    SourceOutcome("src_ok", None, "rss:ok", "full", "succeeded", 1),
                    SourceOutcome(
                        "src_bad",
                        None,
                        "rss:https://alice:key@example.com/feed?token=key-secret",
                        "full",
                        "failed",
                        0,
                        issue,
                    ),
                ),
                issues=(issue,),
            )

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="worker-partial")
    latest = UserFeedStore(store).latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])

    assert result["id"] == job["id"]
    assert result["status"] == "partial"
    assert result["result_json"]["run_id"] == "run_partial"
    assert result["result_json"]["run_status"] == "partial"
    assert result["result_json"]["item_count"] == 1
    assert result["result_json"]["new_item_count"] == 1
    assert len(result["result_json"]["source_outcomes"]) == 2
    assert result["result_json"]["source_outcomes"][1]["issue"] == result["result_json"]["issues"][0]
    serialized = str(result["result_json"])
    for secret in ("alice", "pass", "url-secret", "bearer-secret", "key-secret"):
        assert secret not in serialized
    assert latest["payload"]["run_status"] == "partial"


def test_worker_all_sources_failed_does_not_create_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {"enabled": False, "provider": "openai", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"},
                "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
                "filtering": {"time_window_hours": 24},
            }
        ),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )
    issue = RunIssue(
        "fetch",
        "UnsafeNetworkTarget",
        "blocked https://alice:pass@example.com/feed?token=failed-secret stack=Traceback-private",
        False,
    )
    avatar_runs = []

    class AvatarService:
        def __init__(self, _store, *, data_dir):
            assert data_dir == str(tmp_path)

        def refresh_run_result(self, *, workspace_id, result):
            avatar_runs.append((workspace_id, result))
            return []

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            return FeedRunResult(
                run_id="run_failed",
                status="failed",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                source_outcomes=(
                    SourceOutcome(
                        "src_bad",
                        None,
                        "rss:bad",
                        "full",
                        "failed",
                        0,
                        issue,
                        avatar_hints=(
                            SourceAvatarHint(
                                source_id="src_bad",
                                remote_url="https://example.com/avatar.png",
                                origin="rss_feed_icon",
                            ),
                        ),
                    ),
                ),
                issues=(issue,),
            )

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)
    monkeypatch.setattr("src.services.worker.SourceAvatarService", AvatarService)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="worker-failed")

    assert result["status"] == "failed"
    assert result["error_code"] == "FeedRunFailed"
    assert result["result_json"]["run_id"] == "run_failed"
    assert result["result_json"]["run_status"] == "failed"
    assert result["result_json"]["item_count"] == 0
    assert "new_item_count" not in result["result_json"]
    assert len(result["result_json"]["source_outcomes"]) == 1
    assert len(result["result_json"]["issues"]) == 1
    assert len(avatar_runs) == 1
    assert avatar_runs[0][0] == workspace["id"]
    assert avatar_runs[0][1].items == ()
    assert avatar_runs[0][1].source_outcomes[0].avatar_hints[0].origin == (
        "rss_feed_icon"
    )
    serialized = str(
        {
            "result": result["result_json"],
            "error_message": result["error_message"],
        }
    )
    for secret in ("alice", "pass", "failed-secret", "Traceback-private"):
        assert secret not in serialized
    assert UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    ) is None


def test_worker_defers_retention_until_feed_storage_v3_is_migrated(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_unmigrated_retention",
        payload={"schema_version": 2, "items": [{"id": "legacy-item"}]},
    )
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 3")
    store.connect().commit()
    calls = 0

    def unexpected_maintenance(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("retention ran before backup-backed v3 migration")

    monkeypatch.setattr(
        "src.services.worker.MaintenanceService.run_if_due",
        unexpected_maintenance,
    )

    assert run_worker_once(
        data_dir=str(tmp_path),
        worker_id="unmigrated-maintenance-worker",
        enqueue_schedules=False,
    ) is None
    assert calls == 0


def test_worker_runs_content_repair_without_schedules_or_feed_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"], scope="public", owner_user_id=owner["id"],
        source_type="rss", display_name="Repair Worker",
        config={"url": "https://example.com/repair.xml"},
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"], user_id=owner["id"], source_id=source_id,
        job_type="content_repair", payload={"maintenance_only": True},
    )

    def fake_repair(claimed_job, *, data_dir, store):
        assert claimed_job["id"] == job["id"]
        assert data_dir == str(tmp_path)
        return {
            "ok": True, "job_type": "content_repair", "snapshot_created": False,
            "analysis_calls": 0, "matched_items": 1,
        }

    monkeypatch.setattr("src.services.content_repair.repair_existing_content", fake_repair)
    monkeypatch.setattr("src.services.worker.FeedScheduleService.enqueue_due", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("schedule evaluated")))
    monkeypatch.setattr("src.services.worker.SourceScheduleService.enqueue_due", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("schedule evaluated")))

    result = run_worker_once(
        data_dir=str(tmp_path), worker_id="content-repair-worker", enqueue_schedules=False,
    )

    assert result["status"] == "succeeded"
    assert result["result_json"]["snapshot_created"] is False
    assert result["result_json"]["analysis_calls"] == 0
    assert store.connect().execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0] == 0
