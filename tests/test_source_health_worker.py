from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.services.feed_run import FeedRunResult, RunIssue, SourceOutcome
from src.services.feed_production import FeedRunFailed
from src.services.job_queue import JobQueue
from src.services.source_health import SourceHealthService
from src.services.user_feed_store import UserFeedSnapshotInput, UserFeedStore
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


def _write_config(tmp_path) -> None:
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


def _context(tmp_path, monkeypatch, *, source_count: int = 1):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    _write_config(tmp_path)
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    sources = []
    subscriptions = []
    for index in range(source_count):
        source_id = store.create_source(
            workspace_id=workspace["id"],
            scope="public",
            owner_user_id=owner["id"],
            source_type="rss",
            display_name=f"Health Worker Feed {index}",
            config={"url": f"https://example.com/health-{index}.xml"},
            source_key=f"rss:https://example.com/health-{index}.xml",
        )
        sources.append(source_id)
        subscriptions.append(
            store.create_subscription(user_id=owner["id"], source_id=source_id)
        )
    return store, workspace, owner, sources, subscriptions


def _outcome(
    source_id: str,
    subscription_id: str,
    *,
    status: str = "succeeded",
    count: int = 1,
    issue: RunIssue | None = None,
) -> SourceOutcome:
    return SourceOutcome(
        source_id=source_id,
        subscription_id=subscription_id,
        source_key=f"rss:{source_id}",
        analysis_mode="full",
        status=status,
        fetched_count=count,
        issue=issue,
    )


def test_worker_success_and_partial_finalize_snapshot_health_and_job_without_legacy_outputs(
    tmp_path, monkeypatch
):
    store, workspace, owner, sources, subscriptions = _context(
        tmp_path, monkeypatch, source_count=2
    )
    queue = JobQueue(store)
    first_job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )
    issue = RunIssue("fetch", "TimeoutError", "second source timed out", True)
    results = iter(
        (
            FeedRunResult(
                run_id="health-success",
                status="succeeded",
                started_at="2026-07-11T01:59:00+00:00",
                finished_at="2026-07-11T02:00:00+00:00",
                source_outcomes=(
                    _outcome(sources[0], subscriptions[0]["id"], count=1),
                ),
            ),
            FeedRunResult(
                run_id="health-partial",
                status="partial",
                started_at="2026-07-11T02:59:00+00:00",
                finished_at="2026-07-11T03:00:00+00:00",
                source_outcomes=(
                    _outcome(sources[0], subscriptions[0]["id"], count=0),
                    _outcome(
                        sources[1],
                        subscriptions[1]["id"],
                        status="failed",
                        count=0,
                        issue=issue,
                    ),
                ),
                issues=(issue,),
            ),
        )
    )

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            return next(results)

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)

    first = run_worker_once(data_dir=str(tmp_path), worker_id="health-worker-success")
    first_health = SourceHealthService(store).get_health(subscriptions[0]["id"])
    second_job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )
    second = run_worker_once(data_dir=str(tmp_path), worker_id="health-worker-partial")
    first_after_partial = SourceHealthService(store).get_health(subscriptions[0]["id"])
    second_health = SourceHealthService(store).get_health(subscriptions[1]["id"])

    assert first["id"] == first_job["id"]
    assert first["status"] == "succeeded"
    assert first_health["status"] == "healthy"
    assert first_health["last_job_id"] == first_job["id"]
    assert second["id"] == second_job["id"]
    assert second["status"] == "partial"
    assert first_after_partial["status"] == "healthy"
    assert first_after_partial["last_fetched_count"] == 0
    assert first_after_partial["last_job_id"] == second_job["id"]
    assert second_health["status"] == "degraded"
    assert second_health["last_job_id"] == second_job["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_feed_snapshots WHERE job_id IN (?, ?)",
        (first_job["id"], second_job["id"]),
    ).fetchone()[0] == 1
    assert first["result_json"]["snapshot_created"] is True
    assert second["result_json"]["snapshot_created"] is False
    assert not (tmp_path / "site" / "radar-data.json").exists()
    assert not (tmp_path / "site" / "history-data.json").exists()


