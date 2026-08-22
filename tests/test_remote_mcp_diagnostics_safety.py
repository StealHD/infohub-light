from __future__ import annotations

from tests.remote_mcp_diagnostics_test_support import *  # noqa: F403

@pytest.mark.parametrize(
    "business_name",
    (
        "Turkey Keynote",
        "Monkey Business",
        "Connection String Theory",
        "Basic Engineering News",
        "Bearer Market Report",
    ),
)
@pytest.mark.parametrize("diagnostic_kind", ("source", "job"))
def test_target_name_preserves_ordinary_business_names(
    context,
    diagnostic_kind,
    business_name,
):
    context["store"].update_source(
        context["source_id"], display_name=business_name
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

    assert result["target"]["name"] == business_name


@pytest.mark.parametrize(
    "business_code",
    (
        "StorageKeyRotation",
        "MonkeyBusiness",
        "HockeyScore",
        "ConnectionStringTheory",
    ),
)
def test_job_code_preserves_ordinary_business_identifiers(context, business_code):
    job = _create_job(
        context,
        source=False,
        error_code=business_code,
        error_message="unmapped failure",
    )

    result = context["diagnostics"].diagnose_job(
        actor=context["actor"], job_id=job["id"]
    )

    assert result["cause"]["code"] == business_code
    assert {"kind": "error_code", "value": business_code} in result["evidence"]


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
