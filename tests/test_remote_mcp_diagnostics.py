import json
from datetime import datetime, timedelta, timezone

import pytest

from src.mcp.remote_diagnostics import RemoteMCPDiagnostics
from src.mcp.remote_service import RemoteMCPNotFound
from src.services.job_queue import JobQueue
from src.services.runtime_status import RuntimeStatusService
from src.services.subscription_mutation import SubscriptionActor
from src.storage.service_store import ServiceStore


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
ALLOWED_ACTION_MODES = {"prepare_change", "web", "wait", "contact_admin"}
CREDENTIAL_LABELS = (
    "AWS_ACCESS_KEY_ID",
    "SSH_PRIVATE_KEY",
    "OPENAI_KEY_ENV",
    "OPENAI_API_KEY_ENV",
    "RSS_PRIVATE_SECRET_ENV",
    "GITHUB_TOKEN_ENV",
    "MY_API_KEY",
)
FORBIDDEN_KEYS = {
    "payload",
    "payload_json",
    "raw_result",
    "result_json",
    "raw_response",
    "worker_id",
    "claim_token",
    "locked_until",
    "config",
    "config_json",
    "secret_env",
    "secret_value",
    "user_id",
    "owner_user_id",
    "workspace_id",
}


def _all_keys(value):
    if isinstance(value, dict):
        return set(value) | {
            key for item in value.values() for key in _all_keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def _assert_fixed_safe_shape(result, *, kind, target_id):
    assert set(result) == {
        "target",
        "status",
        "cause",
        "evidence",
        "suggested_actions",
        "related_job_id",
    }
    assert result["target"]["kind"] == kind
    assert result["target"]["id"] == target_id
    assert set(result["target"]) == {"kind", "id", "name"}
    assert set(result["cause"]) == {
        "category",
        "code",
        "title",
        "message",
        "confidence",
        "retryable",
    }
    assert all(set(item) == {"kind", "value"} for item in result["evidence"])
    assert all(
        set(item) == {"code", "mode", "label"}
        and item["mode"] in ALLOWED_ACTION_MODES
        for item in result["suggested_actions"]
    )
    assert not FORBIDDEN_KEYS & _all_keys(result)
    rendered = repr(result)
    assert "Authorization:" not in rendered
    assert "Bearer " not in rendered
    assert "?token=" not in rendered
    assert "?api_key=" not in rendered
    assert "https://" not in rendered
    assert "http://" not in rendered
    assert all(
        phrase not in item["label"]
        for item in result["suggested_actions"]
        for phrase in ("已修复", "修复成功", "已完成", "已经处理")
    )


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "owner-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    other = store.create_user(
        workspace_id=workspace["id"],
        username="other",
        password="other-password",
        role="member",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Example Feed",
        config={
            "url": "https://private.example/feed?token=source-secret",
            "headers": {"Authorization": "Bearer source-secret"},
        },
        secret_env="RSS_PRIVATE_SECRET_ENV",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    other_source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=other["id"],
        source_type="rss",
        display_name="Other Feed",
        config={"url": "https://other.example/feed"},
        secret_env="OTHER_PRIVATE_SECRET_ENV",
    )
    other_subscription = store.create_subscription(
        user_id=other["id"],
        source_id=other_source_id,
    )
    actor = SubscriptionActor(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        role=owner["role"],
    )
    secret_checks = []

    def secret_is_set(env_name):
        secret_checks.append(env_name)
        return env_name == "RSS_PRIVATE_SECRET_ENV"

    diagnostics = RemoteMCPDiagnostics(
        store,
        runtime_status=RuntimeStatusService(store),
        secret_is_set=secret_is_set,
        now=lambda: NOW,
    )
    return {
        "store": store,
        "workspace": workspace,
        "owner": owner,
        "other": other,
        "source_id": source_id,
        "subscription": subscription,
        "other_source_id": other_source_id,
        "other_subscription": other_subscription,
        "actor": actor,
        "diagnostics": diagnostics,
        "secret_checks": secret_checks,
    }