def test_catalog_source_fetch_applies_only_target_source_outcome(tmp_path, monkeypatch):
    store, workspace, owner, sources, subscriptions = _context(
        tmp_path, monkeypatch, source_count=2
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=sources[0],
        subscription_id=subscriptions[0]["id"],
        job_type="source_fetch",
        payload={},
    )
    issue = RunIssue("fetch", "UnexpectedExtraOutcome", "must be ignored", False)

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            return FeedRunResult(
                run_id="target-source-fetch",
                status="partial",
                started_at="2026-07-11T03:59:00+00:00",
                finished_at="2026-07-11T04:00:00+00:00",
                source_outcomes=(
                    _outcome(sources[0], subscriptions[0]["id"], count=0),
                    _outcome(
                        sources[1],
                        subscriptions[1]["id"],
                        status="failed",
                        count=0,
                        issue=issue,
                    ),
                ),
                issues=(issue,),
            )

    monkeypatch.setattr(
        "src.services.catalog_source_runner.HorizonOrchestrator", FakeOrchestrator
    )

    result = run_worker_once(data_dir=str(tmp_path), worker_id="health-source-fetch")

    assert result["id"] == job["id"]
    assert result["status"] == "partial"
    assert SourceHealthService(store).get_health(subscriptions[0]["id"])["status"] == "healthy"
    assert SourceHealthService(store).get_health(subscriptions[1]["id"]) is None


def test_structured_failed_run_writes_health_only_on_final_attempt_and_no_snapshot(
    tmp_path, monkeypatch
):
    store, workspace, owner, sources, subscriptions = _context(tmp_path, monkeypatch)
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
        max_attempts=2,
    )
    issue = RunIssue("fetch", "TimeoutError", "upstream timeout", True)
    failed_result = FeedRunResult(
        run_id="all-source-failed",
        status="failed",
        started_at="2026-07-11T04:59:00+00:00",
        finished_at="2026-07-11T05:00:00+00:00",
        source_outcomes=(
            _outcome(
                sources[0],
                subscriptions[0]["id"],
                status="failed",
                count=0,
                issue=issue,
            ),
        ),
        issues=(issue,),
    )

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            return failed_result

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)

    retry = run_worker_once(
        data_dir=str(tmp_path), worker_id="health-failed-worker", retry_base_seconds=0
    )
    assert retry["status"] == "queued"
    assert SourceHealthService(store).get_health(subscriptions[0]["id"]) is None

    final = run_worker_once(
        data_dir=str(tmp_path), worker_id="health-failed-worker", retry_base_seconds=0
    )
    health = SourceHealthService(store).get_health(subscriptions[0]["id"])

    assert final["id"] == job["id"]
    assert final["status"] == "failed"
    assert final["attempts"] == 2
    assert health["status"] == "degraded"
    assert health["consecutive_failures"] == 1
    assert health["last_job_id"] == job["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_feed_snapshots WHERE job_id = ?", (job["id"],)
    ).fetchone()[0] == 0


def test_source_test_and_job_level_error_without_outcomes_do_not_write_health(
    tmp_path, monkeypatch
):
    store, workspace, owner, sources, subscriptions = _context(tmp_path, monkeypatch)
    queue = JobQueue(store)
    source_test_job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=sources[0],
        subscription_id=subscriptions[0]["id"],
        job_type="source_test",
        payload={},
    )
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda _payload: {"ok": True, "source_type": "rss"},
    )

    source_test_result = run_worker_once(
        data_dir=str(tmp_path), worker_id="health-source-test"
    )

    assert source_test_result["id"] == source_test_job["id"]
    assert source_test_result["status"] == "succeeded"
    assert SourceHealthService(store).get_health(subscriptions[0]["id"]) is None

    source_fetch_job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=sources[0],
        subscription_id=subscriptions[0]["id"],
        job_type="source_fetch",
        payload={},
        max_attempts=1,
    )

    def job_level_failure(*_args, **_kwargs):
        raise RuntimeError("job-level failure without structured source outcomes")

    monkeypatch.setattr(
        "src.services.catalog_source_runner.run_catalog_source_fetch",
        job_level_failure,
    )
    failed = run_worker_once(data_dir=str(tmp_path), worker_id="health-job-error")

    assert failed["id"] == source_fetch_job["id"]
    assert failed["status"] == "failed"
    assert SourceHealthService(store).get_health(subscriptions[0]["id"]) is None


