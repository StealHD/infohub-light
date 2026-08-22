from __future__ import annotations

from tests.remote_mcp_subscription_service_test_support import *  # noqa: F403

@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("revoke", "unauthorized"),
        ("disable", "unauthorized"),
        ("role", "forbidden"),
        ("scopes", "unauthorized"),
    ],
)
def test_prepare_final_guard_is_atomic_with_principal_changes(
    context, mutation, expected_code
):
    actor = _actor(context, "member")
    plan = context["mutations"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": f"Race {mutation}",
            "config": {"url": f"https://example.com/race-{mutation}.xml"},
        },
        subscription={},
        schedule=None,
    )
    competing_store = ServiceStore(
        context["store"].data_dir,
        db_path=context["store"].db_path,
    )
    mutated = [False]

    def mutate() -> None:
        conn = competing_store.connect()
        if mutation == "revoke":
            conn.execute(
                "UPDATE agent_delegations SET revoked_at = ? WHERE id = ?",
                (NOW.isoformat(), actor.delegation_id),
            )
        elif mutation == "disable":
            conn.execute(
                "UPDATE users SET enabled = 0 WHERE id = ?", (actor.user_id,)
            )
        elif mutation == "role":
            conn.execute(
                "UPDATE users SET role = 'viewer' WHERE id = ?", (actor.user_id,)
            )
        else:
            conn.execute(
                "UPDATE agent_delegations SET scopes_json = ? WHERE id = ?",
                ('["inteliscope:read"]', actor.delegation_id),
            )
        conn.commit()

    def clock_after_preflight() -> datetime:
        if not mutated[0]:
            mutated[0] = True
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(mutate).result(timeout=5)
        return NOW

    context["proposals"].now = clock_after_preflight
    try:
        with pytest.raises(AgentProposalError) as error:
            context["proposals"].prepare(actor, plan)
    finally:
        competing_store.close()

    assert mutated == [True]
    assert error.value.code == expected_code
    assert error.value.code != "invalid_plan_snapshot"
    assert _proposal_count(context) == 0


def test_prepare_final_guard_rereads_dynamic_write_flag_before_insert(context):
    actor = _actor(context, "member")
    plan = context["mutations"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "Flag race",
            "config": {"url": "https://example.com/flag-race.xml"},
        },
        subscription={},
        schedule=None,
    )

    def disable_after_preflight() -> datetime:
        context["writes_enabled"][0] = False
        return NOW

    context["proposals"].now = disable_after_preflight
    with pytest.raises(AgentProposalError) as error:
        context["proposals"].prepare(actor, plan)

    assert error.value.code == "subscription_writes_disabled"
    assert _proposal_count(context) == 0


def test_prepare_create_persists_only_complete_v2_plan_and_hash(context):
    before = _business_dump(context)

    result = context["service"].prepare_create_subscription(
        actor=_actor(context, "member"),
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "Example",
            "config": {"url": "https://example.com/feed.xml"},
        },
        subscription={"priority": 10},
        schedule=None,
    )

    row = context["store"].get_agent_change_proposal(result["proposal_id"])
    assert row is not None
    snapshot = row["payload"]["plan_snapshot"]
    assert set(snapshot) == {
        "version",
        "kind",
        "normalized",
        "preview",
        "targets",
        "fingerprints",
    }
    assert snapshot["version"] == 2
    assert row["kind"] == snapshot["kind"] == result["kind"] == "create"
    assert row["preview"] == snapshot["preview"] == result["preview"]
    assert row["fingerprints"] == snapshot["fingerprints"]
    assert row["source_id"] is None
    assert row["subscription_id"] is None
    assert result["confirmation_text"].startswith("确认执行 ")
    assert row["confirmation_hash"] == hashlib.sha256(
        result["confirmation_text"].encode("utf-8")
    ).hexdigest()
    assert result["created_at"] == NOW.isoformat()
    assert result["expires_at"] == (NOW + timedelta(minutes=10)).isoformat()
    assert datetime.fromisoformat(result["expires_at"]) - datetime.fromisoformat(
        result["created_at"]
    ) == timedelta(minutes=10)
    assert result["confirmation_text"] not in repr(row)
    assert "config" not in repr(result["preview"])
    assert set(result["preview"]) >= {"impact", "warnings"}
    assert _business_dump(context) == before


