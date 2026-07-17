from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

import pytest

import src.services.agent_change_proposal as proposal_service_module
import src.storage.service_store as service_store_module
from src.mcp.remote_subscription_service import RemoteMCPSubscriptionService
from src.services.agent_change_proposal import (
    AgentChangeProposalService,
    AgentProposalError,
    DelegatedActor,
)
from src.services.source_type_registry import SourceConfigError
from src.services.quota import QuotaExceeded
from src.services.subscription_mutation import SubscriptionMutationService
from src.storage.service_store import (
    AGENT_DELEGATION_READ_SCOPE,
    AGENT_DELEGATION_WRITE_SCOPE,
    ServiceStore,
)


NOW = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)


def _actor(context: dict[str, Any], name: str) -> DelegatedActor:
    user = context[name]
    delegation = context[f"{name}_write"]
    return DelegatedActor(
        workspace_id=context["workspace"]["id"],
        user_id=user["id"],
        role=user["role"],
        delegation_id=delegation["id"],
        scopes=tuple(delegation["scopes"]),
    )


def _read_actor(context: dict[str, Any]) -> DelegatedActor:
    user = context["member"]
    delegation = context["member_read"]
    return DelegatedActor(
        workspace_id=context["workspace"]["id"],
        user_id=user["id"],
        role=user["role"],
        delegation_id=delegation["id"],
        scopes=tuple(delegation["scopes"]),
    )


