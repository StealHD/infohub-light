from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from src.services.media_cache import MediaCacheService
from src.services.quota import QuotaExceeded, QuotaService
from src.services.source_health import SourceHealthService
from src.services.source_schedule import SOURCE_ALLOWED_INTERVALS, SourceScheduleService
from src.services.subscription_mutation import (
    SubscriptionActor,
    SubscriptionChangePlan,
    SubscriptionMutationError,
    SubscriptionMutationService,
)
from src.services.user_config_builder import build_user_config_data
from src.services.worker import _source_payload_from_catalog
from src.storage.service_store import ServiceStore


@pytest.fixture
def mutation_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
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
    viewer = store.create_user(
        workspace_id=workspace["id"],
        username="viewer",
        password="viewer-password",
        role="viewer",
    )
    quota = QuotaService(store, max_sources_per_user=100)
    schedules = SourceScheduleService(store, quota=quota)
    health = SourceHealthService(store)
    media = MediaCacheService(store, data_dir=tmp_path)
    service = SubscriptionMutationService(
        store,
        quota=quota,
        source_schedules=schedules,
        source_health=health,
        media_cache=media,
    )
    return {
        "store": store,
        "workspace": workspace,
        "owner": owner,
        "member": member,
        "viewer": viewer,
        "quota": quota,
        "schedules": schedules,
        "health": health,
        "media": media,
        "service": service,
    }


def _private_rss_plan(context, *, user="member", suffix="private"):
    actor = SubscriptionActor.from_user(context[user])
    return actor, context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "Example",
            "description": "Public feed",
            "default_channel": None,
            "default_topics": [],
            "config": {"url": f"https://example.com/{suffix}.xml"},
        },
        subscription={"enabled": True, "priority": 25},
        schedule={"enabled": True, "interval_minutes": 60},
    )


def _create_private_subscription(context, *, user="member", suffix="private"):
    actor, plan = _private_rss_plan(context, user=user, suffix=suffix)
    return actor, context["service"].apply_plan(actor, plan)


def _create_shared_source(context, *, suffix="shared"):
    store = context["store"]
    return store.create_source(
        workspace_id=context["workspace"]["id"],
        scope="workspace",
        owner_user_id=context["owner"]["id"],
        source_type="rss",
        display_name="Shared RSS",
        config={"url": f"https://example.com/{suffix}.xml"},
        source_key=f"rss:https://example.com/{suffix}.xml",
    )


