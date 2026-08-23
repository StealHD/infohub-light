from __future__ import annotations

from tests.remote_mcp_subscription_service_test_support import *  # noqa: F403

def test_apply_cleanup_failure_is_best_effort_after_committed_success(
    context, monkeypatch, caplog
):
    events: list[str] = []
    sensitive_cleanup_detail = "cleanup-private-path-/secret/cache.png"

    class CleanupSpy:
        def run(self) -> int:
            events.append("run")
            raise RuntimeError(sensitive_cleanup_detail)

        def discard(self) -> None:
            events.append("discard")

    monkeypatch.setattr(proposal_service_module, "PostCommitMediaCleanup", CleanupSpy)
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="cleanup-failure", actor=actor)

    applied = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )

    assert events == ["run"]
    source_id = applied["result"]["source_id"]
    subscription_id = applied["result"]["subscription_id"]
    assert context["store"].get_source(source_id) is not None
    assert context["store"].get_subscription(subscription_id) is not None
    assert context["store"].get_source_schedule(subscription_id) is not None
    assert len(context["store"].list_user_subscriptions(actor.user_id)) == 1
    _assert_applied_summary_and_consumed(
        context,
        actor=actor,
        prepared=prepared,
        applied=applied,
        expected_result_keys=_CREATE_UPDATE_RESULT_KEYS,
    )
    assert events == ["run", "discard"]
    assert sensitive_cleanup_detail not in caplog.text


def test_apply_update_commits_business_result_and_exact_safe_summary(context):
    actor = _actor(context, "member")
    prepared_create = _prepare_private(
        context, suffix="update-success", actor=actor
    )
    created = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared_create["proposal_id"],
        confirmation_text=prepared_create["confirmation_text"],
    )
    source_id = created["result"]["source_id"]
    subscription_id = created["result"]["subscription_id"]
    prepared = context["service"].prepare_update_subscription(
        actor=actor,
        subscription_id=subscription_id,
        source_updates={"display_name": "Applied update"},
        subscription_updates={"override_channel": "AI", "priority": 42},
        schedule_updates={"enabled": True, "interval_minutes": 180},
    )

    applied = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )

    source = context["store"].get_source(source_id)
    subscription = context["store"].get_subscription(subscription_id)
    schedule = context["store"].get_source_schedule(subscription_id)
    assert source["display_name"] == "Applied update"
    assert subscription["override_channel"] == "AI"
    assert subscription["priority"] == 42
    assert schedule["enabled"] is True
    assert schedule["interval_minutes"] == 180
    assert applied["result"] == {
        "action": "updated",
        "source_id": source_id,
        "subscription_id": subscription_id,
        "source_enabled": True,
        "subscription_enabled": True,
        "schedule_enabled": True,
        "schedule_interval_minutes": 180,
    }
    _assert_applied_summary_and_consumed(
        context,
        actor=actor,
        prepared=prepared,
        applied=applied,
        expected_result_keys=_CREATE_UPDATE_RESULT_KEYS,
    )