def _source(
    context: dict[str, Any],
    *,
    name: str,
    source_type: str = "rss",
    scope: str = "workspace",
    owner: str = "owner",
    config: dict[str, Any] | None = None,
    secret_env: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    config = config or {"url": f"https://example.com/{name}.xml"}
    source_id = context["store"].create_source(
        workspace_id=context["workspace"]["id"],
        scope=scope,
        owner_user_id=context[owner]["id"],
        source_type=source_type,
        display_name=name,
        config=config,
        source_key=f"{source_type}:{name}",
        secret_env=secret_env,
        enabled=enabled,
    )
    source = context["store"].get_source(source_id)
    assert source is not None
    return source


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    proposal_clock = [NOW]
    monkeypatch.setattr(
        service_store_module,
        "_proposal_utc_now",
        lambda: proposal_clock[0],
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    other = store.create_user(
        workspace_id=workspace["id"],
        username="other",
        password="other-password",
        role="member",
    )
    viewer = store.create_user(
        workspace_id=workspace["id"],
        username="viewer",
        password="viewer-password",
        role="viewer",
    )

    def delegation(user, access):
        row, _token = store.create_agent_delegation(
            workspace_id=workspace["id"],
            user_id=user["id"],
            name=f"{user['username']} {access}",
            access=access,
        )
        return row

    writes_enabled = [True]
    secret_calls: list[str] = []

    def secret_is_set(name: str) -> bool:
        secret_calls.append(name)
        return name == "VISIBLE_TOKEN"

    mutations = SubscriptionMutationService(store)
    proposals = AgentChangeProposalService(
        store,
        writes_enabled=lambda: writes_enabled[0],
        now=lambda: NOW - timedelta(days=30),
    )
    service = RemoteMCPSubscriptionService(
        store=store,
        mutations=mutations,
        proposals=proposals,
        secret_is_set=secret_is_set,
    )
    return {
        "store": store,
        "workspace": workspace,
        "owner": owner,
        "member": member,
        "other": other,
        "viewer": viewer,
        "member_write": delegation(member, "subscriptions_write"),
        "member_read": delegation(member, "read"),
        "other_write": delegation(other, "subscriptions_write"),
        # The store deliberately permits constructing this row; the Web API is
        # the creation guard and proposal prepare must still reject its live role.
        "viewer_write": delegation(viewer, "subscriptions_write"),
        "writes_enabled": writes_enabled,
        "secret_calls": secret_calls,
        "mutations": mutations,
        "proposals": proposals,
        "proposal_clock": proposal_clock,
        "service": service,
    }


def _proposal_count(context: dict[str, Any]) -> int:
    return int(
        context["store"]
        .connect()
        .execute("SELECT COUNT(*) FROM agent_change_proposals")
        .fetchone()[0]
    )


def _business_dump(context: dict[str, Any]) -> tuple[list[tuple], ...]:
    conn = context["store"].connect()
    return tuple(
        [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
        for table in (
            "source_catalog",
            "user_subscriptions",
            "user_source_schedules",
        )
    )


def _prepare_private(
    context: dict[str, Any],
    *,
    suffix: str,
    actor: DelegatedActor | None = None,
) -> dict[str, Any]:
    return context["service"].prepare_create_subscription(
        actor=actor or _actor(context, "member"),
        source={
            "mode": "private",
            "type": "rss",
            "display_name": f"Apply {suffix}",
            "config": {"url": f"https://example.com/{suffix}.xml"},
        },
        subscription={"priority": 17},
        schedule={"enabled": False, "interval_minutes": 60},
    )


def test_setup_guide_is_safe_and_does_not_require_write_scope(context):
    result = context["service"].get_source_setup_guide(
        actor=_read_actor(context), source_type="rss", locale="en"
    )

    assert result["source_type"]["type"] == "rss"
    serialized = repr(result).lower()
    assert "secret_env" not in serialized
    assert "token_env" not in serialized


def test_available_sources_are_current_user_scoped_and_secret_safe(context):
    public = _source(
        context,
        name="Public",
        scope="public",
        secret_env="VISIBLE_TOKEN",
    )
    shared = _source(context, name="Shared", scope="workspace")
    mine = _source(context, name="Mine", scope="private", owner="member")
    _source(
        context,
        name="Other private",
        scope="private",
        owner="other",
        secret_env="OTHER_TOKEN",
    )
    _source(
        context,
        name="Disabled",
        scope="workspace",
        secret_env="DISABLED_TOKEN",
        enabled=False,
    )

    result = context["service"].list_available_sources(
        actor=_read_actor(context), source_type=None, unsubscribed_only=False
    )

    assert {item["id"] for item in result["items"]} == {
        public["id"],
        shared["id"],
        mine["id"],
    }
    assert all(
        set(item)
        == {
            "id",
            "name",
            "type",
            "scope",
            "enabled",
            "default_channel",
            "default_topics",
            "secret_configured",
            "subscribed",
        }
        for item in result["items"]
    )
    assert next(item for item in result["items"] if item["id"] == public["id"])[
        "secret_configured"
    ] is True
    assert context["secret_calls"] == ["VISIBLE_TOKEN"]
    serialized = repr(result)
    assert "secret_env" not in serialized
    assert "owner_user_id" not in serialized
    assert "'config':" not in serialized
    assert "OTHER_TOKEN" not in serialized


def test_available_source_filter_uses_explicit_public_type_matrix(context):
    rows = {
        "rss": _source(
            context,
            name="Z ordinary RSS",
            source_type="rss",
            config={"url": "https://example.com/feed.xml"},
        ),
        "youtube": _source(
            context,
            name="YouTube RSS",
            source_type="rss",
            config={
                "url": (
                    "https://www.youtube.com/feeds/videos.xml?"
                    "channel_id=UCabcdefghijklmnopqrstuv"
                )
            },
        ),
        "github_release": _source(
            context,
            name="Z GitHub release",
            source_type="github_release",
            config={"owner": "openai", "repo": "codex"},
        ),
        "github_user": _source(
            context,
            name="A GitHub user",
            source_type="github_user",
            config={"username": "openai"},
        ),
        "reddit_subreddit": _source(
            context,
            name="Z Reddit subreddit",
            source_type="reddit_subreddit",
            config={"subreddit": "LocalLLaMA"},
        ),
        "reddit_user": _source(
            context,
            name="A Reddit user",
            source_type="reddit_user",
            config={"username": "spez"},
        ),
        "telegram": _source(
            context,
            name="Telegram",
            source_type="telegram_channel",
            config={"channel": "durov"},
        ),
        "twitter": _source(
            context,
            name="Twitter",
            source_type="apify_social",
            config={"platform": "x", "kind": "profile", "target": "openai"},
        ),
        "apify": _source(
            context,
            name="Generic Apify",
            source_type="apify_social",
            config={
                "platform": "instagram",
                "kind": "profile",
                "target": "openai",
            },
        ),
        "hackernews": _source(
            context,
            name="Hacker News",
            source_type="hackernews",
            config={"fetch_top_stories": 30, "min_score": 100},
        ),
    }
    expected = {
        # RSS and Website intentionally share the same non-YouTube RSS set:
        # persisted catalog rows have no discriminator that can separate them.
        "rss": [rows["rss"]["id"]],
        "website": [rows["rss"]["id"]],
        "youtube": [rows["youtube"]["id"]],
        "github": [rows["github_user"]["id"], rows["github_release"]["id"]],
        "reddit": [rows["reddit_user"]["id"], rows["reddit_subreddit"]["id"]],
        "telegram": [rows["telegram"]["id"]],
        "twitter": [rows["twitter"]["id"]],
        "apify": [rows["apify"]["id"]],
    }

    for source_type, expected_ids in expected.items():
        first = context["service"].list_available_sources(
            actor=_read_actor(context),
            source_type=source_type,
            unsubscribed_only=False,
        )
        second = context["service"].list_available_sources(
            actor=_read_actor(context),
            source_type=source_type,
            unsubscribed_only=False,
        )
        result_ids = [item["id"] for item in first["items"]]
        assert result_ids == expected_ids
        assert result_ids == [item["id"] for item in second["items"]]
        assert len(result_ids) == len(set(result_ids))
        assert rows["hackernews"]["id"] not in result_ids


@pytest.mark.parametrize("catalog_populated", [False, True], ids=["empty", "populated"])
def test_available_source_filter_rejects_unknown_public_type_before_catalog_scan(
    context,
    catalog_populated,
):
    if catalog_populated:
        _source(context, name="Visible source")

    with pytest.raises(SourceConfigError, match="unsupported source type"):
        context["service"].list_available_sources(
            actor=_read_actor(context),
            source_type="hackernews",
            unsubscribed_only=False,
        )


def test_secret_checker_failure_is_fixed_and_does_not_retain_secret_env(context):
    secret_env = "DO_NOT_EXPOSE_DISCOVERY_TOKEN_ENV"
    _source(
        context,
        name="Secret-backed source",
        secret_env=secret_env,
    )

    def unavailable(name: str) -> bool:
        raise KeyError(name)

    service = RemoteMCPSubscriptionService(
        store=context["store"],
        mutations=context["mutations"],
        proposals=context["proposals"],
        secret_is_set=unavailable,
    )
    with pytest.raises(AgentProposalError) as error:
        service.list_available_sources(
            actor=_read_actor(context),
            source_type="rss",
            unsubscribed_only=False,
        )

    assert error.value.code == "source_discovery_unavailable"
    assert str(error.value) == "source discovery is unavailable"
    assert secret_env not in str(error.value)
    assert secret_env not in repr(error.value)
    assert secret_env not in repr(
        {"code": error.value.code, "message": str(error.value)}
    )
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_unsubscribed_filter_uses_only_the_current_users_subscriptions(context):
    subscribed = _source(context, name="Subscribed")
    other_only = _source(context, name="Other subscribed")
    context["store"].create_subscription(
        user_id=context["member"]["id"], source_id=subscribed["id"]
    )
    context["store"].create_subscription(
        user_id=context["other"]["id"], source_id=other_only["id"]
    )

    result = context["service"].list_available_sources(
        actor=_read_actor(context), source_type=None, unsubscribed_only=True
    )

    assert [item["id"] for item in result["items"]] == [other_only["id"]]
    assert result["items"][0]["subscribed"] is False


@pytest.mark.parametrize(
    ("flag", "actor_factory", "expected_code"),
    [
        (False, _read_actor, "subscription_writes_disabled"),
        (True, _read_actor, "write_scope_required"),
        (True, lambda context: _actor(context, "viewer"), "forbidden"),
    ],
)
def test_prepare_guard_order_fails_before_object_queries(
    context, monkeypatch, flag, actor_factory, expected_code
):
    context["writes_enabled"][0] = flag
    object_query = monkeypatch.setattr(
        context["store"],
        "get_source",
        lambda *_args, **_kwargs: pytest.fail("object query must not run"),
    )
    del object_query

    with pytest.raises(AgentProposalError) as error:
        context["service"].prepare_create_subscription(
            actor=actor_factory(context),
            source={"mode": "existing", "source_id": "src_unknown"},
            subscription={},
            schedule=None,
        )

    assert error.value.code == expected_code
    assert _proposal_count(context) == 0


def test_prepare_rejects_forged_actor_binding_before_object_queries(
    context, monkeypatch
):
    valid = _actor(context, "member")
    forged = DelegatedActor(
        workspace_id=valid.workspace_id,
        user_id=context["other"]["id"],
        role="member",
        delegation_id=valid.delegation_id,
        scopes=valid.scopes,
    )
    monkeypatch.setattr(
        context["store"],
        "get_source",
        lambda *_args, **_kwargs: pytest.fail("object query must not run"),
    )

    with pytest.raises(AgentProposalError) as error:
        context["service"].prepare_create_subscription(
            actor=forged,
            source={"mode": "existing", "source_id": "src_unknown"},
            subscription={},
            schedule=None,
        )

    assert error.value.code == "unauthorized"
    assert _proposal_count(context) == 0


def test_prepare_rejects_forged_write_scope_on_read_delegation(context):
    read = _read_actor(context)
    forged = DelegatedActor(
        workspace_id=read.workspace_id,
        user_id=read.user_id,
        role=read.role,
        delegation_id=read.delegation_id,
        scopes=(AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE),
    )

    with pytest.raises(AgentProposalError) as error:
        context["service"].prepare_create_subscription(
            actor=forged,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Nope",
                "config": {"url": "https://example.com/nope.xml"},
            },
            subscription={},
            schedule=None,
        )

    assert error.value.code == "unauthorized"
    assert _proposal_count(context) == 0


def test_prepare_rechecks_revocation_and_live_user_role(context):
    actor = _actor(context, "member")
    context["store"].connect().execute(
        "UPDATE users SET role = 'viewer' WHERE id = ?", (actor.user_id,)
    )
    context["store"].connect().commit()

    with pytest.raises(AgentProposalError) as downgraded:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Nope",
                "config": {"url": "https://example.com/nope.xml"},
            },
            subscription={},
            schedule=None,
        )
    assert downgraded.value.code == "forbidden"

    context["store"].connect().execute(
        "UPDATE users SET role = 'member' WHERE id = ?", (actor.user_id,)
    )
    context["store"].connect().commit()
    context["store"].revoke_agent_delegation(actor.user_id, actor.delegation_id)
    with pytest.raises(AgentProposalError) as revoked:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Nope",
                "config": {"url": "https://example.com/nope.xml"},
            },
            subscription={},
            schedule=None,
        )
    assert revoked.value.code == "unauthorized"
    assert _proposal_count(context) == 0


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
    row = context["store"].get_agent_change_proposal(prepared["proposal_id"])
    assert applied == {
        "proposal_id": prepared["proposal_id"],
        "status": "applied",
        "result": row["result_summary"],
    }
    assert row["status"] == "applied"
    assert set(applied["result"]) == {
        "action",
        "source_id",
        "subscription_id",
        "source_enabled",
        "subscription_enabled",
        "schedule_enabled",
        "schedule_interval_minutes",
    }
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

    with pytest.raises(AgentProposalError) as consumed:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )
    assert consumed.value.code == "proposal_consumed"


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
