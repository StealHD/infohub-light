from __future__ import annotations

from datetime import datetime

import pytest

from src.services.feed_run import RunIssue, SourceOutcome
from src.services.job_queue import JobQueue
from src.storage.service_store import ServiceStore


ATTEMPT_1 = "2026-07-11T01:00:00+00:00"
ATTEMPT_2 = "2026-07-11T02:00:00+00:00"
ATTEMPT_3 = "2026-07-11T03:00:00+00:00"


def _context(tmp_path, monkeypatch):
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
        display_name="Health Feed",
        config={"url": "https://example.com/health.xml"},
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    return store, workspace, owner, source_id, subscription


def _service(store):
    from src.services.source_health import SourceHealthService

    return SourceHealthService(store)


def _job(store, workspace, user, source_id, subscription_id):
    return JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=user["id"],
        job_type="source_fetch",
        source_id=source_id,
        subscription_id=subscription_id,
        payload={},
    )


def _outcome(
    source_id: str,
    subscription_id: str | None,
    *,
    status: str = "succeeded",
    fetched_count: int = 3,
    issue: RunIssue | None = None,
) -> SourceOutcome:
    return SourceOutcome(
        source_id=source_id,
        subscription_id=subscription_id,
        source_key="rss:https://example.com/health.xml",
        analysis_mode="full",
        status=status,
        fetched_count=fetched_count,
        issue=issue,
    )


def test_missing_health_is_unknown_and_outcome_without_subscription_does_not_create_row(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    job = _job(store, workspace, owner, source_id, subscription["id"])

    assert service.get_health(subscription["id"]) is None
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(_outcome(source_id, None),),
    )

    assert service.get_health(subscription["id"]) is None
    assert store.connect().execute("SELECT COUNT(*) FROM user_source_health").fetchone()[0] == 0


@pytest.mark.parametrize("fetched_count", [4, 0])
def test_success_including_zero_items_records_healthy(tmp_path, monkeypatch, fetched_count):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    job = _job(store, workspace, owner, source_id, subscription["id"])

    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(_outcome(source_id, subscription["id"], fetched_count=fetched_count),),
    )
    health = service.get_health(subscription["id"])

    assert health["status"] == "healthy"
    assert health["last_attempt_at"] == ATTEMPT_1
    assert health["last_success_at"] == ATTEMPT_1
    assert health["last_failure_at"] is None
    assert health["consecutive_failures"] == 0
    assert health["last_fetched_count"] == fetched_count
    assert health["last_issue_stage"] is None
    assert health["last_issue_code"] is None
    assert health["last_issue_message"] is None
    assert health["last_issue_retryable"] is None
    assert health["last_job_id"] == job["id"]


def test_first_and_second_consecutive_failures_degrade_then_fail(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    issue = RunIssue("fetch", "TimeoutError", "upstream timed out", True)

    first_job = _job(store, workspace, owner, source_id, subscription["id"])
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=first_job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(_outcome(source_id, subscription["id"], status="failed", fetched_count=0, issue=issue),),
    )
    first = service.get_health(subscription["id"])

    second_job = _job(store, workspace, owner, source_id, subscription["id"])
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=second_job["id"],
        attempted_at=ATTEMPT_2,
        outcomes=(_outcome(source_id, subscription["id"], status="failed", fetched_count=0, issue=issue),),
    )
    second = service.get_health(subscription["id"])

    assert first["status"] == "degraded"
    assert first["consecutive_failures"] == 1
    assert first["last_failure_at"] == ATTEMPT_1
    assert first["last_success_at"] is None
    assert first["last_issue_retryable"] is True
    assert second["status"] == "failing"
    assert second["consecutive_failures"] == 2
    assert second["last_attempt_at"] == ATTEMPT_2
    assert second["last_failure_at"] == ATTEMPT_2
    assert second["last_success_at"] is None


def test_failed_outcome_without_issue_stores_empty_structured_issue(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    job = _job(store, workspace, owner, source_id, subscription["id"])

    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(
            _outcome(
                source_id,
                subscription["id"],
                status="failed",
                fetched_count=0,
                issue=None,
            ),
        ),
    )
    health = service.get_health(subscription["id"])

    assert health["status"] == "degraded"
    assert health["last_issue_stage"] is None
    assert health["last_issue_code"] is None
    assert health["last_issue_message"] is None
    assert health["last_issue_retryable"] is None


