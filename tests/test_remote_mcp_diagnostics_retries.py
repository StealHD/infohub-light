from __future__ import annotations

from tests.remote_mcp_diagnostics_test_support import *  # noqa: F403

def test_catalog_partial_retry_success_reapplies_health_and_diagnostics(
    context, monkeypatch
):
    (context["data_dir"] / "config.json").write_text(
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
    attempts = iter(
        (
            _catalog_worker_result(
                context,
                run_id="run_partial_zero",
                status="partial",
                fetched_count=0,
            ),
            _catalog_worker_result(
                context,
                run_id="run_retry_three",
                status="succeeded",
                fetched_count=3,
            ),
        )
    )

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            return next(attempts)

    monkeypatch.setattr(
        "src.services.catalog_source_runner.HorizonOrchestrator", FakeOrchestrator
    )
    queue = JobQueue(context["store"])
    job, created = queue.create_source_fetch_if_absent(
        workspace_id=context["workspace"]["id"],
        user_id=context["owner"]["id"],
        source_id=context["source_id"],
        subscription_id=context["subscription"]["id"],
        payload={},
    )

    first = run_worker_once(
        data_dir=str(context["data_dir"]),
        worker_id="diagnostic-partial-first",
        enqueue_schedules=False,
    )
    first_health = SourceHealthService(context["store"]).get_health(
        context["subscription"]["id"]
    )
    assert created is True
    assert first["id"] == job["id"]
    assert first["status"] == "partial", first
    assert first["result_json"]["fetched_count"] == 0
    assert first_health["status"] == "healthy"
    assert first_health["last_fetched_count"] == 0
    assert context["store"].connect().execute(
        """
        SELECT COUNT(*)
        FROM user_source_health_applications
        WHERE subscription_id = ? AND job_id = ?
        """,
        (context["subscription"]["id"], job["id"]),
    ).fetchone()[0] == 1

    retried = queue.retry_job(job["id"], user_id=context["owner"]["id"])
    second = run_worker_once(
        data_dir=str(context["data_dir"]),
        worker_id="diagnostic-success-second",
        enqueue_schedules=False,
    )
    health = SourceHealthService(context["store"]).get_health(
        context["subscription"]["id"]
    )
    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert retried["id"] == job["id"] and retried["status"] == "queued"
    assert second["id"] == job["id"] and second["status"] == "succeeded"
    assert second["result_json"]["fetched_count"] == 3
    assert health["status"] == "healthy"
    assert health["last_job_id"] == job["id"]
    assert health["last_fetched_count"] == 3
    assert result["status"] == "healthy"
    assert result["cause"]["category"] == "unknown"
    assert result["related_job_id"] == job["id"]
    assert {"kind": "health_evidence_role", "value": "current"} in result[
        "evidence"
    ]
    assert {"kind": "last_fetched_count", "value": 3} in result["evidence"]
    result_summary = next(
        item["value"]
        for item in result["evidence"]
        if item["kind"] == "result_summary"
    )
    assert result_summary["fetched_count"] == 3
    assert result_summary["item_count"] == 3
    assert result_summary["run_status"] == "succeeded"


def test_catalog_partial_manual_retry_drops_old_result_before_a_pre_result_failure(
    context, monkeypatch
):
    (context["data_dir"] / "config.json").write_text(
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
    attempts = iter(
        (
            _catalog_worker_result(
                context,
                run_id="run_partial_with_snapshot",
                status="partial",
                fetched_count=1,
            ),
            RuntimeError("failed before FeedRunResult"),
        )
    )
    running_views = {}

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            attempt = next(attempts)
            if isinstance(attempt, Exception):
                running_job = JobQueue(context["store"]).get_job(job["id"])
                reads = RemoteMCPReadService(context["store"])
                running_views.update(
                    {
                        "job": running_job,
                        "listed": reads.list_jobs(
                            workspace_id=context["workspace"]["id"],
                            user_id=context["owner"]["id"],
                        )["items"][0],
                        "fetched": reads.get_job(
                            workspace_id=context["workspace"]["id"],
                            user_id=context["owner"]["id"],
                            job_id=job["id"],
                        ),
                        "job_diagnostic": context["diagnostics"].diagnose_job(
                            actor=context["actor"],
                            job_id=job["id"],
                        ),
                        "source_diagnostic": context[
                            "diagnostics"
                        ].diagnose_source(
                            actor=context["actor"],
                            subscription_id=context["subscription"]["id"],
                        ),
                    }
                )
                raise attempt
            return attempt

    monkeypatch.setattr(
        "src.services.catalog_source_runner.HorizonOrchestrator", FakeOrchestrator
    )
    queue = JobQueue(context["store"])
    job, created = queue.create_source_fetch_if_absent(
        workspace_id=context["workspace"]["id"],
        user_id=context["owner"]["id"],
        source_id=context["source_id"],
        subscription_id=context["subscription"]["id"],
        payload={},
        max_attempts=1,
    )
    first = run_worker_once(
        data_dir=str(context["data_dir"]),
        worker_id="diagnostic-old-result-first",
        enqueue_schedules=False,
    )
    first_summary = RemoteMCPReadService(context["store"]).get_job(
        workspace_id=context["workspace"]["id"],
        user_id=context["owner"]["id"],
        job_id=job["id"],
    )["result_summary"]
    old_started_at = first["started_at"]
    old_snapshot_id = first_summary["snapshot_id"]

    assert created is True
    assert first["status"] == "partial"
    assert first_summary == {
        "fetched_count": 1,
        "item_count": 1,
        "snapshot_id": old_snapshot_id,
        "run_status": "partial",
    }

    retried = queue.retry_job(job["id"], user_id=context["owner"]["id"])
    reads = RemoteMCPReadService(context["store"])
    queued_views = {
        "listed": reads.list_jobs(
            workspace_id=context["workspace"]["id"],
            user_id=context["owner"]["id"],
        )["items"][0],
        "fetched": reads.get_job(
            workspace_id=context["workspace"]["id"],
            user_id=context["owner"]["id"],
            job_id=job["id"],
        ),
        "job_diagnostic": context["diagnostics"].diagnose_job(
            actor=context["actor"],
            job_id=job["id"],
        ),
        "source_diagnostic": context["diagnostics"].diagnose_source(
            actor=context["actor"],
            subscription_id=context["subscription"]["id"],
        ),
    }

    assert retried["status"] == "queued"
    assert retried["result_json"] is None
    assert retried["started_at"] is None
    for phase in (queued_views,):
        assert phase["listed"]["result_summary"] == {}
        assert phase["fetched"]["result_summary"] == {}
        assert not any(
            item["kind"] == "result_summary"
            for key in ("job_diagnostic", "source_diagnostic")
            for item in phase[key]["evidence"]
        )
        assert old_snapshot_id not in repr(phase)

    second = run_worker_once(
        data_dir=str(context["data_dir"]),
        worker_id="diagnostic-pre-result-second",
        enqueue_schedules=False,
    )
    final_views = {
        "listed": reads.list_jobs(
            workspace_id=context["workspace"]["id"],
            user_id=context["owner"]["id"],
        )["items"][0],
        "fetched": reads.get_job(
            workspace_id=context["workspace"]["id"],
            user_id=context["owner"]["id"],
            job_id=job["id"],
        ),
        "job_diagnostic": context["diagnostics"].diagnose_job(
            actor=context["actor"],
            job_id=job["id"],
        ),
        "source_diagnostic": context["diagnostics"].diagnose_source(
            actor=context["actor"],
            subscription_id=context["subscription"]["id"],
        ),
    }

    assert running_views["job"]["status"] == "running"
    assert running_views["job"]["result_json"] is None
    assert running_views["job"]["started_at"]
    assert running_views["job"]["started_at"] != old_started_at
    assert second["status"] == "failed"
    assert second["error_code"] == "RuntimeError"
    assert second["result_json"] is None
    for phase in (running_views, final_views):
        assert phase["listed"]["result_summary"] == {}
        assert phase["fetched"]["result_summary"] == {}
        assert not any(
            item["kind"] == "result_summary"
            for key in ("job_diagnostic", "source_diagnostic")
            for item in phase[key]["evidence"]
        )
        assert old_snapshot_id not in repr(phase)


@pytest.mark.parametrize(
    ("second_status", "issue", "expected_job_status", "expected_category"),
    (
        (
            "failed",
            RunIssue("fetch", "TimeoutError", "second attempt timed out", False),
            "failed",
            "network_timeout",
        ),
        (
            "partial",
            RunIssue("fetch", "Unauthorized", "second attempt unauthorized", False),
            "partial",
            "auth_missing",
        ),
    ),
)
def test_catalog_partial_retry_terminal_outcome_reapplies_current_health(
    context,
    monkeypatch,
    second_status,
    issue,
    expected_job_status,
    expected_category,
):
    (context["data_dir"] / "config.json").write_text(
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
    attempts = iter(
        (
            _catalog_worker_result(
                context,
                run_id="run_partial_zero_before_terminal",
                status="partial",
                fetched_count=0,
            ),
            _catalog_worker_result(
                context,
                run_id=f"run_retry_{second_status}",
                status=second_status,
                fetched_count=0,
                issue=issue,
            ),
        )
    )

    class FakeOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            return next(attempts)

    monkeypatch.setattr(
        "src.services.catalog_source_runner.HorizonOrchestrator", FakeOrchestrator
    )
    queue = JobQueue(context["store"])
    job, _created = queue.create_source_fetch_if_absent(
        workspace_id=context["workspace"]["id"],
        user_id=context["owner"]["id"],
        source_id=context["source_id"],
        subscription_id=context["subscription"]["id"],
        payload={},
    )
    first = run_worker_once(
        data_dir=str(context["data_dir"]),
        worker_id=f"diagnostic-{second_status}-first",
        enqueue_schedules=False,
    )
    assert first["status"] == "partial", first
    assert SourceHealthService(context["store"]).get_health(
        context["subscription"]["id"]
    )["status"] == "healthy"

    queue.retry_job(job["id"], user_id=context["owner"]["id"])
    second = run_worker_once(
        data_dir=str(context["data_dir"]),
        worker_id=f"diagnostic-{second_status}-second",
        enqueue_schedules=False,
    )
    health = SourceHealthService(context["store"]).get_health(
        context["subscription"]["id"]
    )
    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert second["id"] == job["id"]
    assert second["status"] == expected_job_status
    assert health["status"] == "degraded"
    assert health["last_job_id"] == job["id"]
    assert health["last_issue_code"] == issue.code
    assert health["last_fetched_count"] == 0
    assert context["store"].connect().execute(
        """
        SELECT COUNT(*)
        FROM user_source_health_applications
        WHERE subscription_id = ? AND job_id = ?
        """,
        (context["subscription"]["id"], job["id"]),
    ).fetchone()[0] == 1
    assert result["status"] == "degraded"
    assert result["cause"]["category"] == expected_category
    assert result["cause"]["code"] == issue.code
    assert result["related_job_id"] == job["id"]
    assert {"kind": "health_evidence_role", "value": "current"} in result[
        "evidence"
    ]
    assert {"kind": "health_status", "value": "degraded"} in result["evidence"]
    assert {"kind": "last_fetched_count", "value": 0} in result["evidence"]
    assert {"kind": "job_status", "value": expected_job_status} in result[
        "evidence"
    ]


def test_source_same_id_retry_new_failure_reapplies_current_health(
    context,
):
    job = _finalize_failed_source_attempt_with_health(context)
    queue = JobQueue(context["store"])
    retried = queue.retry_job(job["id"], user_id=context["owner"]["id"])
    assert retried["id"] == job["id"] and retried["status"] == "queued"
    claimed = queue.claim_next_job(worker_id="diagnostic-attempt-two-failure")
    assert claimed is not None and claimed["id"] == job["id"]
    queue.fail_or_retry_job(
        job["id"],
        error_code="Unauthorized",
        error_message="credential missing",
        retryable=False,
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
        commit=False,
    )
    SourceHealthService(context["store"]).apply_outcomes(
        workspace_id=context["workspace"]["id"],
        user_id=context["owner"]["id"],
        job_id=job["id"],
        attempted_at=(NOW + timedelta(minutes=5)).isoformat(),
        outcomes=(
            SourceOutcome(
                source_id=context["source_id"],
                subscription_id=context["subscription"]["id"],
                source_key="rss:diagnostic-attempt",
                analysis_mode="full",
                status="failed",
                fetched_count=0,
                issue=RunIssue(
                    stage="fetch",
                    code="Unauthorized",
                    message="credential missing",
                    retryable=False,
                ),
            ),
        ),
        commit=False,
    )
    context["store"].connect().commit()

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] == job["id"]
    assert result["status"] == "failing"
    assert result["cause"]["category"] == "auth_missing"
    assert result["cause"]["code"] == "Unauthorized"
    assert {
        "kind": "health_evidence_role",
        "value": "current",
    } in result["evidence"]
    assert {"kind": "health_status", "value": "failing"} in result["evidence"]
    assert {"kind": "consecutive_failures", "value": 2} in result["evidence"]
    assert {"kind": "job_status", "value": "failed"} in result["evidence"]