@pytest.mark.parametrize(
    ("source_disposition", "expected_source_enabled", "expected_source_disabled"),
    [
        # `keep` preserves the private source definition, but the final
        # subscription removal still soft-disables the orphan so it cannot
        # continue polling without an owner.
        pytest.param("keep", False, True, id="keep"),
        pytest.param("disable_private", False, True, id="disable-private"),
    ],
)
def test_apply_delete_commits_each_disposition_and_exact_safe_summary(
    context,
    source_disposition,
    expected_source_enabled,
    expected_source_disabled,
):
    actor = _actor(context, "member")
    prepared_create = _prepare_private(
        context, suffix=f"delete-{source_disposition}", actor=actor
    )
    created = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared_create["proposal_id"],
        confirmation_text=prepared_create["confirmation_text"],
    )
    source_id = created["result"]["source_id"]
    subscription_id = created["result"]["subscription_id"]
    prepared = context["service"].prepare_delete_subscription(
        actor=actor,
        subscription_id=subscription_id,
        source_disposition=source_disposition,
    )

    applied = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )

    assert context["store"].get_subscription(subscription_id) is None
    assert context["store"].get_source_schedule(subscription_id) is None
    assert context["store"].get_source(source_id)["enabled"] is expected_source_enabled
    assert applied["result"] == {
        "action": "deleted",
        "source_id": source_id,
        "subscription_id": subscription_id,
        "source_disabled": expected_source_disabled,
    }
    _assert_applied_summary_and_consumed(
        context,
        actor=actor,
        prepared=prepared,
        applied=applied,
        expected_result_keys=_DELETE_RESULT_KEYS,
    )


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        ("flag", "subscription_writes_disabled"),
        ("revoke", "unauthorized"),
        ("expire_delegation", "unauthorized"),
        ("role", "forbidden"),
        ("scope", "unauthorized"),
    ],
)
def test_apply_reauthenticates_live_flag_scope_role_and_delegation(
    context, change, expected_code
):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix=f"reauth-{change}", actor=actor)
    conn = context["store"].connect()
    if change == "flag":
        context["writes_enabled"][0] = False
    elif change == "revoke":
        conn.execute(
            "UPDATE agent_delegations SET revoked_at = ? WHERE id = ?",
            (NOW.isoformat(), actor.delegation_id),
        )
        conn.commit()
    elif change == "expire_delegation":
        conn.execute(
            "UPDATE agent_delegations SET expires_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), actor.delegation_id),
        )
        conn.commit()
    elif change == "role":
        conn.execute("UPDATE users SET role = 'viewer' WHERE id = ?", (actor.user_id,))
        conn.commit()
    else:
        conn.execute(
            "UPDATE agent_delegations SET scopes_json = ? WHERE id = ?",
            (json.dumps([AGENT_DELEGATION_READ_SCOPE]), actor.delegation_id),
        )
        conn.commit()

    with pytest.raises(AgentProposalError) as error:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert error.value.code == expected_code
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"


def test_apply_rereads_dynamic_flag_inside_immediate_transaction(context):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="flag-race", actor=actor)
    checks = 0

    def enabled_then_disabled() -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    context["proposals"]._writes_enabled_provider = enabled_then_disabled
    with pytest.raises(AgentProposalError) as error:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert checks == 2
    assert error.value.code == "subscription_writes_disabled"
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"


def test_apply_uses_fresh_live_role_instead_of_request_role_snapshot(context):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="fresh-role", actor=actor)
    context["store"].connect().execute(
        "UPDATE users SET role = 'owner' WHERE id = ?", (actor.user_id,)
    )
    context["store"].connect().commit()

    result = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )

    assert result["status"] == "applied"


def test_apply_duplicate_projection_mismatch_is_stale_and_pending(context):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="duplicate", actor=actor)
    before = _business_dump(context)
    conn = context["store"].connect()
    conn.execute(
        "UPDATE agent_change_proposals SET preview_json = ? WHERE id = ?",
        (json.dumps({"action": "tampered"}), prepared["proposal_id"]),
    )
    conn.commit()

    with pytest.raises(AgentProposalError) as error:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert error.value.code == "proposal_stale"
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"
    assert _business_dump(context) == before


def test_apply_target_fingerprint_change_is_stale_without_extra_business_change(
    context,
):
    actor = _actor(context, "member")
    source = _source(context, name="stale-source", scope="private", owner="member")
    subscription = context["store"].create_subscription(
        user_id=actor.user_id, source_id=source["id"]
    )
    prepared = context["service"].prepare_update_subscription(
        actor=actor,
        subscription_id=subscription["id"],
        source_updates=None,
        subscription_updates={"priority": 30},
        schedule_updates=None,
    )
    context["store"].connect().execute(
        "UPDATE user_subscriptions SET priority = 29, updated_at = ? WHERE id = ?",
        ((NOW + timedelta(seconds=1)).isoformat(), subscription["id"]),
    )
    context["store"].connect().commit()
    after_competing_change = _business_dump(context)

    with pytest.raises(AgentProposalError) as error:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert error.value.code == "proposal_stale"
    assert _business_dump(context) == after_competing_change
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"