def _create_job(
    context,
    *,
    owner=True,
    source=True,
    job_type=None,
    status="failed",
    error_code=None,
    error_message=None,
    result=None,
):
    user = context["owner"] if owner else context["other"]
    source_id = (
        context["source_id"] if owner else context["other_source_id"]
    ) if source else None
    subscription_id = (
        context["subscription"]["id"]
        if owner
        else context["other_subscription"]["id"]
    ) if source else None
    job = JobQueue(context["store"]).create_job(
        workspace_id=context["workspace"]["id"],
        user_id=user["id"],
        source_id=source_id,
        subscription_id=subscription_id,
        job_type=job_type or ("source_fetch" if source else "user_feed_refresh"),
        payload={
            "authorization": "Bearer payload-secret",
            "url": "https://payload.example/a?api_key=payload-secret",
        },
    )
    context["store"].connect().execute(
        """
        UPDATE fetch_jobs
        SET status = ?, attempts = 2, max_attempts = 4,
            worker_id = 'worker-private-id', claim_token = 'claim-private-token',
            locked_until = ?, error_code = ?, error_message = ?, result_json = ?,
            started_at = created_at, finished_at = updated_at
        WHERE id = ?
        """,
        (
            status,
            (NOW + timedelta(minutes=5)).isoformat(),
            error_code,
            error_message,
            json.dumps(result) if result is not None else None,
            job["id"],
        ),
    )
    context["store"].connect().commit()
    return JobQueue(context["store"]).get_job(job["id"])


def _insert_health(
    context,
    *,
    job_id=None,
    status="failing",
    error_code=None,
    error_message=None,
    fetched_count=0,
):
    subscription = context["subscription"]
    timestamp = NOW.isoformat()
    context["store"].connect().execute(
        """
        INSERT INTO user_source_health (
            subscription_id, workspace_id, user_id, source_id, status,
            last_attempt_at, last_success_at, last_failure_at,
            consecutive_failures, last_fetched_count, last_issue_stage,
            last_issue_code, last_issue_message, last_issue_retryable,
            last_job_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subscription["id"],
            context["workspace"]["id"],
            context["owner"]["id"],
            context["source_id"],
            status,
            timestamp,
            timestamp if status == "healthy" else None,
            timestamp if status != "healthy" else None,
            0 if status == "healthy" else 2,
            fetched_count,
            "fetch",
            error_code,
            error_message,
            1 if status != "healthy" else None,
            job_id,
            timestamp,
            timestamp,
        ),
    )
    context["store"].connect().commit()


def _insert_schedule(
    context,
    *,
    enabled,
    last_skip_reason=None,
    overdue=False,
    last_job_id=None,
):
    timestamp = NOW.isoformat()
    next_run_at = (
        NOW - timedelta(minutes=1) if overdue else NOW + timedelta(hours=1)
    ).isoformat()
    context["store"].connect().execute(
        """
        INSERT INTO user_source_schedules (
            subscription_id, workspace_id, user_id, source_id, enabled,
            interval_minutes, next_run_at, last_evaluated_at,
            last_enqueued_at, last_job_id, last_skip_reason,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 60, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            context["subscription"]["id"],
            context["workspace"]["id"],
            context["owner"]["id"],
            context["source_id"],
            1 if enabled else 0,
            next_run_at,
            timestamp,
            last_job_id,
            last_skip_reason,
            timestamp,
            timestamp,
        ),
    )
    context["store"].connect().commit()


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
    assert {"kind": "job_status", "value": "queued"} in result["evidence"]
    assert old_job["id"] not in repr(result)


def test_source_accepts_owned_full_refresh_linked_by_health_fk(context):
    refresh_job = _create_job(
        context,
        source=False,
        status="succeeded",
        result={"fetched_count": 7},
    )
    assert refresh_job["source_id"] is None
    assert refresh_job["subscription_id"] is None
    _insert_health(
        context,
        job_id=refresh_job["id"],
        status="healthy",
        fetched_count=7,
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] == refresh_job["id"]
    assert {
        "kind": "result_summary",
        "value": {"fetched_count": 7},
    } in result["evidence"]


