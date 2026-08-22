from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from src.services.worker_cycle import PreparedWorkerCycle, prepare_worker_cycle
from src.services.worker_housekeeping import WorkerCyclePorts
from src.services.worker_job_policy import (
    RETIRED_ACTOROPS_V1_JOB_TYPES,
    WORKER_CLAIMABLE_JOB_TYPES,
)
from src.services.worker_retired_actorops_jobs import retire_queued_actorops_v1_jobs
from src.storage.service_store import ServiceStore
from tests.test_actorops_v1_retirement_boundary import (
    install_actorops_v1_deny_authorizer,
)


def _owner(store: ServiceStore) -> dict[str, object]:
    owner = store.get_user_by_username("owner")
    if owner is not None:
        return owner
    return store.create_user(
        workspace_id="default",
        username="owner",
        password="safe-password",
        role="owner",
    )


def _job(
    queue: JobQueue,
    owner: dict[str, object],
    *,
    job_type: str,
    priority: int = 0,
) -> dict[str, object]:
    return queue.create_job(
        workspace_id=str(owner["workspace_id"]),
        user_id=str(owner["id"]),
        job_type=job_type,
        payload={},
        priority=priority,
    )


def test_retirement_cancels_only_never_started_v1_jobs(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    queue = JobQueue(store)
    owner = _owner(store)
    queued = _job(
        queue,
        owner,
        job_type="apify_actor_discovery",
    )
    running = _job(
        queue,
        owner,
        job_type="apify_actor_validation",
    )
    store.connect().execute(
        """UPDATE fetch_jobs
           SET status='running', attempts=1, started_at=?, locked_until=?
           WHERE id=?""",
        (
            datetime.now(timezone.utc).isoformat(),
            (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            running["id"],
        ),
    )
    store.connect().commit()

    retired = retire_queued_actorops_v1_jobs(store)

    assert retired == [str(queued["id"])]
    cancelled = queue.get_job(str(queued["id"]))
    isolated = queue.get_job(str(running["id"]))
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert cancelled["error_code"] == "actorops_v1_retired"
    assert cancelled["result_json"] == {"invalidation_reason": "actorops_v1_retired"}
    assert isolated is not None
    assert isolated["status"] == "running"
    assert isolated["attempts"] == 1
    store.close()


def test_claim_and_stale_recovery_never_touch_retired_actorops_jobs(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    queue = JobQueue(store)
    owner = _owner(store)
    retired = _job(
        queue,
        owner,
        job_type="apify_actor_canary_batch",
        priority=100,
    )
    normal = _job(queue, owner, job_type="source_test")

    claim = queue.claim_next_job(
        worker_id="single-track-worker",
        allowed_job_types=WORKER_CLAIMABLE_JOB_TYPES,
    )

    assert claim is not None
    assert claim["id"] == normal["id"]
    assert queue.get_job(str(retired["id"]))["status"] == "queued"
    store.connect().execute(
        """UPDATE fetch_jobs
           SET status='running', attempts=1, started_at=?, locked_until=?
           WHERE id=?""",
        (
            datetime.now(timezone.utc).isoformat(),
            (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            retired["id"],
        ),
    )
    store.connect().commit()

    recovered = queue.recover_stale_running_jobs(
        allowed_job_types=WORKER_CLAIMABLE_JOB_TYPES,
    )

    assert recovered == []
    assert queue.get_job(str(retired["id"]))["status"] == "running"
    assert set(RETIRED_ACTOROPS_V1_JOB_TYPES) == {
        "apify_actor_discovery",
        "apify_actor_validation",
        "apify_actor_canary_batch",
        "apify_actor_freshness_check",
    }
    store.close()


def test_legacy_actorops_migration_cannot_block_an_rss_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = _owner(store)
    source_id = store.create_source(
        workspace_id=str(owner["workspace_id"]),
        scope="public",
        owner_user_id=str(owner["id"]),
        source_type="rss",
        display_name="Worker migration isolation",
        config={"url": "https://example.com/feed.xml"},
    )
    job = JobQueue(store).create_job(
        workspace_id=str(owner["workspace_id"]),
        user_id=str(owner["id"]),
        source_id=source_id,
        job_type="source_test",
        payload={},
    )
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version = 17"
    )
    store.connect().commit()
    store.close()
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda _payload: {"ok": True, "source_type": "rss"},
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="ordinary-source-worker",
        enqueue_schedules=False,
    )

    assert result is not None
    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"


def test_worker_claim_path_runs_with_historical_v1_tables_denied(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = _owner(store)
    job = _job(JobQueue(store), owner, job_type="source_test")
    uninstall = install_actorops_v1_deny_authorizer(store.connect())
    try:
        prepared = prepare_worker_cycle(
            store,
            data_dir=str(tmp_path),
            worker_id="v1-deny-worker",
            lease_seconds=60,
            retry_base_seconds=1,
            enqueue_schedules=False,
            ports=WorkerCyclePorts(
                run_feed_end_messages=lambda **_kwargs: None,
                emit_operation_event=lambda **_kwargs: True,
            ),
            logger=__import__("logging").getLogger(__name__),
        )
    finally:
        uninstall()

    assert isinstance(prepared, PreparedWorkerCycle)
    assert prepared.job["id"] == job["id"]
    store.close()


def test_rss_worker_executes_with_historical_v1_tables_denied(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = _owner(store)
    job = _job(JobQueue(store), owner, job_type="source_test")
    store.close()
    original_initialize = ServiceStore.initialize

    def initialize_with_v1_denied(self: ServiceStore) -> None:
        original_initialize(self)
        install_actorops_v1_deny_authorizer(self.connect())

    monkeypatch.setattr(ServiceStore, "initialize", initialize_with_v1_denied)
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda _payload: {"ok": True, "source_type": "rss"},
    )

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="v1-deny-rss-worker",
        enqueue_schedules=False,
    )

    assert result is not None
    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"


def test_missing_v2_schema_only_fails_the_v2_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-password")
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = _owner(store)
    v2_job = _job(
        JobQueue(store),
        owner,
        job_type="actorops_v2_metadata_refresh",
        priority=100,
    )
    normal_job = _job(JobQueue(store), owner, job_type="source_test")
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 26")
    store.connect().commit()
    store.close()
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda _payload: {"ok": True, "source_type": "rss"},
    )

    first = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="v2-schema-worker",
        enqueue_schedules=False,
    )
    second = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="v2-schema-worker",
        enqueue_schedules=False,
    )

    assert first is not None
    assert first["id"] == v2_job["id"]
    assert first["status"] == "failed"
    assert second is not None
    assert second["id"] == normal_job["id"]
    assert second["status"] == "succeeded"
