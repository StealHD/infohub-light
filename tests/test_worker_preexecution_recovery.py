import sqlite3

from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


def test_heartbeat_start_failure_requeues_without_running_or_spending_attempt(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-test-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        max_attempts=1,
    )
    ran = []

    def fail_before_execution(_self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("src.services.worker.LeaseHeartbeat.__enter__", fail_before_execution)
    monkeypatch.setattr("src.services.worker._run_job", lambda *_args, **_kwargs: ran.append(True))
    monkeypatch.setattr(
        "src.services.worker_cycle.MaintenanceService.run_if_due",
        lambda *_args, **_kwargs: {"ran": False},
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="preexecution-recovery-worker",
        enqueue_schedules=False,
    )

    assert result["id"] == job["id"]
    assert result["status"] == "queued"
    assert result["attempts"] == 0
    assert result["error_code"] == "OperationalError"
    assert ran == []
