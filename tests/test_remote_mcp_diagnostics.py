from __future__ import annotations

from tests.remote_mcp_diagnostics_test_support import *  # noqa: F403

@pytest.mark.parametrize(
    "code,category",
    [
        ("TimeoutError", "network_timeout"),
        ("HTTP_429", "rate_limited"),
        ("Unauthorized", "auth_missing"),
        ("SourceConfigError", "invalid_source_config"),
        ("HTTPError", "upstream_rejected"),
    ],
)
def test_job_diagnostic_classifies_safe_codes(context, code, category):
    job = _create_job(
        context,
        source=False,
        error_code=code,
        error_message=(
            "https://example.com/a?token=secret "
            "Authorization: Bearer hidden"
        ),
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    _assert_fixed_safe_shape(result, kind="job", target_id=job["id"])
    assert result["cause"]["category"] == category
    assert result["cause"]["confidence"] == "confirmed"
    assert result["cause"]["code"] == code


@pytest.mark.parametrize(
    "message,category",
    [
        ("Unauthorized credential is missing", "auth_missing"),
        ("Quota exceeded with HTTP 429", "rate_limited"),
        ("Read timed out", "network_timeout"),
        ("SourceConfig validation error", "invalid_source_config"),
        ("Upstream rejected the request", "upstream_rejected"),
    ],
)
def test_job_diagnostic_uses_sanitized_message_only_as_likely_evidence(
    context, message, category
):
    job = _create_job(
        context,
        source=False,
        error_message=(
            f"{message} at https://example.com/private/path?api_key=secret"
        ),
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    _assert_fixed_safe_shape(result, kind="job", target_id=job["id"])
    assert result["cause"]["category"] == category
    assert result["cause"]["confidence"] == "likely"
    assert result["cause"]["code"] is None
    assert len(result["cause"]["message"]) <= 160


def test_job_diagnostic_does_not_return_or_classify_an_unsafe_code(context):
    job = _create_job(
        context,
        source=False,
        error_code="https://example.com/?token=Unauthorized-secret",
        error_message="unmapped failure",
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["code"] is None
    _assert_fixed_safe_shape(result, kind="job", target_id=job["id"])


def test_unknown_diagnostic_retains_an_unmapped_safe_code(context):
    job = _create_job(
        context,
        source=False,
        error_code="ProviderChanged",
        error_message="unmapped failure",
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["confidence"] == "unknown"
    assert result["cause"]["code"] == "ProviderChanged"
    _assert_fixed_safe_shape(result, kind="job", target_id=job["id"])


def test_source_diagnostic_degrades_to_unknown_without_causal_evidence(context):
    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    _assert_fixed_safe_shape(
        result,
        kind="source",
        target_id=context["subscription"]["id"],
    )
    assert result["status"] == "unknown"
    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["confidence"] == "unknown"
    assert result["cause"]["message"] == "现有记录不足以确定原因"
    assert result["related_job_id"] is None
    assert {item["kind"] for item in result["evidence"]} >= {
        "source_enabled",
        "subscription_enabled",
        "schedule_status",
        "secret_configured",
    }
    secret_evidence = [
        item for item in result["evidence"] if item["kind"] == "secret_configured"
    ]
    assert secret_evidence == [{"kind": "secret_configured", "value": True}]
    assert context["secret_checks"] == ["RSS_PRIVATE_SECRET_ENV"]
    assert "RSS_PRIVATE_SECRET_ENV" not in repr(result)


def test_source_and_subscription_disabled_precede_other_evidence(context):
    job = _create_job(
        context,
        error_code="TimeoutError",
        error_message="timeout",
    )
    _insert_health(
        context,
        job_id=job["id"],
        error_code="TimeoutError",
        error_message="timeout",
    )
    _insert_schedule(
        context,
        enabled=True,
        last_skip_reason="quota_exceeded",
        overdue=True,
    )
    context["store"].update_source(context["source_id"], enabled=False)

    source_disabled = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )
    assert source_disabled["cause"]["category"] == "source_disabled"
    assert source_disabled["cause"]["confidence"] == "confirmed"

    context["store"].update_source(context["source_id"], enabled=True)
    context["store"].update_subscription(
        context["subscription"]["id"], enabled=False
    )
    subscription_disabled = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )
    assert subscription_disabled["cause"]["category"] == "subscription_disabled"
    assert subscription_disabled["cause"]["confidence"] == "confirmed"


@pytest.mark.parametrize(
    "enabled,last_skip_reason,overdue",
    [
        (False, None, False),
        (True, "quota_exceeded", False),
        (True, None, True),
    ],
)
def test_schedule_blocking_precedes_error_codes(
    context, enabled, last_skip_reason, overdue
):
    job = _create_job(context, error_code="TimeoutError", error_message="timeout")
    _insert_health(
        context,
        job_id=job["id"],
        error_code="TimeoutError",
        error_message="timeout",
    )
    _insert_schedule(
        context,
        enabled=enabled,
        last_skip_reason=last_skip_reason,
        overdue=overdue,
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["cause"]["category"] == "schedule_blocked"
    assert result["cause"]["confidence"] == "confirmed"


def test_active_job_with_missing_worker_precedes_error_evidence(context):
    job = _create_job(
        context,
        source=False,
        status="queued",
        error_code="TimeoutError",
        error_message="timeout",
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "worker_unavailable"
    assert result["cause"]["confidence"] == "confirmed"
    worker_evidence = [
        item for item in result["evidence"] if item["kind"] == "worker_status"
    ]
    assert worker_evidence == [{"kind": "worker_status", "value": "missing"}]
    assert "workers" not in _all_keys(result)
    _assert_fixed_safe_shape(result, kind="job", target_id=job["id"])


def test_active_job_with_stale_worker_uses_only_anonymous_status(context):
    job = _create_job(context, source=False, status="running")
    context["store"].upsert_worker_heartbeat(
        "worker-must-not-leak",
        "idle",
        current_job_id=job["id"],
        now=NOW - timedelta(minutes=2),
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "worker_unavailable"
    assert {"kind": "worker_status", "value": "stale"} in result["evidence"]
    assert "worker-must-not-leak" not in repr(result)
    _assert_fixed_safe_shape(result, kind="job", target_id=job["id"])


def test_terminal_job_ignores_disabled_schedule_and_uses_its_own_failure(context):
    _insert_schedule(context, enabled=False)
    job = _create_job(
        context,
        job_type="source_test",
        status="failed",
        error_code="TimeoutError",
        error_message="connection timed out",
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["status"] == "failed"
    assert result["cause"] == {
        "category": "network_timeout",
        "code": "TimeoutError",
        "title": "上游连接超时",
        "message": "连接上游时超时或网络不可用",
        "confidence": "confirmed",
        "retryable": True,
    }
    assert not any(
        item["kind"].startswith("schedule_") for item in result["evidence"]
    )


def test_terminal_successful_job_ignores_old_failing_health(context):
    old_job = _create_job(
        context,
        status="failed",
        error_code="Unauthorized",
        error_message="credential missing",
    )
    _insert_health(
        context,
        job_id=old_job["id"],
        status="failing",
        error_code="Unauthorized",
        error_message="credential missing",
    )
    job = _create_job(
        context,
        job_type="source_test",
        status="succeeded",
        result={"fetched_count": 3},
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["status"] == "succeeded"
    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["code"] is None
    assert not any(
        item["kind"].startswith("health_") for item in result["evidence"]
    )


def test_source_prefers_new_active_schedule_job_over_old_health_job(context):
    old_job = _create_job(
        context,
        status="succeeded",
        result={"fetched_count": 4},
    )
    _insert_health(
        context,
        job_id=old_job["id"],
        status="healthy",
        fetched_count=4,
    )
    active_job = _create_job(context, status="queued")
    context["store"].connect().execute(
        "UPDATE fetch_jobs SET created_at = ? WHERE id = ?",
        ((NOW + timedelta(minutes=1)).isoformat(), active_job["id"]),
    )
    context["store"].connect().commit()
    _insert_schedule(context, enabled=True, last_job_id=active_job["id"])

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["cause"]["category"] == "worker_unavailable"
    assert result["related_job_id"] == active_job["id"]
    assert result["status"] == "queued"
    assert {
        "kind": "health_evidence_role",
        "value": "historical",
    } in result["evidence"]
    assert {"kind": "job_status", "value": "queued"} in result["evidence"]
    assert old_job["id"] not in repr(result)


def test_source_running_schedule_job_with_stale_worker_marks_health_historical(
    context,
):
    old_job = _create_job(
        context,
        status="succeeded",
        result={"fetched_count": 4},
    )
    _insert_health(
        context,
        job_id=old_job["id"],
        status="healthy",
        fetched_count=4,
    )
    active_job = _create_job(context, status="running")
    context["store"].connect().execute(
        "UPDATE fetch_jobs SET created_at = ? WHERE id = ?",
        ((NOW + timedelta(minutes=1)).isoformat(), active_job["id"]),
    )
    context["store"].connect().commit()
    _insert_schedule(context, enabled=True, last_job_id=active_job["id"])
    context["store"].upsert_worker_heartbeat(
        "worker-must-not-leak",
        "idle",
        current_job_id=active_job["id"],
        now=NOW - timedelta(minutes=2),
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["cause"]["category"] == "worker_unavailable"
    assert result["status"] == "running"
    assert {
        "kind": "health_evidence_role",
        "value": "historical",
    } in result["evidence"]
    assert {"kind": "worker_status", "value": "stale"} in result["evidence"]
    assert "worker-must-not-leak" not in repr(result)


def test_source_same_id_retry_success_reapplies_current_health(context):
    job = _finalize_failed_source_attempt_with_health(context)
    queue = JobQueue(context["store"])
    retried = queue.retry_job(job["id"], user_id=context["owner"]["id"])
    assert retried["id"] == job["id"] and retried["status"] == "queued"
    claimed = queue.claim_next_job(worker_id="diagnostic-attempt-two-success")
    assert claimed is not None and claimed["id"] == job["id"]
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
                status="succeeded",
                fetched_count=3,
            ),
        ),
        commit=False,
    )
    queue.complete_job(
        job["id"],
        status="succeeded",
        result={"fetched_count": 3},
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] == job["id"]
    assert result["status"] == "healthy"
    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["code"] is None
    assert {
        "kind": "health_evidence_role",
        "value": "current",
    } in result["evidence"]
    assert {"kind": "last_fetched_count", "value": 3} in result["evidence"]
    assert {"kind": "job_status", "value": "succeeded"} in result["evidence"]
