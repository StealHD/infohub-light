from __future__ import annotations

from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from src.services.worker_cycle import (
    PreparedWorkerCycle,
    WorkerCyclePorts,
    prepare_worker_cycle,
)
from src.storage.service_store import ServiceStore


def _source_job(store: ServiceStore) -> str:
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Worker isolation",
        config={"url": "https://example.com/isolation.xml"},
    )
    return str(JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={},
    )["id"])


def test_claimed_source_job_runs_before_v2_housekeeping(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    job_id = _source_job(store)
    events: list[str] = []
    original_claim = JobQueue.claim_next_job

    def claim(self, *args, **kwargs):
        events.append("claim")
        return original_claim(self, *args, **kwargs)

    monkeypatch.setattr(JobQueue, "claim_next_job", claim)
    monkeypatch.setattr(
        "src.services.worker_housekeeping._reconcile_actorops_v2",
        lambda *_args, **_kwargs: events.append("actorops_v2"),
    )
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda _payload: events.append("job") or {"ok": True, "source_type": "rss"},
    )

    result = run_worker_once(
        data_dir=str(tmp_path), worker_id="isolation-worker", enqueue_schedules=False
    )

    assert result and result["id"] == job_id and result["status"] == "succeeded"
    assert events.index("claim") < events.index("actorops_v2")
    assert events.index("job") < events.index("actorops_v2")
    store.close()


def test_v2_housekeeping_failure_after_claim_cannot_fail_source_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    job_id = _source_job(store)
    monkeypatch.setattr(
        "src.services.worker_housekeeping._reconcile_actorops_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("v2 failed")),
    )
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda _payload: {"ok": True, "source_type": "rss"},
    )

    result = run_worker_once(
        data_dir=str(tmp_path), worker_id="failure-isolation-worker", enqueue_schedules=False
    )

    assert result and result["id"] == job_id and result["status"] == "succeeded"
    store.close()


def test_idle_cycle_claims_only_new_v2_control_work(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    events: list[str] = []

    def enqueue_v2(_store, queue, *, logger):
        events.append("discovery")
        queue.create_job(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            source_id=None,
            job_type="actorops_v2_discovery",
            payload={},
        )

    monkeypatch.setattr(
        "src.services.worker_housekeeping._run_v2_enqueuers",
        enqueue_v2,
    )

    ports = WorkerCyclePorts(
        run_feed_end_messages=lambda **_kwargs: None,
        emit_operation_event=lambda **_kwargs: True,
    )

    prepared = prepare_worker_cycle(
        store,
        data_dir=str(tmp_path),
        worker_id="idle-isolation-worker",
        lease_seconds=60,
        retry_base_seconds=1,
        enqueue_schedules=False,
        ports=ports,
        logger=__import__("logging").getLogger(__name__),
    )

    assert isinstance(prepared, PreparedWorkerCycle)
    assert prepared.job["job_type"] == "actorops_v2_discovery"
    assert events == ["discovery"]
    store.close()