def test_apply_rechecks_source_key_and_quota_and_rolls_back(context, monkeypatch):
    actor = _actor(context, "member")
    collision = _prepare_private(context, suffix="collision", actor=actor)
    context["store"].create_source(
        workspace_id=actor.workspace_id,
        scope="private",
        owner_user_id=actor.user_id,
        source_type="rss",
        display_name="Competing collision",
        config={"url": "https://example.com/collision.xml"},
        source_key="rss:https://example.com/collision.xml",
        enabled=True,
    )
    after_collision = _business_dump(context)
    with pytest.raises(AgentProposalError) as conflict:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=collision["proposal_id"],
            confirmation_text=collision["confirmation_text"],
        )
    assert conflict.value.code == "source_key_conflict"
    assert _business_dump(context) == after_collision

    quota = _prepare_private(context, suffix="quota", actor=actor)
    before_quota = _business_dump(context)
    monkeypatch.setattr(
        context["mutations"].quota,
        "ensure_source_allowed",
        Mock(side_effect=QuotaExceeded("enabled source quota exceeded")),
    )
    with pytest.raises(AgentProposalError) as limited:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=quota["proposal_id"],
            confirmation_text=quota["confirmation_text"],
        )
    assert limited.value.code == "quota_exceeded"
    assert _business_dump(context) == before_quota
    assert context["store"].get_agent_change_proposal(quota["proposal_id"])[
        "status"
    ] == "pending"


@pytest.mark.parametrize("failure_point", ["mutation", "summary_store"])
def test_apply_rolls_back_business_and_keeps_pending_on_internal_failure(
    context, monkeypatch, failure_point
):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix=f"rollback-{failure_point}", actor=actor)
    before = _business_dump(context)
    if failure_point == "mutation":
        original = context["mutations"].apply_plan

        def fail_after_mutation(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("mutation failed after writes")

        monkeypatch.setattr(context["mutations"], "apply_plan", fail_after_mutation)
    else:
        monkeypatch.setattr(
            context["store"],
            "apply_agent_change_proposal",
            Mock(side_effect=RuntimeError("summary store failed")),
        )

    with pytest.raises(RuntimeError):
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert _business_dump(context) == before
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"


def test_apply_rejects_caller_owned_transaction(context):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="outer-transaction", actor=actor)
    before = _business_dump(context)
    conn = context["store"].connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(AgentProposalError) as error:
            context["service"].apply_subscription_change(
                actor=actor,
                proposal_id=prepared["proposal_id"],
                confirmation_text=prepared["confirmation_text"],
            )
        assert error.value.code == "invalid_transaction"
    finally:
        conn.rollback()
    assert _business_dump(context) == before


def test_concurrent_apply_has_exactly_one_business_write(context):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="concurrent", actor=actor)

    def apply_or_code(_index: int) -> str:
        try:
            with context["store"].request_connection_scope():
                result = context["service"].apply_subscription_change(
                    actor=actor,
                    proposal_id=prepared["proposal_id"],
                    confirmation_text=prepared["confirmation_text"],
                )
            return result["status"]
        except AgentProposalError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply_or_code, range(2)))

    assert results.count("applied") == 1
    assert results.count("proposal_consumed") == 1
    source = context["store"].get_source_by_key(
        workspace_id=actor.workspace_id,
        source_key="rss:https://example.com/concurrent.xml",
    )
    assert source is not None
    assert len(context["store"].list_user_subscriptions(actor.user_id)) == 1