def test_recovery_resets_failures_clears_issue_and_retains_success_failure_timestamps(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    issue = RunIssue("fetch", "HTTPError", "status 503", True)

    failed_job = _job(store, workspace, owner, source_id, subscription["id"])
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=failed_job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(_outcome(source_id, subscription["id"], status="failed", fetched_count=0, issue=issue),),
    )
    success_job = _job(store, workspace, owner, source_id, subscription["id"])
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=success_job["id"],
        attempted_at=ATTEMPT_2,
        outcomes=(_outcome(source_id, subscription["id"], fetched_count=2),),
    )
    recovered = service.get_health(subscription["id"])

    assert recovered["status"] == "healthy"
    assert recovered["consecutive_failures"] == 0
    assert recovered["last_success_at"] == ATTEMPT_2
    assert recovered["last_failure_at"] == ATTEMPT_1
    assert recovered["last_issue_code"] is None
    assert recovered["last_issue_message"] is None

    next_failed_job = _job(store, workspace, owner, source_id, subscription["id"])
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=next_failed_job["id"],
        attempted_at=ATTEMPT_3,
        outcomes=(_outcome(source_id, subscription["id"], status="failed", fetched_count=0, issue=issue),),
    )
    failed_again = service.get_health(subscription["id"])

    assert failed_again["status"] == "degraded"
    assert failed_again["consecutive_failures"] == 1
    assert failed_again["last_success_at"] == ATTEMPT_2
    assert failed_again["last_failure_at"] == ATTEMPT_3


def test_same_job_outcome_is_idempotent(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    job = _job(store, workspace, owner, source_id, subscription["id"])
    issue = RunIssue("fetch", "TimeoutError", "timed out", True)
    outcome = _outcome(
        source_id,
        subscription["id"],
        status="failed",
        fetched_count=0,
        issue=issue,
    )

    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(outcome,),
    )
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at=ATTEMPT_2,
        outcomes=(outcome,),
    )
    health = service.get_health(subscription["id"])

    assert health["status"] == "degraded"
    assert health["consecutive_failures"] == 1
    assert health["last_attempt_at"] == ATTEMPT_1
    assert health["last_failure_at"] == ATTEMPT_1


def test_replaying_older_job_after_newer_job_is_still_idempotent(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    first_job = _job(store, workspace, owner, source_id, subscription["id"])
    second_job = _job(store, workspace, owner, source_id, subscription["id"])
    issue = RunIssue("fetch", "TimeoutError", "timed out", True)
    outcome = _outcome(
        source_id,
        subscription["id"],
        status="failed",
        fetched_count=0,
        issue=issue,
    )

    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=first_job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(outcome,),
    )
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=second_job["id"],
        attempted_at=ATTEMPT_2,
        outcomes=(outcome,),
    )
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=first_job["id"],
        attempted_at=ATTEMPT_3,
        outcomes=(outcome,),
    )
    health = service.get_health(subscription["id"])

    assert health["status"] == "failing"
    assert health["consecutive_failures"] == 2
    assert health["last_attempt_at"] == ATTEMPT_2
    assert health["last_failure_at"] == ATTEMPT_2
    assert health["last_job_id"] == second_job["id"]


def test_issue_message_is_single_line_bounded_and_redacted(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    job = _job(store, workspace, owner, source_id, subscription["id"])
    raw_message = (
        "failed https://alice:url-pass@example.com/path?token=url-secret\n"
        "Bearer bearer-secret token=token-secret api_key=api-secret "
        "password=password-secret secret=secret-value claim_token=claim-secret "
        "payload={'api_key':'payload-secret'} config={'password':'config-secret'} "
        "stack=Traceback-private " + ("x" * 300)
    )

    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(
            _outcome(
                source_id,
                subscription["id"],
                status="failed",
                fetched_count=0,
                issue=RunIssue("fetch", "UnsafeError", raw_message, False),
            ),
        ),
    )
    stored = service.get_health(subscription["id"])["last_issue_message"]

    assert "\n" not in stored and "\r" not in stored
    assert len(stored) <= 240
    assert "https://example.com/path" in stored
    for secret in (
        "alice",
        "url-pass",
        "url-secret",
        "bearer-secret",
        "token-secret",
        "api-secret",
        "password-secret",
        "secret-value",
        "claim-secret",
        "payload-secret",
        "config-secret",
        "Traceback-private",
    ):
        assert secret not in stored