def test_source_uses_newer_failed_schedule_job_over_old_healthy_health(context):
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
    failed_job = _create_job(
        context,
        status="failed",
        error_code="SourceConfigError",
        error_message="invalid source config",
    )
    context["store"].connect().executemany(
        "UPDATE fetch_jobs SET created_at = ? WHERE id = ?",
        (
            (NOW.isoformat(), old_job["id"]),
            ((NOW + timedelta(minutes=1)).isoformat(), failed_job["id"]),
        ),
    )
    context["store"].connect().commit()
    _insert_schedule(context, enabled=True, last_job_id=failed_job["id"])

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] == failed_job["id"]
    assert result["status"] == "failed"
    assert result["cause"]["category"] == "invalid_source_config"
    assert {
        "kind": "related_job_provenance",
        "value": "schedule",
    } in result["evidence"]
    assert {
        "kind": "health_evidence_role",
        "value": "historical",
    } in result["evidence"]


def test_source_newer_schedule_failure_wins_conflicting_old_health_code(context):
    old_job = _create_job(
        context,
        status="failed",
        error_code="TimeoutError",
        error_message="connection timed out",
    )
    _insert_health(
        context,
        job_id=old_job["id"],
        status="failing",
        error_code="TimeoutError",
        error_message="connection timed out",
    )
    failed_job = _create_job(
        context,
        status="failed",
        error_code="Unauthorized",
        error_message="credential missing",
    )
    context["store"].connect().executemany(
        "UPDATE fetch_jobs SET created_at = ? WHERE id = ?",
        (
            (NOW.isoformat(), old_job["id"]),
            ((NOW + timedelta(minutes=1)).isoformat(), failed_job["id"]),
        ),
    )
    context["store"].connect().commit()
    _insert_schedule(context, enabled=True, last_job_id=failed_job["id"])

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] == failed_job["id"]
    assert result["status"] == "failed"
    assert result["cause"]["category"] == "auth_missing"
    assert result["cause"]["code"] == "Unauthorized"