def test_fail_or_retry_job_can_join_outer_transaction_without_committing(
    tmp_path, monkeypatch
):
    store, workspace, owner, sources, subscriptions = _context(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=sources[0],
        subscription_id=subscriptions[0]["id"],
        job_type="source_fetch",
        payload={},
        max_attempts=1,
    )
    claim = queue.claim_next_job(worker_id="outer-worker", lease_seconds=60)
    conn = store.connect()
    conn.execute("BEGIN IMMEDIATE")

    finalized = queue.fail_or_retry_job(
        job["id"],
        error_code="StructuredFailure",
        error_message="final",
        worker_id="outer-worker",
        claim_token=claim["claim_token"],
        commit=False,
    )

    assert finalized["status"] == "failed"
    assert conn.in_transaction is True
    conn.rollback()
    assert queue.get_job(job["id"])["status"] == "running"


def test_expired_claim_rolls_back_pending_snapshot_and_health(tmp_path, monkeypatch):
    store, workspace, owner, sources, subscriptions = _context(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=sources[0],
        subscription_id=subscriptions[0]["id"],
        job_type="source_fetch",
        payload={},
    )
    claim = queue.claim_next_job(worker_id="expired-health-worker", lease_seconds=60)
    store.connect().execute(
        "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), job["id"]),
    )
    store.connect().commit()

    UserFeedStore(store).save_run_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        snapshot=UserFeedSnapshotInput(
            run_id="expired-health-run",
            run_status="succeeded",
            generated_at="2026-07-11T06:00:00+00:00",
            items=(),
        ),
        commit=False,
    )
    SourceHealthService(store).apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at="2026-07-11T06:00:00+00:00",
        outcomes=(_outcome(sources[0], subscriptions[0]["id"], count=0),),
        commit=False,
    )

    with pytest.raises(PermissionError, match="claim"):
        queue.complete_job(
            job["id"],
            status="succeeded",
            result={"ok": True},
            worker_id="expired-health-worker",
            claim_token=claim["claim_token"],
        )

    assert queue.get_job(job["id"])["status"] == "running"
    assert SourceHealthService(store).get_health(subscriptions[0]["id"]) is None
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_feed_snapshots WHERE job_id = ?", (job["id"],)
    ).fetchone()[0] == 0


def test_final_failed_worker_path_rejects_expired_claim_without_writing_health(
    tmp_path, monkeypatch
):
    store, workspace, owner, sources, subscriptions = _context(tmp_path, monkeypatch)
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
        max_attempts=1,
    )
    issue = RunIssue("fetch", "TimeoutError", "late structured failure", True)
    failed_result = FeedRunResult(
        run_id="expired-final-failure",
        status="failed",
        started_at="2026-07-11T06:59:00+00:00",
        finished_at="2026-07-11T07:00:00+00:00",
        source_outcomes=(
            _outcome(
                sources[0],
                subscriptions[0]["id"],
                status="failed",
                count=0,
                issue=issue,
            ),
        ),
        issues=(issue,),
    )

    def expire_claim_then_fail(claimed_job, *, data_dir, store):
        store.connect().execute(
            "UPDATE fetch_jobs SET locked_until = ? WHERE id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
                claimed_job["id"],
            ),
        )
        store.connect().commit()
        raise FeedRunFailed(failed_result)

    monkeypatch.setattr("src.services.worker._run_job", expire_claim_then_fail)

    with pytest.raises(PermissionError, match="claim"):
        run_worker_once(
            data_dir=str(tmp_path),
            worker_id="expired-final-health-worker",
            lease_seconds=60,
            retry_base_seconds=0,
        )

    loaded = JobQueue(store).get_job(job["id"])
    assert loaded["status"] == "running"
    assert SourceHealthService(store).get_health(subscriptions[0]["id"]) is None
