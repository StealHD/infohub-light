from __future__ import annotations

from tests.remote_mcp_diagnostics_test_support import *  # noqa: F403

def test_source_same_id_retry_same_failure_code_marks_old_health_historical(
    context,
):
    job = _finalize_failed_source_attempt_with_health(context)
    queue = JobQueue(context["store"])
    retried = queue.retry_job(job["id"], user_id=context["owner"]["id"])
    assert retried["id"] == job["id"] and retried["status"] == "queued"
    claimed = queue.claim_next_job(worker_id="diagnostic-attempt-two-same-failure")
    assert claimed is not None and claimed["id"] == job["id"]
    queue.fail_or_retry_job(
        job["id"],
        error_code="TimeoutError",
        error_message="connection timed out again",
        retryable=False,
        worker_id=claimed["worker_id"],
        claim_token=claimed["claim_token"],
    )

    result = context["diagnostics"].diagnose_source(
        actor=context["actor"],
        subscription_id=context["subscription"]["id"],
    )

    assert result["related_job_id"] == job["id"]
    assert result["status"] == "failed"
    assert result["cause"]["category"] == "network_timeout"
    assert result["cause"]["code"] == "TimeoutError"
    assert {
        "kind": "health_evidence_role",
        "value": "historical",
    } in result["evidence"]


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
@pytest.mark.parametrize(
    "credential_label",
    (
        "AWS_ACCESS_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS_JSON",
        "Bearer:hidden",
    ),
)
@pytest.mark.parametrize(
    "diagnostic_kind,fallback_name",
    (("source", "来源"), ("job", "来源抓取任务")),
)
def test_target_name_classifies_the_complete_scalar_before_truncation(
    context,
    diagnostic_kind,
    fallback_name,
    credential_label,
):
    complete_name = f"{'public-prefix-' * 12}{credential_label}"
    context["store"].update_source(
        context["source_id"], display_name=complete_name
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
