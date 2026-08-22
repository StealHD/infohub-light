import json
from datetime import datetime, timedelta, timezone

import pytest

from src.mcp.remote_diagnostics import RemoteMCPDiagnostics
from src.mcp.remote_service import (
    RemoteMCPNotFound,
    RemoteMCPReadService,
)
from src.models import ContentItem, SourceType
from src.services.feed_run import FeedRunResult, RunIssue, SourceOutcome
from src.services.job_queue import JobQueue
from src.services.runtime_status import RuntimeStatusService
from src.services.source_health import SourceHealthService
from src.services.subscription_mutation import SubscriptionActor
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
ALLOWED_ACTION_MODES = {"prepare_change", "web", "wait", "contact_admin"}
CREDENTIAL_LABELS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_ACCESS_KEY",
    "AZURE_STORAGE_KEY",
    "SSH_PRIVATE_KEY",
    "OPENAI_KEY_ENV",
    "OPENAI_API_KEY_ENV",
    "RSS_PRIVATE_SECRET_ENV",
    "GITHUB_TOKEN_ENV",
    "MY_API_KEY",
    "DATABASE_CONNECTION_STRING",
    "CREDENTIAL",
    "CREDENTIALS",
    "GOOGLE_APPLICATION_CREDENTIAL",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_APPLICATION_CREDENTIALS_JSON",
    "credentials_json",
    "Bearer:hidden",
    "Bearer_hidden",
    "Basic.hidden",
    "Basic-hidden",
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
        "data_dir": tmp_path,
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


def _catalog_worker_result(
    context,
    *,
    run_id,
    status,
    fetched_count,
    issue=None,
):
    timestamp = datetime.now(timezone.utc).isoformat()
    items = tuple(
        ContentItem(
            id=f"rss:{run_id}:{index}",
            source_type=SourceType.RSS,
            title=f"Item {index}",
            url=f"https://example.com/{run_id}/{index}",
            published_at=datetime.now(timezone.utc),
            metadata={
                "source_id": context["source_id"],
                "subscription_id": context["subscription"]["id"],
            },
        )
        for index in range(fetched_count)
    )
    return FeedRunResult(
        run_id=run_id,
        status=status,
        started_at=timestamp,
        finished_at=timestamp,
        items=items,
        source_outcomes=(
            SourceOutcome(
                source_id=context["source_id"],
                subscription_id=context["subscription"]["id"],
                source_key="rss:diagnostic-retry",
                analysis_mode="full",
                status="failed" if issue else "succeeded",
                fetched_count=fetched_count,
                issue=issue,
            ),
        ),
        issues=(issue,) if issue else (),
    )


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


def _finalize_failed_source_attempt_with_health(
    context,
    *,
    error_code="TimeoutError",
    error_message="connection timed out",
):
    queue = JobQueue(context["store"])
    job = queue.create_job(
        workspace_id=context["workspace"]["id"],
        user_id=context["owner"]["id"],
        source_id=context["source_id"],
        subscription_id=context["subscription"]["id"],
        job_type="source_fetch",
        payload={},
        max_attempts=1,
    )
    claimed = queue.claim_next_job(worker_id="diagnostic-attempt-one")
    assert claimed is not None and claimed["id"] == job["id"]
    finalized = queue.fail_or_retry_job(
        job["id"],
        error_code=error_code,
        error_message=error_message,
        retryable=False,
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
        commit=False,
    )
    SourceHealthService(context["store"]).apply_outcomes(
        workspace_id=context["workspace"]["id"],
        user_id=context["owner"]["id"],
        job_id=job["id"],
        attempted_at=(NOW - timedelta(minutes=5)).isoformat(),
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
                    code=error_code,
                    message=error_message,
                    retryable=False,
                ),
            ),
        ),
        commit=False,
    )
    context["store"].connect().commit()
    assert finalized["status"] == "failed"
    _insert_schedule(context, enabled=True, last_job_id=job["id"])
    return job

def test_support_exports_diagnostic_fixture_and_shape_guard() -> None:
    assert callable(context)
    assert callable(_assert_fixed_safe_shape)


__all__ = [
    name
    for name in globals()
    if not name.startswith("__") and name != "test_support_exports_diagnostic_fixture_and_shape_guard"
]