def _insert_health_and_avatar(context, result):
    now = "2026-07-17T00:00:00+00:00"
    source = result["source"]
    subscription = result["subscription"]
    conn = context["store"].connect()
    conn.execute(
        """
        INSERT INTO user_source_health (
            subscription_id, workspace_id, user_id, source_id, status,
            last_attempt_at, consecutive_failures, last_fetched_count,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'healthy', ?, 0, 1, ?, ?)
        """,
        (
            subscription["id"],
            source["workspace_id"],
            subscription["user_id"],
            source["id"],
            now,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, source_id, asset_kind, remote_url, local_path,
            mime_type, byte_size, checksum, visibility_scope, status,
            created_at, updated_at
        ) VALUES ('media_avatar', ?, ?, 'source_avatar', '',
                  'media/missing-avatar.png', 'image/png', 0, 'checksum',
                  'private', 'ready', ?, ?)
        """,
        (source["workspace_id"], source["id"], now, now),
    )
    conn.commit()


def test_actor_plan_and_error_are_typed_and_plan_is_immutable(mutation_context):
    actor, plan = _private_rss_plan(mutation_context)

    assert actor == SubscriptionActor(
        mutation_context["workspace"]["id"],
        mutation_context["member"]["id"],
        "member",
    )
    assert isinstance(plan, SubscriptionChangePlan)
    assert plan.kind == "create"
    assert set(plan.fingerprints) >= {"source", "subscription", "schedule"}
    with pytest.raises(FrozenInstanceError):
        plan.kind = "delete"

    error = SubscriptionMutationError(
        "proposal_stale", "proposal targets changed", status_code=409, action="Retry."
    )
    assert error.code == "proposal_stale"
    assert error.status_code == 409
    assert error.action == "Retry."


def test_private_source_subscription_and_schedule_are_created_atomically(
    mutation_context,
):
    actor, plan = _private_rss_plan(mutation_context)

    result = mutation_context["service"].apply_plan(actor, plan)

    assert result["action"] == "created"
    assert result["source"]["scope"] == "private"
    assert result["source"]["owner_user_id"] == actor.user_id
    assert result["source"]["secret_env"] is None
    assert result["subscription"]["source_id"] == result["source"]["id"]
    assert result["schedule"]["enabled"] is True
    assert mutation_context["store"].connect().in_transaction is False


def test_plan_preview_is_safe_and_does_not_expose_config_or_internal_identity(
    mutation_context,
):
    _actor, plan = _private_rss_plan(mutation_context)

    serialized = repr(plan.preview)
    assert plan.preview["source"] == {
        "display_name": "Example",
        "type": "rss",
        "public_target": "https://example.com/private.xml",
    }
    assert set(plan.preview) >= {"action", "impact", "warnings", "subscription", "schedule"}
    assert "config" not in serialized
    assert "owner_user_id" not in serialized
    assert "source_key" not in serialized
    assert "secret_env" not in serialized


def test_agent_private_create_consumes_policy_and_keeps_public_type_separate(
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    plan = mutation_context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "github",
            "display_name": "Codex Releases",
            "config": {"repository": "https://github.com/openai/codex"},
        },
        subscription={},
        schedule=None,
    )

    result = mutation_context["service"].apply_plan(actor, plan)

    assert plan.payload["source"]["agent_type"] == "github"
    assert plan.payload["source"]["catalog_source_type"] == "github_release"
    assert result["source"]["type"] == "github_release"


@pytest.mark.parametrize("agent_type", ["twitter", "apify"])
def test_managed_agent_types_cannot_be_created(agent_type, mutation_context):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    config = (
        {"handle": "@openai"}
        if agent_type == "twitter"
        else {"platform": "x", "kind": "profile", "target": "openai"}
    )

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={
                "mode": "private",
                "type": agent_type,
                "display_name": "Managed source",
                "config": config,
            },
            subscription={},
            schedule=None,
        )

    assert exc_info.value.code == "source_requires_web_setup"
    assert str(exc_info.value) == "source_requires_web_setup"


@pytest.mark.parametrize(
    "source_overrides",
    [
        {"display_name": "Authorization: Bearer never-echo-this"},
        {"description": "api_key=never-echo-this"},
        {"default_channel": "password: never-echo-this"},
        {"default_topics": ["safe", "token=never-echo-this"]},
    ],
)
def test_agent_create_rejects_credentials_in_source_metadata_without_echo(
    source_overrides, mutation_context
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Safe name",
                "config": {"url": "https://example.com/metadata.xml"},
                **source_overrides,
            },
            subscription={},
            schedule=None,
        )

    assert exc_info.value.code == "invalid_source_config"
    assert "never-echo-this" not in str(exc_info.value)


def test_apify_customization_keeps_stable_web_setup_error(mutation_context):
    actor = SubscriptionActor.from_user(mutation_context["member"])

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={
                "mode": "private",
                "type": "apify",
                "display_name": "Managed source",
                "config": {
                    "platform": "x",
                    "kind": "profile",
                    "target": "openai",
                    "fetch_limit": 99,
                },
            },
            subscription={},
            schedule=None,
        )

    assert exc_info.value.code == "source_requires_web_setup"


def test_existing_shared_source_can_be_subscribed_but_not_mutated(mutation_context):
    source_id = _create_shared_source(mutation_context)
    actor = SubscriptionActor.from_user(mutation_context["member"])
    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={"priority": 10},
        schedule=None,
    )

    created = mutation_context["service"].apply_plan(actor, plan)
    assert created["subscription"]["source_id"] == source_id

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_update(
            actor,
            subscription_id=created["subscription"]["id"],
            source_updates={"display_name": "Blocked"},
            subscription_updates=None,
            schedule_updates=None,
        )
    assert exc_info.value.code == "forbidden"


def test_cross_user_and_missing_subscription_ids_share_not_found_contract(
    mutation_context,
):
    _actor, created = _create_private_subscription(mutation_context, user="owner")
    member_actor = SubscriptionActor.from_user(mutation_context["member"])

    for subscription_id in (created["subscription"]["id"], "sub_missing"):
        with pytest.raises(SubscriptionMutationError) as exc_info:
            mutation_context["service"].plan_update(
                member_actor,
                subscription_id=subscription_id,
                source_updates=None,
                subscription_updates={"enabled": False},
                schedule_updates=None,
            )
        assert exc_info.value.code == "not_found"
        assert exc_info.value.status_code == 404
        assert str(exc_info.value) == "subscription not found"


def test_viewer_cannot_plan_or_apply_writes(mutation_context):
    actor = SubscriptionActor.from_user(mutation_context["viewer"])
    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={"mode": "existing", "source_id": _create_shared_source(mutation_context)},
            subscription={},
            schedule=None,
        )
    assert exc_info.value.code == "forbidden"
    assert exc_info.value.status_code == 403

    member_actor, plan = _private_rss_plan(mutation_context)
    forged = SubscriptionActor(actor.workspace_id, actor.user_id, "member")
    with pytest.raises(SubscriptionMutationError) as apply_error:
        mutation_context["service"].apply_plan(forged, plan)
    assert apply_error.value.code in {"forbidden", "not_found"}


def test_own_private_update_preserves_omission_and_applies_explicit_clears(
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    create = mutation_context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "Clearable",
            "default_channel": "tech",
            "default_topics": ["AI"],
            "config": {"url": "https://example.com/clearable.xml"},
        },
        subscription={
            "override_channel": "tech",
            "override_topics": ["AI"],
            "personal_tags": ["keep-me"],
            "priority": 20,
        },
        schedule=None,
    )
    created = mutation_context["service"].apply_plan(actor, create)

    update = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={"default_channel": None, "default_topics": []},
        subscription_updates={"override_channel": None, "override_topics": []},
        schedule_updates=None,
    )
    result = mutation_context["service"].apply_plan(actor, update)

    assert result["source"]["default_channel"] is None
    assert result["source"]["default_topics"] == []
    assert result["subscription"]["override_channel"] is None
    assert result["subscription"]["override_topics"] == []
    assert result["subscription"]["personal_tags"] == ["keep-me"]
    assert result["subscription"]["priority"] == 20


def test_agent_update_rejects_credentials_in_config_or_metadata_without_echo(
    mutation_context,
):
    actor, created = _create_private_subscription(mutation_context)

    for updates in (
        {"display_name": "Authorization: Bearer never-echo-this"},
        {
            "config": {
                "url": "https://example.com/private.xml",
                "headers": {"Authorization": "Bearer never-echo-this"},
            }
        },
    ):
        with pytest.raises(SubscriptionMutationError) as exc_info:
            mutation_context["service"].plan_update(
                actor,
                subscription_id=created["subscription"]["id"],
                source_updates=updates,
                subscription_updates=None,
                schedule_updates=None,
            )
        assert exc_info.value.code == "invalid_source_config"
        assert "never-echo-this" not in str(exc_info.value)


@pytest.mark.parametrize("interval_minutes", SOURCE_ALLOWED_INTERVALS)
def test_agent_schedule_accepts_only_existing_interval_set(
    interval_minutes, mutation_context
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    plan = mutation_context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": f"Interval {interval_minutes}",
            "config": {"url": f"https://example.com/{interval_minutes}.xml"},
        },
        subscription={},
        schedule={"enabled": True, "interval_minutes": interval_minutes},
    )

    result = mutation_context["service"].apply_plan(actor, plan)
    assert result["schedule"]["interval_minutes"] == interval_minutes


def test_invalid_schedule_interval_fails_during_planning(mutation_context):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Invalid interval",
                "config": {"url": "https://example.com/invalid-interval.xml"},
            },
            subscription={},
            schedule={"enabled": True, "interval_minutes": 29},
        )
    assert exc_info.value.code == "invalid_source_schedule"


def test_quota_is_rechecked_at_apply_and_source_creation_rolls_back(
    mutation_context, monkeypatch
):
    actor, plan = _private_rss_plan(mutation_context)
    monkeypatch.setattr(
        mutation_context["quota"],
        "ensure_source_allowed",
        Mock(side_effect=QuotaExceeded("enabled source quota exceeded")),
    )

    with pytest.raises(SubscriptionMutationError, match="enabled source quota exceeded") as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "quota_exceeded"
    assert mutation_context["store"].connect().execute(
        "SELECT COUNT(*) FROM source_catalog"
    ).fetchone()[0] == 0
    assert mutation_context["store"].connect().execute(
        "SELECT COUNT(*) FROM user_subscriptions"
    ).fetchone()[0] == 0


def test_create_rolls_back_source_subscription_and_schedule_on_late_failure(
    mutation_context, monkeypatch
):
    actor, plan = _private_rss_plan(mutation_context)
    original = mutation_context["schedules"].update_subscription_schedule

    def fail_after_schedule_write(**kwargs):
        original(**kwargs)
        raise RuntimeError("late schedule failure")

    monkeypatch.setattr(
        mutation_context["schedules"], "update_subscription_schedule", fail_after_schedule_write
    )

    with pytest.raises(RuntimeError, match="late schedule failure"):
        mutation_context["service"].apply_plan(actor, plan)

    conn = mutation_context["store"].connect()
    assert conn.execute("SELECT COUNT(*) FROM source_catalog").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM user_subscriptions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM user_source_schedules").fetchone()[0] == 0
    assert conn.in_transaction is False


def test_update_failure_rolls_back_source_subscription_schedule_health_and_cache(
    mutation_context, monkeypatch
):
    actor, created = _create_private_subscription(mutation_context)
    _insert_health_and_avatar(mutation_context, created)
    before_source = mutation_context["store"].get_source(created["source"]["id"])
    before_subscription = mutation_context["store"].get_subscription(
        created["subscription"]["id"]
    )
    before_schedule = mutation_context["store"].get_source_schedule(
        created["subscription"]["id"]
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={
            "config": {"url": "https://example.com/changed.xml"},
            "display_name": "Changed",
        },
        subscription_updates={"priority": 99},
        schedule_updates={"interval_minutes": 180},
    )

    original = mutation_context["schedules"].update_subscription_schedule

    def fail_after_schedule_write(**kwargs):
        original(**kwargs)
        raise RuntimeError("rollback all")

    monkeypatch.setattr(
        mutation_context["schedules"], "update_subscription_schedule", fail_after_schedule_write
    )
    with pytest.raises(RuntimeError, match="rollback all"):
        mutation_context["service"].apply_plan(actor, plan)

    store = mutation_context["store"]
    assert store.get_source(created["source"]["id"]) == before_source
    assert store.get_subscription(created["subscription"]["id"]) == before_subscription
    assert store.get_source_schedule(created["subscription"]["id"]) == before_schedule
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE subscription_id = ?",
        (created["subscription"]["id"],),
    ).fetchone()[0] == 1
    assert store.connect().execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'media_avatar'"
    ).fetchone()[0] == 1


def test_source_key_conflict_is_rejected_at_prepare_and_rechecked_at_apply(
    mutation_context,
):
    actor, plan = _private_rss_plan(mutation_context, suffix="conflict")
    store = mutation_context["store"]
    store.create_source(
        workspace_id=mutation_context["workspace"]["id"],
        scope="workspace",
        owner_user_id=mutation_context["owner"]["id"],
        source_type="rss",
        display_name="Conflict",
        config={"url": "https://example.com/conflict.xml"},
        source_key="rss:https://example.com/conflict.xml",
    )

    with pytest.raises(SubscriptionMutationError) as apply_error:
        mutation_context["service"].apply_plan(actor, plan)
    assert apply_error.value.code in {"source_key_conflict", "proposal_stale"}

    with pytest.raises(SubscriptionMutationError) as prepare_error:
        _private_rss_plan(mutation_context, suffix="conflict")
    assert prepare_error.value.code == "source_key_conflict"


def test_apply_rejects_stale_target_fingerprints_without_writes(mutation_context):
    actor, created = _create_private_subscription(mutation_context)
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates=None,
        subscription_updates={"priority": 55},
        schedule_updates=None,
    )
    mutation_context["store"].connect().execute(
        "UPDATE user_subscriptions SET updated_at = ? WHERE id = ?",
        ("2099-01-01T00:00:00+00:00", created["subscription"]["id"]),
    )
    mutation_context["store"].connect().commit()

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "proposal_stale"
    assert exc_info.value.status_code == 409
    assert mutation_context["store"].get_subscription(
        created["subscription"]["id"]
    )["priority"] == 25


def test_apply_rechecks_live_actor_role_and_workspace(mutation_context):
    actor, plan = _private_rss_plan(mutation_context)
    mutation_context["store"].update_user(actor.user_id, role="viewer")

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "forbidden"
    assert mutation_context["store"].connect().execute(
        "SELECT COUNT(*) FROM source_catalog"
    ).fetchone()[0] == 0


def test_health_and_avatar_reset_only_when_fetch_identity_changes(mutation_context):
    actor, created = _create_private_subscription(mutation_context)
    _insert_health_and_avatar(mutation_context, created)
    subscription_id = created["subscription"]["id"]
    source_id = created["source"]["id"]

    metadata_plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription_id,
        source_updates={"display_name": "Metadata only"},
        subscription_updates=None,
        schedule_updates=None,
    )
    mutation_context["service"].apply_plan(actor, metadata_plan)
    assert mutation_context["health"].get_health(subscription_id) is not None
    assert mutation_context["media"].avatar_for_source(
        workspace_id=actor.workspace_id, source_id=source_id
    ) is not None

    identity_plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription_id,
        source_updates={"config": {"url": "https://example.com/new-identity.xml"}},
        subscription_updates=None,
        schedule_updates=None,
    )
    mutation_context["service"].apply_plan(actor, identity_plan)
    assert mutation_context["health"].get_health(subscription_id) is None
    assert mutation_context["media"].avatar_for_source(
        workspace_id=actor.workspace_id, source_id=source_id
    ) is None


@pytest.mark.parametrize(
    ("disposition", "source_enabled"), (("keep", True), ("disable_private", False))
)
def test_delete_requires_explicit_source_disposition(
    disposition, source_enabled, mutation_context
):
    actor, created = _create_private_subscription(
        mutation_context, suffix=f"delete-{disposition}"
    )
    plan = mutation_context["service"].plan_delete(
        actor,
        subscription_id=created["subscription"]["id"],
        source_disposition=disposition,
    )

    result = mutation_context["service"].apply_plan(actor, plan)

    assert result["deleted"] is True
    assert result["source_disabled"] is (not source_enabled)
    assert mutation_context["store"].get_source(created["source"]["id"])[
        "enabled"
    ] is source_enabled


def test_delete_missing_disposition_and_shared_disable_are_rejected(mutation_context):
    actor, private = _create_private_subscription(mutation_context)
    with pytest.raises(SubscriptionMutationError) as missing:
        mutation_context["service"].plan_delete(
            actor, subscription_id=private["subscription"]["id"]
        )
    assert missing.value.code == "invalid_request"

    source_id = _create_shared_source(mutation_context, suffix="shared-delete")
    shared_plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={},
        schedule=None,
    )
    shared = mutation_context["service"].apply_plan(actor, shared_plan)
    with pytest.raises(SubscriptionMutationError) as forbidden:
        mutation_context["service"].plan_delete(
            actor,
            subscription_id=shared["subscription"]["id"],
            source_disposition="disable_private",
        )
    assert forbidden.value.code == "forbidden"


def test_agent_created_rss_persists_and_executes_public_network_policy_for_owner(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, user="owner", suffix="owner-public-network"
    )
    source = mutation_context["store"].get_source(created["source"]["id"])

    assert source["enforce_public_network"] is True
    worker_payload = _source_payload_from_catalog(
        {"source_id": source["id"], "payload_json": {}},
        store=mutation_context["store"],
    )
    assert worker_payload["enforce_public_network"] is True

    config = build_user_config_data(
        store=mutation_context["store"],
        workspace_id=actor.workspace_id,
        user_id=actor.user_id,
        base_config={
            "version": "1.0",
            "ai": {"enabled": False},
            "tags": [],
            "personal_tags": [],
            "sources": {},
            "filtering": {},
        },
    )
    entry = next(
        item
        for item in config["sources"]["rss"]
        if item["source_id"] == source["id"]
    )
    assert entry["enforce_public_network"] is True


def test_explicit_rest_context_keeps_admin_shared_source_management(
    mutation_context,
):
    source_id = _create_shared_source(mutation_context, suffix="rest-admin")
    actor = SubscriptionActor.from_user(mutation_context["owner"])
    subscription = mutation_context["service"].rest_create_subscription(
        actor, source_id=source_id, values={"priority": 10}
    )

    with pytest.raises(SubscriptionMutationError) as agent_error:
        mutation_context["service"].plan_update(
            actor,
            subscription_id=subscription["id"],
            source_updates={"display_name": "Agent blocked"},
            subscription_updates=None,
            schedule_updates=None,
        )
    assert agent_error.value.code == "forbidden"

    updated = mutation_context["service"].rest_update_source(
        actor,
        source_id=source_id,
        updates={"display_name": "REST admin allowed"},
    )
    assert updated["display_name"] == "REST admin allowed"
    assert mutation_context["store"].connect().in_transaction is False


def test_rest_context_preserves_subscription_omission_null_and_list_clear(
    mutation_context,
):
    source_id = _create_shared_source(mutation_context, suffix="rest-omission")
    actor = SubscriptionActor.from_user(mutation_context["member"])
    subscription = mutation_context["service"].rest_create_subscription(
        actor,
        source_id=source_id,
        values={
            "override_channel": "tech",
            "override_topics": ["AI"],
            "personal_tags": ["keep"],
            "priority": 40,
        },
    )

    updated = mutation_context["service"].rest_update_subscription(
        actor,
        subscription_id=subscription["id"],
        updates={"override_channel": None, "override_topics": []},
    )

    assert updated["override_channel"] is None
    assert updated["override_topics"] == []
    assert updated["personal_tags"] == ["keep"]
    assert updated["priority"] == 40
    assert mutation_context["store"].connect().in_transaction is False
