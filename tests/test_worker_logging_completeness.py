"""Real Worker boundaries with synthetic jobs and no upstream side effects."""

import json
import logging
from unittest.mock import Mock

import pytest

from src.logging_utils import configure_logging
from src.observability_context import current_observability_context
from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from src.services.worker_job_policy import WORKER_CLAIMABLE_JOB_TYPES
from src.storage.service_store import ServiceStore


@pytest.fixture
def worker_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-test-password")
    paths = configure_logging(tmp_path / "logs", service="worker")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    monkeypatch.setattr("src.services.worker_cycle.run_worker_housekeeping", lambda *_args, **_kw: None)
    monkeypatch.setattr("src.services.worker_housekeeping._reconcile_actorops_v2", lambda *_args, **_kw: None)
    yield store, paths
    store.close()
    for logger in (logging.getLogger(), logging.getLogger("inteliscope.operations")):
        for handler in tuple(logger.handlers):
            if getattr(handler, "_inteliscope_managed_handler", False):
                logger.removeHandler(handler)
                handler.close()


def _create_job(store, job_type, max_attempts=1):
    return JobQueue(store).create_job(
        workspace_id=store.get_default_workspace()["id"],
        user_id=store.get_user_by_username("owner")["id"], job_type=job_type,
        payload={"source_type": "rss"}, max_attempts=max_attempts,
    )


def _events(paths):
    return [json.loads(line) for line in paths["operations"].read_text().splitlines()]


@pytest.mark.parametrize("job_type", sorted(WORKER_CLAIMABLE_JOB_TYPES))
def test_each_claimable_job_records_committed_terminal_state(worker_env, monkeypatch, job_type):
    store, paths = worker_env
    job = _create_job(store, job_type)
    monkeypatch.setattr("src.services.worker._run_job", lambda *_a, **_kw: {"ok": True, "item_count": 0})
    result = run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False)
    assert result["status"] == "succeeded"
    events = [event for event in _events(paths) if event.get("job_id") == job["id"]]
    assert len([event for event in events if event["action"] == "claim"]) == 1
    final = [event for event in events if event["category"] == "job" and event["action"] == "finish"]
    assert len(final) == 1 and final[0]["outcome"] == "succeeded"
    assert final[0]["counts"]["attempts"] == 1
    assert JobQueue(store).get_job(job["id"])["status"] == "succeeded"
    assert current_observability_context().job_id is None


def test_retry_and_final_failure_have_one_primary_event_per_attempt(worker_env, monkeypatch):
    store, paths = worker_env
    job = _create_job(store, "source_test", max_attempts=2)

    def fail(*_args, **_kwargs):
        raise TimeoutError("private-upstream-response")

    monkeypatch.setattr("src.services.worker._run_job", fail)
    first = run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False, retry_base_seconds=0)
    second = run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False, retry_base_seconds=0)
    assert first["status"] == "queued" and second["status"] == "failed"
    events = [event for event in _events(paths) if event.get("job_id") == job["id"] and event["action"] == "finish"]
    assert [event["outcome"] for event in events] == ["retried", "failed"]
    assert [event["counts"]["attempts"] for event in events] == [1, 2]
    assert all(event["error_fingerprint"].startswith("err_") for event in events)
    assert "private-upstream-response" not in paths["runtime"].read_text()


def test_preclaim_failure_keeps_system_event_without_invented_identity(worker_env, monkeypatch):
    store, paths = worker_env

    def fail(*_args, **_kwargs):
        raise RuntimeError("private-startup-value")

    monkeypatch.setattr("src.services.worker.prepare_worker_cycle", fail)
    with pytest.raises(RuntimeError):
        run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False)
    events = [event for event in _events(paths) if event["action"] == "worker_boundary"]
    assert len(events) == 1 and events[0]["error_code"] == "RuntimeError"
    assert not {"workspace_id", "job_id", "source_id"} & events[0].keys()
    assert current_observability_context().job_id is None


def test_caught_notification_backlog_failure_has_safe_exception_and_event(worker_env):
    from src.services.worker_cycle import _dispatch_notification_backlog

    store, paths = worker_env
    notifications = Mock()
    notifications.dispatch_pending.side_effect = RuntimeError("private-notification-target")
    _dispatch_notification_backlog(store, notifications, Mock(), logger=logging.getLogger("backlog-test"))
    events = [event for event in _events(paths) if event["action"] == "backlog_dispatch"]
    assert len(events) == 1 and events[0]["error_code"] == "notification_backlog_failed"
    runtime = [json.loads(line) for line in paths["runtime"].read_text().splitlines()]
    assert any(record.get("error_fingerprint") == events[0]["error_fingerprint"] for record in runtime)
    assert "private-notification-target" not in paths["runtime"].read_text()


def test_lease_thread_failure_keeps_job_context_and_isolated_event(worker_env):
    from src.services.worker_lifecycle import LeaseHeartbeat

    store, paths = worker_env
    job = _create_job(store, "source_test")
    job.update(worker_id="worker_test", claim_token="claim_test")
    heartbeat = LeaseHeartbeat(data_dir=str(store.data_dir), job=job, lease_seconds=30, exception_code=lambda _: "RuntimeError")
    heartbeat.queue = Mock()
    heartbeat.queue.extend_job_lease.side_effect = RuntimeError("private-lease-error")
    heartbeat.stop_event = Mock()
    heartbeat.stop_event.wait.side_effect = [False, True]
    try:
        heartbeat._run()
    finally:
        heartbeat.store.close()
    events = [event for event in _events(paths) if event["action"] == "lease_extend"]
    assert len(events) == 1 and events[0]["job_id"] == job["id"]
    assert events[0]["error_code"] == "lease_extend_failed"
    assert current_observability_context().job_id is None
    assert "private-lease-error" not in paths["runtime"].read_text()


def test_operation_sink_failure_does_not_revert_committed_job(worker_env, monkeypatch):
    from src.logging_utils import logging_health_status

    store, paths = worker_env
    job = _create_job(store, "source_test")
    monkeypatch.setattr("src.services.worker._run_job", lambda *_a, **_kw: {"ok": True})
    handler = next(h for h in logging.getLogger("inteliscope.operations").handlers
                   if getattr(h, "channel", None) == "operations")

    def fail(*_args):
        raise OSError("private-disk-error")

    with monkeypatch.context() as patch:
        patch.setattr(handler.stream, "write", fail)
        result = run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False)
    assert result["status"] == "succeeded"
    assert JobQueue(store).get_job(job["id"])["status"] == "succeeded"
    assert logging_health_status()["channels"]["operations"]["status"] == "degraded"
    assert "private-disk-error" not in paths["runtime"].read_text()