def test_prepare_existing_source_disabled_between_facade_check_and_planner_fails_closed(
    context,
    monkeypatch,
):
    source = _source(context, name="Visibility race")
    actor = _actor(context, "member")
    original_get_source = context["store"].get_source
    reads = 0

    def disable_before_planner_read(source_id):
        nonlocal reads
        reads += 1
        if reads == 2:
            context["store"].update_source(source_id, enabled=False)
        return original_get_source(source_id)

    monkeypatch.setattr(context["store"], "get_source", disable_before_planner_read)

    with pytest.raises(AgentProposalError) as error:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={"mode": "existing", "source_id": source["id"]},
            subscription={},
            schedule=None,
        )

    assert reads == 2
    assert error.value.code == "not_found"
    assert _proposal_count(context) == 0


def test_prepare_reads_write_flag_dynamically_for_existing_write_actor(context):
    actor = _actor(context, "member")
    first = context["service"].prepare_create_subscription(
        actor=actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "One",
            "config": {"url": "https://example.com/one.xml"},
        },
        subscription={},
        schedule=None,
    )
    assert first["kind"] == "create"

    context["writes_enabled"][0] = False
    with pytest.raises(AgentProposalError) as disabled:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Two",
                "config": {"url": "https://example.com/two.xml"},
            },
            subscription={},
            schedule=None,
        )
    assert disabled.value.code == "subscription_writes_disabled"
    assert _proposal_count(context) == 1


def test_prepare_maps_limit_and_sanitizer_failures_without_partial_rows(
    context, monkeypatch
):
    actor = _actor(context, "member")
    values = {
        "source": {
            "mode": "private",
            "type": "rss",
            "display_name": "Example",
            "config": {"url": "https://example.com/feed.xml"},
        },
        "subscription": {},
        "schedule": None,
    }
    for _index in range(10):
        context["service"].prepare_create_subscription(actor=actor, **values)
    with pytest.raises(AgentProposalError) as limited:
        context["service"].prepare_create_subscription(actor=actor, **values)
    assert limited.value.code == "proposal_limit"
    assert _proposal_count(context) == 10

    context["store"].connect().execute("DELETE FROM agent_change_proposals")
    context["store"].connect().commit()
    original = context["store"].create_agent_change_proposal

    def rejected(**kwargs):
        kwargs["payload"] = {"secret_env": "NEVER_STORE"}
        return original(**kwargs)

    monkeypatch.setattr(context["store"], "create_agent_change_proposal", rejected)
    with pytest.raises(AgentProposalError) as unsafe:
        context["service"].prepare_create_subscription(actor=actor, **values)
    assert unsafe.value.code == "invalid_plan_snapshot"
    assert "NEVER_STORE" not in str(unsafe.value)
    assert _proposal_count(context) == 0


def test_prepare_unknown_and_cross_user_ids_are_not_found_and_delete_is_explicit(context):
    source = _source(context, name="Other private", scope="private", owner="other")
    subscription = context["store"].create_subscription(
        user_id=context["other"]["id"], source_id=source["id"]
    )
    actor = _actor(context, "member")

    for operation in (
        lambda: context["service"].prepare_create_subscription(
            actor=actor,
            source={"mode": "existing", "source_id": source["id"]},
            subscription={},
            schedule=None,
        ),
        lambda: context["service"].prepare_update_subscription(
            actor=actor,
            subscription_id=subscription["id"],
            source_updates=None,
            subscription_updates={"priority": 1},
            schedule_updates=None,
        ),
        lambda: context["service"].prepare_delete_subscription(
            actor=actor,
            subscription_id="sub_unknown",
            source_disposition="keep",
        ),
    ):
        with pytest.raises(AgentProposalError) as error:
            operation()
        assert error.value.code == "not_found"

    own_source = _source(context, name="Own private", scope="private", owner="member")
    own_subscription = context["store"].create_subscription(
        user_id=context["member"]["id"], source_id=own_source["id"]
    )
    with pytest.raises(AgentProposalError) as missing_disposition:
        context["service"].prepare_delete_subscription(
            actor=actor, subscription_id=own_subscription["id"]
        )
    assert missing_disposition.value.code == "invalid_request"
    assert _proposal_count(context) == 0


def test_managed_apify_can_only_use_an_existing_visible_source(context):
    visible = _source(
        context,
        name="Managed X",
        source_type="apify_social",
        config={"platform": "x", "kind": "profile", "target": "openai"},
        secret_env="VISIBLE_TOKEN",
    )
    actor = _actor(context, "member")

    prepared = context["service"].prepare_create_subscription(
        actor=actor,
        source={"mode": "existing", "source_id": visible["id"]},
        subscription={},
        schedule=None,
    )
    assert prepared["preview"]["source"]["type"] == "apify_social"

    with pytest.raises(AgentProposalError) as private:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={
                "mode": "private",
                "type": "apify",
                "display_name": "No private managed source",
                "config": {"platform": "x", "kind": "profile", "target": "openai"},
            },
            subscription={},
            schedule=None,
        )
    assert private.value.code == "source_requires_web_setup"
    assert _proposal_count(context) == 1