def test_safe_code_precedes_conflicting_sanitized_message(context):
    job = _create_job(
        context,
        source=False,
        error_code="TimeoutError",
        error_message="Unauthorized credential missing",
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "network_timeout"
    assert result["cause"]["confidence"] == "confirmed"


def test_successful_zero_item_attempt_is_confirmed_no_items(context):
    job = _create_job(
        context,
        source=False,
        status="succeeded",
        result={"fetched_count": 0, "raw_response": "raw-result-secret"},
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "no_items"
    assert result["cause"]["confidence"] == "confirmed"
    assert {"kind": "result_summary", "value": {"fetched_count": 0}} in result[
        "evidence"
    ]
    assert "raw-result-secret" not in repr(result)


def test_job_zero_items_does_not_use_an_older_source_health_attempt(context):
    _insert_health(context, status="healthy", fetched_count=0)
    job = _create_job(
        context,
        status="failed",
        result={"fetched_count": 5},
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["confidence"] == "unknown"


def test_job_zero_items_requires_explicit_zero_fetched_count(context):
    job = _create_job(
        context,
        source=False,
        status="succeeded",
        result={"fetched_count": 5, "item_count": 0},
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "unknown"
    assert result["cause"]["confidence"] == "unknown"


@pytest.mark.parametrize("invalid_count", [False, True, -1, 0.5, "0"])
def test_job_zero_items_rejects_non_json_nonnegative_integer_counts(
    context, invalid_count
):
    job = _create_job(
        context,
        source=False,
        status="succeeded",
        result={"fetched_count": invalid_count},
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["category"] == "unknown"
    assert not any(
        item["kind"] == "result_summary" and "fetched_count" in item["value"]
        for item in result["evidence"]
    )


@pytest.mark.parametrize("invalid_count", [False, True, -1, 0.5, "0"])
def test_source_zero_items_rejects_non_json_nonnegative_integer_job_counts(
    context, invalid_count
):
    job = _create_job(
        context,
        status="succeeded",
        result={"fetched_count": invalid_count},
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] == job["id"]
    assert result["cause"]["category"] == "unknown"
    assert not any(
        item["kind"] == "result_summary" and "fetched_count" in item["value"]
        for item in result["evidence"]
    )


def test_source_zero_items_accepts_a_validated_related_successful_job(context):
    job = _create_job(
        context,
        status="succeeded",
        result={"fetched_count": 0},
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["cause"]["category"] == "no_items"
    assert result["related_job_id"] == job["id"]


def test_successful_zero_item_source_health_is_confirmed_no_items(context):
    _insert_health(context, status="healthy", fetched_count=0)

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["status"] == "healthy"
    assert result["cause"]["category"] == "no_items"
    assert result["cause"]["confidence"] == "confirmed"
    _assert_fixed_safe_shape(
        result,
        kind="source",
        target_id=context["subscription"]["id"],
    )


def test_source_diagnostic_combines_health_related_job_and_secret_boolean(context):
    job = _create_job(
        context,
        error_code="Unauthorized",
        error_message=(
            "Authorization: Bearer job-secret "
            "https://job.example/private?token=job-secret"
        ),
        result={
            "fetched_count": 0,
            "issue_count": 1,
            "raw_response": "raw-result-secret",
        },
    )
    _insert_health(
        context,
        job_id=job["id"],
        error_code="Unauthorized",
        error_message=(
            "Authorization: Bearer health-secret "
            "https://health.example/private?api_key=health-secret"
        ),
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["status"] == "failing"
    assert result["cause"]["category"] == "auth_missing"
    assert result["cause"]["confidence"] == "confirmed"
    assert result["related_job_id"] == job["id"]
    assert {"kind": "consecutive_failures", "value": 2} in result["evidence"]
    assert {"kind": "secret_configured", "value": True} in result["evidence"]
    assert {"kind": "result_summary", "value": {
        "fetched_count": 0,
        "issue_count": 1,
    }} in result["evidence"]
    _assert_fixed_safe_shape(
        result,
        kind="source",
        target_id=context["subscription"]["id"],
    )
    rendered = repr(result)
    assert "job-secret" not in rendered
    assert "health-secret" not in rendered
    assert "raw-result-secret" not in rendered
    assert "worker-private-id" not in rendered
    assert "claim-private-token" not in rendered
    assert "source-secret" not in rendered


@pytest.mark.parametrize(
    "credential_label",
    CREDENTIAL_LABELS,
)
def test_job_diagnostic_rejects_credential_key_labels_in_codes(
    context, credential_label
):
    job = _create_job(
        context,
        source=False,
        error_code=credential_label,
        error_message="unmapped failure",
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["code"] is None
    assert credential_label not in repr(result)


@pytest.mark.parametrize(
    "credential_label",
    CREDENTIAL_LABELS,
)
def test_source_diagnostic_rejects_credential_key_labels_in_health_codes(
    context, credential_label
):
    _insert_health(
        context,
        error_code=credential_label,
        error_message="unmapped failure",
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["cause"]["code"] is None
    assert credential_label not in repr(result)


@pytest.mark.parametrize("credential_label", CREDENTIAL_LABELS)
def test_source_diagnostic_rejects_credential_key_labels_in_schedule_codes(
    context, credential_label
):
    _insert_schedule(
        context,
        enabled=True,
        last_skip_reason=credential_label,
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["cause"]["code"] == "schedule_blocked"
    assert credential_label not in repr(result)


@pytest.mark.parametrize(
    "credential_label",
    CREDENTIAL_LABELS,
)
def test_job_diagnostic_rejects_credential_key_labels_in_result_identifiers(
    context, credential_label
):
    job = _create_job(
        context,
        source=False,
        result={
            "snapshot_id": credential_label,
            "run_status": credential_label,
        },
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert credential_label not in repr(result)
    assert not any(
        item["kind"] == "result_summary" for item in result["evidence"]
    )


@pytest.mark.parametrize("credential_label", CREDENTIAL_LABELS)
@pytest.mark.parametrize(
    "diagnostic_kind,fallback_name",
    [("source", "来源"), ("job", "来源抓取任务")],
)
def test_diagnostic_target_name_rejects_credential_key_labels(
    context, diagnostic_kind, credential_label, fallback_name
):
    context["store"].update_source(
        context["source_id"], display_name=credential_label
    )
    if diagnostic_kind == "source":
        result = context["diagnostics"].diagnose_source(
            actor=context["actor"],
            subscription_id=context["subscription"]["id"],
        )
    else:
        job = _create_job(context)
        result = context["diagnostics"].diagnose_job(
            actor=context["actor"], job_id=job["id"]
        )

    assert result["target"]["name"] == fallback_name
    assert credential_label not in repr(result)


def test_source_target_name_classifies_the_complete_scalar_before_truncation(context):
    credential_label = f"{'public-prefix-' * 12}AWS_ACCESS_KEY_ID"
    context["store"].update_source(
        context["source_id"], display_name=credential_label
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["target"]["name"] == "来源"
    assert "AWS_ACCESS_KEY_ID" not in repr(result)


@pytest.mark.parametrize("diagnostic_kind", ["source", "job"])
def test_each_public_diagnostic_uses_one_consistent_checked_at(
    context, diagnostic_kind
):
    _insert_schedule(context, enabled=True)
    boundary = NOW + timedelta(seconds=1)
    context["store"].connect().execute(
        "UPDATE user_source_schedules SET next_run_at = ? WHERE subscription_id = ?",
        (boundary.isoformat(), context["subscription"]["id"]),
    )
    context["store"].connect().commit()
    observed_times = []

    def increasing_clock():
        current = NOW + timedelta(seconds=len(observed_times) * 2)
        observed_times.append(current)
        return current

    diagnostics = RemoteMCPDiagnostics(
        context["store"],
        runtime_status=RuntimeStatusService(context["store"]),
        secret_is_set=lambda _env_name: True,
        now=increasing_clock,
    )
    if diagnostic_kind == "source":
        result = diagnostics.diagnose_source(
            actor=context["actor"],
            subscription_id=context["subscription"]["id"],
        )
        assert {"kind": "schedule_status", "value": "ready"} in result[
            "evidence"
        ]
    else:
        job = _create_job(context, status="failed")
        result = diagnostics.diagnose_job(
            actor=context["actor"], job_id=job["id"]
        )

    assert result["cause"]["category"] == "unknown"
    assert observed_times == [NOW]


def test_cross_user_and_missing_targets_share_not_found(context):
    other_job = _create_job(
        context,
        owner=False,
        source=False,
        error_code="TimeoutError",
        error_message="timeout",
    )

    for subscription_id in (
        context["other_subscription"]["id"],
        "sub_missing",
    ):
        with pytest.raises(RemoteMCPNotFound, match="not_found"):
            context["diagnostics"].diagnose_source(
                actor=context["actor"], subscription_id=subscription_id
            )
    for job_id in (other_job["id"], "job_missing"):
        with pytest.raises(RemoteMCPNotFound, match="not_found"):
            context["diagnostics"].diagnose_job(
                actor=context["actor"], job_id=job_id
            )


def test_source_health_cannot_link_another_users_job_into_diagnostics(context):
    other_job = _create_job(
        context,
        owner=False,
        source=False,
        error_code="Unauthorized",
        error_message="Bearer other-job-secret",
    )
    _insert_health(context, job_id=other_job["id"], status="healthy", fetched_count=3)

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] is None
    assert other_job["id"] not in repr(result)
    assert "other-job-secret" not in repr(result)
    _assert_fixed_safe_shape(
        result,
        kind="source",
        target_id=context["subscription"]["id"],
    )


def test_diagnostics_leave_persisted_state_unchanged(context):
    job = _create_job(
        context,
        error_code="TimeoutError",
        error_message="timeout at https://example.com/?token=secret",
    )
    _insert_health(
        context,
        job_id=job["id"],
        error_code="TimeoutError",
        error_message="timeout at https://example.com/?token=secret",
    )
    before = "\n".join(context["store"].connect().iterdump())

    context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )
    context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert "\n".join(context["store"].connect().iterdump()) == before