@pytest.mark.parametrize(
    ("raw_message", "secret"),
    [
        ("request failed sk-proj-example1234567890", "sk-proj-example1234567890"),
        ("github rejected ghp_example1234567890", "ghp_example1234567890"),
        ("slack rejected xoxb-example1234567890", "xoxb-example1234567890"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("token token-value-123456", "token-value-123456"),
        ("api key api-value-123456", "api-value-123456"),
        ("password password-value-123456", "password-value-123456"),
        ("secret secret-value-123456", "secret-value-123456"),
    ],
)
def test_issue_sanitizer_redacts_bare_secret_shapes_and_whitespace_values(
    raw_message, secret
):
    from src.services.source_health import sanitize_issue_message

    sanitized = sanitize_issue_message(raw_message)

    assert secret not in sanitized
    assert "[REDACTED]" in sanitized


@pytest.mark.parametrize(
    ("raw_message", "leaked_values"),
    [
        (
            "fetch failed payload={'headers': {'Authorization': 'Basic dXNlcjpwYXNz'}, "
            "'tenant': 'private-tenant'} after parse",
            ("dXNlcjpwYXNz", "private-tenant", "after parse"),
        ),
        (
            "invalid config={'auth': {'api_key': 'nested-api-secret'}, 'user': 'alice'} tail",
            ("nested-api-secret", "alice", "tail"),
        ),
        (
            "stack=Traceback in /srv/private/app.py line 99 next frame secret-data",
            ("/srv/private/app.py", "line 99", "secret-data"),
        ),
        (
            "Traceback in /srv/private/worker.py with password secret-tail",
            ("/srv/private/worker.py", "secret-tail"),
        ),
        (
            "source_payload={'nested': {'tenant': 'tenant-private-one'}} trailing-one",
            ("tenant-private-one", "trailing-one"),
        ),
        (
            "source_config={'nested': {'tenant': 'tenant-private-two'}} trailing-two",
            ("tenant-private-two", "trailing-two"),
        ),
        (
            "payload_json={'nested': {'tenant': 'tenant-private-three'}} trailing-three",
            ("tenant-private-three", "trailing-three"),
        ),
        (
            "config_json={'nested': {'tenant': 'tenant-private-four'}} trailing-four",
            ("tenant-private-four", "trailing-four"),
        ),
        (
            "stack_trace=File /srv/private/worker.py line 5 private-tail-value",
            ("/srv/private/worker.py", "line 5", "private-tail-value"),
        ),
        (
            "raw_payload={'nested': {'tenant': 'tenant-private-five'}} trailing-five",
            ("tenant-private-five", "trailing-five"),
        ),
        (
            "source-config={'nested': {'tenant': 'tenant-private-six'}} trailing-six",
            ("tenant-private-six", "trailing-six"),
        ),
    ],
)
def test_issue_sanitizer_redacts_entire_payload_config_and_stack_tail(
    raw_message, leaked_values
):
    from src.services.source_health import sanitize_issue_message

    sanitized = sanitize_issue_message(raw_message)

    assert sanitized.endswith("[REDACTED]")
    for leaked in leaked_values:
        assert leaked not in sanitized


def test_ownership_mismatch_rolls_back_all_outcomes(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    other = store.create_user(
        workspace_id=workspace["id"],
        username="other",
        password="other-password",
        role="member",
    )
    other_source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=other["id"],
        source_type="rss",
        display_name="Other Feed",
        config={"url": "https://example.com/other.xml"},
    )
    other_subscription = store.create_subscription(
        user_id=other["id"], source_id=other_source_id
    )
    job = _job(store, workspace, owner, source_id, subscription["id"])

    with pytest.raises(PermissionError, match="ownership"):
        service.apply_outcomes(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=job["id"],
            attempted_at=ATTEMPT_1,
            outcomes=(
                _outcome(source_id, subscription["id"]),
                _outcome(other_source_id, other_subscription["id"]),
            ),
        )

    assert service.get_health(subscription["id"]) is None
    assert service.get_health(other_subscription["id"]) is None


def test_nonexistent_subscription_id_is_ownership_failure_and_rolls_back(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    job = _job(store, workspace, owner, source_id, subscription["id"])

    with pytest.raises(PermissionError, match="ownership"):
        service.apply_outcomes(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=job["id"],
            attempted_at=ATTEMPT_1,
            outcomes=(
                _outcome(source_id, subscription["id"]),
                _outcome(source_id, "sub_missing"),
            ),
        )

    assert service.get_health(subscription["id"]) is None
    assert store.connect().execute("SELECT COUNT(*) FROM user_source_health").fetchone()[0] == 0


def test_cross_user_job_is_rejected_before_health_write(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    other = store.create_user(
        workspace_id=workspace["id"],
        username="cross-job-user",
        password="other-password",
        role="member",
    )
    other_subscription = store.create_subscription(user_id=other["id"], source_id=source_id)
    other_job = _job(store, workspace, other, source_id, other_subscription["id"])
    service = _service(store)

    with pytest.raises(PermissionError, match="job scope"):
        service.apply_outcomes(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=other_job["id"],
            attempted_at=ATTEMPT_1,
            outcomes=(_outcome(source_id, subscription["id"]),),
        )

    assert service.get_health(subscription["id"]) is None
    assert service.get_health(other_subscription["id"]) is None


def test_source_test_job_cannot_write_health(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    source_test_job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_test",
        payload={},
    )
    service = _service(store)

    with pytest.raises(PermissionError, match="job scope"):
        service.apply_outcomes(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=source_test_job["id"],
            attempted_at=ATTEMPT_1,
            outcomes=(_outcome(source_id, subscription["id"]),),
        )

    assert service.get_health(subscription["id"]) is None


def test_source_fetch_wrong_target_rolls_back_entire_outcome_batch(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    other_source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Wrong Target Feed",
        config={"url": "https://example.com/wrong-target.xml"},
    )
    other_subscription = store.create_subscription(
        user_id=owner["id"], source_id=other_source_id
    )
    job = _job(store, workspace, owner, source_id, subscription["id"])
    service = _service(store)

    with pytest.raises(PermissionError, match="job scope"):
        service.apply_outcomes(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=job["id"],
            attempted_at=ATTEMPT_1,
            outcomes=(
                _outcome(source_id, subscription["id"]),
                _outcome(other_source_id, other_subscription["id"]),
            ),
        )

    assert service.get_health(subscription["id"]) is None
    assert service.get_health(other_subscription["id"]) is None
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications"
    ).fetchone()[0] == 0


def test_disabling_subscription_retains_health_and_unsubscribe_cascades(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    job = _job(store, workspace, owner, source_id, subscription["id"])
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(_outcome(source_id, subscription["id"]),),
    )

    store.update_subscription(subscription["id"], enabled=False)
    assert service.get_health(subscription["id"])["status"] == "healthy"

    assert store.delete_subscription(subscription["id"], user_id=owner["id"]) is True
    assert service.get_health(subscription["id"]) is None


def test_two_users_subscribed_to_same_public_source_keep_health_and_jobs_isolated(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, owner_subscription = _context(tmp_path, monkeypatch)
    other = store.create_user(
        workspace_id=workspace["id"],
        username="shared-source-user",
        password="other-password",
        role="member",
    )
    other_subscription = store.create_subscription(user_id=other["id"], source_id=source_id)
    owner_job = _job(store, workspace, owner, source_id, owner_subscription["id"])
    other_job = _job(store, workspace, other, source_id, other_subscription["id"])
    service = _service(store)

    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=owner_job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(_outcome(source_id, owner_subscription["id"], fetched_count=2),),
    )
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=other["id"],
        job_id=other_job["id"],
        attempted_at=ATTEMPT_2,
        outcomes=(
            _outcome(
                source_id,
                other_subscription["id"],
                status="failed",
                fetched_count=0,
                issue=RunIssue("fetch", "TimeoutError", "other timed out", True),
            ),
        ),
    )

    owner_health = service.get_health(owner_subscription["id"])
    other_health = service.get_health(other_subscription["id"])
    assert owner_health["user_id"] == owner["id"]
    assert owner_health["status"] == "healthy"
    assert owner_health["last_job_id"] == owner_job["id"]
    assert other_health["user_id"] == other["id"]
    assert other_health["status"] == "degraded"
    assert other_health["last_job_id"] == other_job["id"]


def test_health_application_ledger_cascades_on_job_prune_and_unsubscribe(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _context(tmp_path, monkeypatch)
    service = _service(store)
    queue = JobQueue(store)
    first_job = _job(store, workspace, owner, source_id, subscription["id"])
    first_claim = queue.claim_next_job(worker_id="health-ledger-worker", lease_seconds=60)
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=first_job["id"],
        attempted_at=ATTEMPT_1,
        outcomes=(_outcome(source_id, subscription["id"]),),
        commit=False,
    )
    queue.complete_job(
        first_job["id"],
        status="succeeded",
        result={"ok": True},
        worker_id="health-ledger-worker",
        claim_token=first_claim["claim_token"],
    )
    store.connect().execute(
        "UPDATE fetch_jobs SET expires_at = ? WHERE id = ?",
        ("2026-07-10T00:00:00+00:00", first_job["id"]),
    )
    store.connect().commit()

    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (first_job["id"],),
    ).fetchone()[0] == 1
    assert queue.prune_terminal_jobs(
        datetime.fromisoformat("2026-07-11T00:00:00+00:00")
    ) == 1
    assert service.get_health(subscription["id"])["last_job_id"] is None
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE job_id = ?",
        (first_job["id"],),
    ).fetchone()[0] == 0

    second_job = _job(store, workspace, owner, source_id, subscription["id"])
    service.apply_outcomes(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=second_job["id"],
        attempted_at=ATTEMPT_2,
        outcomes=(_outcome(source_id, subscription["id"]),),
    )
    assert store.delete_subscription(subscription["id"], user_id=owner["id"]) is True
    assert service.get_health(subscription["id"]) is None
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health_applications WHERE subscription_id = ?",
        (subscription["id"],),
    ).fetchone()[0] == 0
    assert store.connect().execute("PRAGMA foreign_key_check").fetchall() == []