def test_apply_requires_exact_phrase_is_single_use_and_stores_same_safe_result(
    context,
):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="lifecycle", actor=actor)
    before = _business_dump(context)

    with pytest.raises(AgentProposalError) as mismatch:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text="确认",
        )
    assert mismatch.value.code == "confirmation_mismatch"
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"
    assert _business_dump(context) == before

    applied = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )
    _assert_applied_summary_and_consumed(
        context,
        actor=actor,
        prepared=prepared,
        applied=applied,
        expected_result_keys=_CREATE_UPDATE_RESULT_KEYS,
    )
    serialized = repr(applied).lower()
    for forbidden in (
        "config",
        "workspace_id",
        "user_id",
        "owner_user_id",
        "secret_env",
        "source_key",
        "file_path",
    ):
        assert forbidden not in serialized

def test_apply_hides_absent_cross_user_and_cross_delegation_ids(context):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="isolation", actor=actor)
    second, _token = context["store"].create_agent_delegation(
        workspace_id=actor.workspace_id,
        user_id=actor.user_id,
        name="member second write",
        access="subscriptions_write",
    )
    same_user_other_delegation = DelegatedActor(
        workspace_id=actor.workspace_id,
        user_id=actor.user_id,
        role=actor.role,
        delegation_id=second["id"],
        scopes=tuple(second["scopes"]),
    )

    for caller, proposal_id in (
        (actor, "agp_absent"),
        (_actor(context, "other"), prepared["proposal_id"]),
        (same_user_other_delegation, prepared["proposal_id"]),
    ):
        with pytest.raises(AgentProposalError) as error:
            context["service"].apply_subscription_change(
                actor=caller,
                proposal_id=proposal_id,
                confirmation_text=prepared["confirmation_text"],
            )
        assert error.value.code == "not_found"

    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"


def test_apply_uses_store_clock_and_exact_ten_minute_boundary_expires_atomically(
    context,
):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="boundary", actor=actor)
    before = _business_dump(context)
    context["proposal_clock"][0] = NOW + timedelta(minutes=10)

    with pytest.raises(AgentProposalError) as expired:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert expired.value.code == "proposal_expired"
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "expired"
    assert _business_dump(context) == before


def test_apply_time_crossing_rolls_back_business_then_commits_only_expiry(
    context, monkeypatch
):
    actor = _actor(context, "member")
    prepared = _prepare_private(context, suffix="time-crossing", actor=actor)
    before = _business_dump(context)
    times = iter(
        [
            NOW + timedelta(minutes=9, seconds=59),
            NOW + timedelta(minutes=10),
            NOW + timedelta(minutes=10),
            NOW + timedelta(minutes=10),
        ]
    )
    monkeypatch.setattr(service_store_module, "_proposal_utc_now", lambda: next(times))

    with pytest.raises(AgentProposalError) as expired:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert expired.value.code == "proposal_expired"
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "expired"
    assert _business_dump(context) == before


def test_apply_runs_cleanup_only_after_success_and_discards_rejections(
    context, monkeypatch
):
    events: list[str] = []

    class CleanupSpy:
        def run(self) -> int:
            events.append("run")
            return 0

        def discard(self) -> None:
            events.append("discard")

    monkeypatch.setattr(proposal_service_module, "PostCommitMediaCleanup", CleanupSpy)
    actor = _actor(context, "member")
    mismatch = _prepare_private(context, suffix="cleanup-reject", actor=actor)
    with pytest.raises(AgentProposalError):
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=mismatch["proposal_id"],
            confirmation_text="wrong",
        )
    assert events == ["discard"]

    expired = _prepare_private(context, suffix="cleanup-expired", actor=actor)
    context["proposal_clock"][0] = NOW + timedelta(minutes=10)
    with pytest.raises(AgentProposalError) as expiry_error:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=expired["proposal_id"],
            confirmation_text=expired["confirmation_text"],
        )
    assert expiry_error.value.code == "proposal_expired"
    assert events == ["discard", "discard"]

    success = _prepare_private(context, suffix="cleanup-success", actor=actor)
    context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=success["proposal_id"],
        confirmation_text=success["confirmation_text"],
    )
    assert events == ["discard", "discard", "run"]
