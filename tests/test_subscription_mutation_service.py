from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
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
import src.services.subscription_mutation as subscription_mutation_module
import src.services.media_cache as media_cache_module


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
        "data_dir": tmp_path,
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
    avatar_path = context["data_dir"] / "media" / "missing-avatar.png"
    avatar_path.parent.mkdir(parents=True, exist_ok=True)
    avatar_path.write_bytes(b"\x89PNG\r\n\x1a\noriginal-avatar-bytes")
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
    return avatar_path


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


def test_public_plan_constructor_cannot_create_an_executable_plan(mutation_context):
    _actor, planned = _private_rss_plan(mutation_context)

    with pytest.raises(TypeError, match="planner or restore"):
        SubscriptionChangePlan(
            planned.kind,
            planned.payload,
            planned.preview,
            planned.target_ids,
            planned.fingerprints,
        )


def test_versioned_plan_snapshot_json_round_trip_restores_same_execution(
    mutation_context,
):
    actor, planned = _private_rss_plan(
        mutation_context, suffix="snapshot-round-trip"
    )
    snapshot = json.loads(json.dumps(planned.to_snapshot()))

    restored = mutation_context["service"].restore_plan_snapshot(snapshot)
    result = mutation_context["service"].apply_plan(actor, restored)

    assert restored.to_snapshot() == snapshot
    assert (
        result["source"]["config"]["url"]
        == "https://example.com/snapshot-round-trip.xml"
    )
    assert result["source"]["enforce_public_network"] is True
    assert result["schedule"]["enabled"] is True
    assert result["schedule"]["interval_minutes"] == 60


@pytest.mark.parametrize(
    "forge",
    [
        lambda snapshot: (
            snapshot["normalized"]["source"].update(
                {
                    "config": {"url": "http://localhost/private.xml"},
                    "source_key": "rss:http://localhost/private.xml",
                    "enforce_public_network": False,
                }
            ),
            snapshot["preview"]["source"].update(
                {"public_target": "http://localhost/private.xml"}
            ),
        ),
        lambda snapshot: (
            snapshot["normalized"]["source"].update(
                {
                    "agent_type": "twitter",
                    "catalog_source_type": "apify_social",
                    "config": {
                        "platform": "x",
                        "kind": "profile",
                        "target": "openai",
                    },
                    "source_key": "apify_social:x:profile:openai",
                    "enforce_public_network": False,
                }
            ),
            snapshot["preview"]["source"].update(
                {
                    "type": "twitter",
                    "public_target": {
                        "platform": "x",
                        "kind": "profile",
                        "target": "openai",
                    },
                }
            ),
        ),
        lambda snapshot: snapshot["preview"]["source"].update(
            {"display_name": "Benign but unconfirmed preview"}
        ),
        lambda snapshot: snapshot["normalized"].update({"unexpected": True}),
    ],
    ids=[
        "localhost-marker-false",
        "managed-only-private-type",
        "preview-payload-mismatch",
        "unexpected-normalized-key",
    ],
)
def test_plan_snapshot_restoration_rejects_forged_normalized_or_preview_data(
    forge,
    mutation_context,
):
    _actor, planned = _private_rss_plan(
        mutation_context, suffix="snapshot-forgery"
    )
    snapshot = planned.to_snapshot()
    forge(snapshot)

    with pytest.raises(SubscriptionMutationError) as error:
        mutation_context["service"].restore_plan_snapshot(snapshot)

    assert error.value.code == "invalid_plan_snapshot"


@pytest.mark.parametrize("kind", ["update", "delete"])
def test_update_and_delete_plan_snapshots_json_round_trip_and_execute(
    kind,
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, suffix=f"snapshot-{kind}"
    )
    if kind == "update":
        planned = mutation_context["service"].plan_update(
            actor,
            subscription_id=created["subscription"]["id"],
            source_updates=None,
            subscription_updates={"priority": 77},
            schedule_updates=None,
        )
    else:
        planned = mutation_context["service"].plan_delete(
            actor,
            subscription_id=created["subscription"]["id"],
            source_disposition="keep",
        )
    snapshot = json.loads(json.dumps(planned.to_snapshot()))

    restored = mutation_context["service"].restore_plan_snapshot(snapshot)
    result = mutation_context["service"].apply_plan(actor, restored)

    assert restored.to_snapshot() == snapshot
    assert result["action"] == ("updated" if kind == "update" else "deleted")
    if kind == "update":
        assert result["subscription"]["priority"] == 77
    else:
        assert result["deleted"] is True


def test_apply_revalidates_even_an_internally_forged_plan_instance(
    mutation_context,
):
    actor, planned = _private_rss_plan(
        mutation_context, suffix="internal-factory-forgery"
    )
    snapshot = planned.to_snapshot()
    snapshot["normalized"]["source"].update(
        {
            "config": {"url": "http://localhost/internal-forgery.xml"},
            "source_key": "rss:http://localhost/internal-forgery.xml",
            "enforce_public_network": True,
        }
    )
    snapshot["preview"]["source"][
        "public_target"
    ] = "http://localhost/internal-forgery.xml"
    forged = SubscriptionChangePlan._from_validated_snapshot(
        snapshot["kind"],
        snapshot["normalized"],
        snapshot["preview"],
        snapshot["targets"],
        snapshot["fingerprints"],
    )

    with pytest.raises(SubscriptionMutationError) as error:
        mutation_context["service"].apply_plan(actor, forged)

    assert error.value.code == "invalid_plan_snapshot"
    assert mutation_context["store"].connect().execute(
        "SELECT COUNT(*) FROM source_catalog"
    ).fetchone()[0] == 0


def test_update_snapshot_restoration_rejects_false_public_marker_and_bad_shapes(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, suffix="snapshot-update-validation"
    )
    planned = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={
            "config": {"url": "https://example.com/snapshot-update-new.xml"}
        },
        subscription_updates=None,
        schedule_updates=None,
    )

    forged_snapshots = []
    false_marker = planned.to_snapshot()
    false_marker["normalized"]["source_updates"]["enforce_public_network"] = False
    forged_snapshots.append(false_marker)
    extra_target = planned.to_snapshot()
    extra_target["targets"]["unexpected"] = "src_forged"
    forged_snapshots.append(extra_target)
    boolean_fingerprint = planned.to_snapshot()
    boolean_fingerprint["fingerprints"]["source"] = False
    forged_snapshots.append(boolean_fingerprint)

    for snapshot in forged_snapshots:
        with pytest.raises(SubscriptionMutationError) as error:
            mutation_context["service"].restore_plan_snapshot(snapshot)
        assert error.value.code == "invalid_plan_snapshot"


def test_delete_snapshot_restoration_rejects_disposition_and_payload_shape(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, suffix="snapshot-delete-validation"
    )
    planned = mutation_context["service"].plan_delete(
        actor,
        subscription_id=created["subscription"]["id"],
        source_disposition="keep",
    )
    invalid_disposition = planned.to_snapshot()
    invalid_disposition["normalized"]["source_disposition"] = "disable_shared"
    invalid_disposition["preview"]["source_disposition"] = "disable_shared"
    unexpected_payload = planned.to_snapshot()
    unexpected_payload["normalized"]["enabled"] = False

    for snapshot in (invalid_disposition, unexpected_payload):
        with pytest.raises(SubscriptionMutationError) as error:
            mutation_context["service"].restore_plan_snapshot(snapshot)
        assert error.value.code == "invalid_plan_snapshot"


def test_plan_exposes_only_defensive_copies_of_every_nested_snapshot(
    mutation_context,
):
    _actor, plan = _private_rss_plan(mutation_context)
    expected_payload = deepcopy(plan.payload)
    expected_preview = deepcopy(plan.preview)
    expected_target_ids = deepcopy(plan.target_ids)
    expected_fingerprints = deepcopy(plan.fingerprints)

    exposed_payload = plan.payload
    exposed_payload["source"]["config"]["url"] = "https://attacker.invalid/feed"
    exposed_payload["source"]["default_topics"].append("unconfirmed")
    exposed_preview = plan.preview
    exposed_preview["source"]["display_name"] = "Unconfirmed"
    exposed_preview["warnings"].append("unconfirmed")
    exposed_target_ids = plan.target_ids
    exposed_target_ids["source_id"] = "src_forged"
    exposed_fingerprints = plan.fingerprints
    exposed_fingerprints["source"] = "forged"

    assert plan.payload == expected_payload
    assert plan.preview == expected_preview
    assert plan.target_ids == expected_target_ids
    assert plan.fingerprints == expected_fingerprints


def test_apply_executes_sealed_normalized_payload_without_renormalizing(
    mutation_context, monkeypatch
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    source_request = {
        "mode": "private",
        "type": "rss",
        "display_name": "Sealed",
        "default_topics": ["confirmed"],
        "config": {"url": "https://example.com/confirmed.xml"},
    }
    plan = mutation_context["service"].plan_create(
        actor,
        source=source_request,
        subscription={"override_topics": ["confirmed"]},
        schedule=None,
    )
    source_request["config"]["url"] = "https://example.com/unconfirmed.xml"
    source_request["default_topics"].append("unconfirmed")

    def normalization_must_not_run(*_args, **_kwargs):
        raise AssertionError("apply must not re-normalize a confirmed plan")

    monkeypatch.setattr(
        subscription_mutation_module,
        "normalize_source_setup_input",
        normalization_must_not_run,
    )

    result = mutation_context["service"].apply_plan(actor, plan)

    assert result["source"]["config"]["url"] == "https://example.com/confirmed.xml"
    assert result["source"]["default_topics"] == ["confirmed"]
    assert result["subscription"]["override_topics"] == ["confirmed"]


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


@pytest.mark.parametrize("schedule_request", [None, {}], ids=["omitted", "empty"])
def test_existing_subscription_create_preview_shows_current_final_schedule(
    schedule_request,
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    source_id = _create_shared_source(
        mutation_context, suffix=f"schedule-existing-{schedule_request is None}"
    )
    subscription = mutation_context["store"].create_subscription(
        user_id=actor.user_id,
        source_id=source_id,
    )
    mutation_context["schedules"].update_subscription_schedule(
        workspace_id=actor.workspace_id,
        user_id=actor.user_id,
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=180,
    )

    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={},
        schedule=schedule_request,
    )
    result = mutation_context["service"].apply_plan(actor, plan)

    assert plan.preview["schedule"] == {
        "enabled": True,
        "interval_minutes": 180,
    }
    assert result["schedule"]["enabled"] is True
    assert result["schedule"]["interval_minutes"] == 180


@pytest.mark.parametrize("schedule_request", [None, {}], ids=["omitted", "empty"])
def test_new_subscription_create_preview_shows_real_default_schedule(
    schedule_request,
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    suffix = f"schedule-new-{schedule_request is None}"
    plan = mutation_context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "Default schedule",
            "config": {"url": f"https://example.com/{suffix}.xml"},
        },
        subscription={},
        schedule=schedule_request,
    )
    result = mutation_context["service"].apply_plan(actor, plan)

    assert plan.preview["schedule"] == {
        "enabled": False,
        "interval_minutes": 60,
    }
    assert result["schedule"]["enabled"] is False
    assert result["schedule"]["interval_minutes"] == 60


@pytest.mark.parametrize(
    ("display_name", "config", "secret_text"),
    [
        (
            "Authorization: Bearer legacy-display-secret",
            {"url": "https://example.com/legacy.xml"},
            "legacy-display-secret",
        ),
        (
            "Legacy userinfo",
            {"url": "https://legacy-user:legacy-password@example.com/feed.xml"},
            "legacy-password",
        ),
        (
            "Legacy signed query",
            {"url": "https://example.com/feed.xml?access_token=legacy-query-secret"},
            "legacy-query-secret",
        ),
        (
            "Legacy header config",
            {
                "url": "https://example.com/header.xml",
                "headers": {"Authorization": "Bearer legacy-header-secret"},
            },
            "legacy-header-secret",
        ),
    ],
)
def test_existing_legacy_source_preview_uses_stable_opaque_safe_summary(
    display_name, config, secret_text, mutation_context
):
    member = mutation_context["member"]
    source_id = mutation_context["store"].create_source(
        workspace_id=member["workspace_id"],
        scope="private",
        owner_user_id=member["id"],
        source_type="rss",
        display_name=display_name,
        config=config,
        source_key=f"legacy-unsafe:{secret_text}",
    )
    actor = SubscriptionActor.from_user(member)

    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={},
        schedule=None,
    )

    assert plan.preview["source"] == {
        "display_name": "Web-managed source",
        "type": "rss",
        "public_target": "web_setup_required",
    }
    assert secret_text not in repr(plan.preview)


@pytest.mark.parametrize(
    ("display_name", "url", "secret_text"),
    [
        (
            "Feed ghp_1234567890abcdef",
            "https://example.com/legacy-ghp.xml",
            "ghp_1234567890abcdef",
        ),
        (
            "Release github_pat_12345678_abcdefgh",
            "https://example.com/legacy-github-pat.xml",
            "github_pat_12345678_abcdefgh",
        ),
        (
            "Legacy Slack cursor",
            "https://example.com/feed?cursor=xoxb-12345678-abcdefgh",
            "xoxb-12345678-abcdefgh",
        ),
        (
            "Legacy Slack fragment",
            "https://example.com/feed#xoxp-12345678-abcdefgh",
            "xoxp-12345678-abcdefgh",
        ),
    ],
)
def test_projector_makes_embedded_known_token_values_opaque_without_echo(
    display_name,
    url,
    secret_text,
    mutation_context,
):
    member = mutation_context["member"]
    source_id = mutation_context["store"].create_source(
        workspace_id=member["workspace_id"],
        scope="private",
        owner_user_id=member["id"],
        source_type="rss",
        display_name=display_name,
        config={"url": url},
        source_key=f"legacy-token-{len(secret_text)}",
    )
    actor = SubscriptionActor.from_user(member)

    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={},
        schedule=None,
    )

    assert plan.preview["source"] == {
        "display_name": "Web-managed source",
        "type": "rss",
        "public_target": "web_setup_required",
    }
    assert secret_text not in repr(plan.preview)


def test_projector_keeps_safe_bearer_business_title_public(mutation_context):
    member = mutation_context["member"]
    source_id = mutation_context["store"].create_source(
        workspace_id=member["workspace_id"],
        scope="private",
        owner_user_id=member["id"],
        source_type="rss",
        display_name="Bearer Market Report",
        config={"url": "https://example.com/bearer-market-report.xml"},
        source_key="rss:https://example.com/bearer-market-report.xml",
    )
    actor = SubscriptionActor.from_user(member)

    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={},
        schedule=None,
    )

    assert plan.preview["source"] == {
        "display_name": "Bearer Market Report",
        "type": "rss",
        "public_target": "https://example.com/bearer-market-report.xml",
    }


def test_update_and_delete_previews_do_not_echo_unsafe_existing_catalog_values(
    mutation_context,
):
    member = mutation_context["member"]
    source_id = mutation_context["store"].create_source(
        workspace_id=member["workspace_id"],
        scope="private",
        owner_user_id=member["id"],
        source_type="rss",
        display_name="Legacy signed source",
        config={
            "url": "https://example.com/feed.xml?signature=legacy-preview-secret"
        },
        source_key="legacy-unsafe:update-delete",
    )
    subscription = mutation_context["store"].create_subscription(
        user_id=member["id"], source_id=source_id
    )
    actor = SubscriptionActor.from_user(member)

    update_plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription["id"],
        source_updates=None,
        subscription_updates={"priority": 10},
        schedule_updates=None,
    )
    delete_plan = mutation_context["service"].plan_delete(
        actor,
        subscription_id=subscription["id"],
        source_disposition="keep",
    )

    for plan in (update_plan, delete_plan):
        assert plan.preview["source"] == {
            "display_name": "Web-managed source",
            "type": "rss",
            "public_target": "web_setup_required",
        }
        assert "legacy-preview-secret" not in repr(plan.preview)


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


def test_agent_rss_update_rejects_local_target_and_forces_public_network_marker(
    mutation_context,
):
    store = mutation_context["store"]
    owner = mutation_context["owner"]
    source_id = store.create_source(
        workspace_id=owner["workspace_id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Web-created RSS",
        config={"url": "https://example.com/web-created.xml"},
        source_key="rss:https://example.com/web-created.xml",
        enforce_public_network=False,
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    actor = SubscriptionActor.from_user(owner)

    with pytest.raises(SubscriptionMutationError) as local_error:
        mutation_context["service"].plan_update(
            actor,
            subscription_id=subscription["id"],
            source_updates={"config": {"url": "http://localhost/private-feed"}},
            subscription_updates=None,
            schedule_updates=None,
        )
    assert local_error.value.code == "invalid_source_config"
    assert "localhost" not in str(local_error.value)

    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription["id"],
        source_updates={"config": {"url": "https://example.com/agent-updated.xml"}},
        subscription_updates=None,
        schedule_updates=None,
    )
    updated = mutation_context["service"].apply_plan(actor, plan)

    assert updated["source"]["config"]["url"] == "https://example.com/agent-updated.xml"
    assert updated["source"]["enforce_public_network"] is True


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


def test_reenabling_disabled_source_with_enabled_subscription_obeys_active_quota(
    mutation_context,
):
    actor, _active = _create_private_subscription(
        mutation_context, suffix="active-at-quota"
    )
    mutation_context["quota"].max_sources_per_user = 1
    store = mutation_context["store"]
    source_id = store.create_source(
        workspace_id=actor.workspace_id,
        scope="private",
        owner_user_id=actor.user_id,
        source_type="rss",
        display_name="Disabled but subscribed",
        config={"url": "https://example.com/disabled-at-quota.xml"},
        source_key="rss:https://example.com/disabled-at-quota.xml",
        enabled=False,
    )
    subscription = store.create_subscription(
        user_id=actor.user_id,
        source_id=source_id,
        enabled=True,
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription["id"],
        source_updates={"enabled": True},
        subscription_updates=None,
        schedule_updates=None,
    )

    with pytest.raises(
        SubscriptionMutationError, match="enabled source quota exceeded"
    ) as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "quota_exceeded"
    assert store.get_source(source_id)["enabled"] is False


@pytest.mark.parametrize("path", ["agent", "rest"])
def test_repeated_subscription_enable_is_idempotent_when_source_is_disabled_at_quota(
    path,
    mutation_context,
):
    actor, _active = _create_private_subscription(
        mutation_context, suffix=f"idempotent-active-{path}"
    )
    mutation_context["quota"].max_sources_per_user = 1
    store = mutation_context["store"]
    source_id = store.create_source(
        workspace_id=actor.workspace_id,
        scope="private",
        owner_user_id=actor.user_id,
        source_type="rss",
        display_name="Disabled source",
        config={"url": f"https://example.com/idempotent-disabled-{path}.xml"},
        source_key=f"rss:https://example.com/idempotent-disabled-{path}.xml",
        enabled=False,
    )
    subscription = store.create_subscription(
        user_id=actor.user_id,
        source_id=source_id,
        enabled=True,
    )

    if path == "agent":
        plan = mutation_context["service"].plan_update(
            actor,
            subscription_id=subscription["id"],
            source_updates=None,
            subscription_updates={"enabled": True},
            schedule_updates=None,
        )
        result = mutation_context["service"].apply_plan(actor, plan)["subscription"]
    else:
        result = mutation_context["service"].rest_update_subscription(
            actor,
            subscription_id=subscription["id"],
            updates={"enabled": True},
        )

    assert result["enabled"] is True
    assert store.get_source(source_id)["enabled"] is False


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
    avatar_path = _insert_health_and_avatar(mutation_context, created)
    avatar_bytes = avatar_path.read_bytes()
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
    assert avatar_path.read_bytes() == avatar_bytes


def test_commit_false_exposes_explicit_post_commit_avatar_cleanup(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, suffix="caller-owned-cleanup"
    )
    avatar_path = _insert_health_and_avatar(mutation_context, created)
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={
            "config": {"url": "https://example.com/caller-owned-cleanup-new.xml"}
        },
        subscription_updates=None,
        schedule_updates=None,
    )
    cleanup = media_cache_module.PostCommitMediaCleanup()
    conn = mutation_context["store"].connect()
    conn.execute("BEGIN IMMEDIATE")

    result = mutation_context["service"].apply_plan(
        actor,
        plan,
        post_commit_cleanup=cleanup,
    )

    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'media_avatar'"
    ).fetchone()[0] == 0
    assert avatar_path.exists()
    assert "cleanup" not in result
    assert "local_path" not in repr(result)
    conn.commit()
    cleanup.run()
    assert not avatar_path.exists()


def test_outer_transaction_without_cleanup_fails_before_plan_mutation_even_with_default_commit(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, suffix="outer-default-cleanup-required"
    )
    avatar_path = _insert_health_and_avatar(mutation_context, created)
    source_before = mutation_context["store"].get_source(created["source"]["id"])
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={
            "config": {
                "url": "https://example.com/outer-default-cleanup-required-new.xml"
            }
        },
        subscription_updates=None,
        schedule_updates=None,
    )
    conn = mutation_context["store"].connect()
    conn.execute("BEGIN IMMEDIATE")

    with pytest.raises(SubscriptionMutationError) as error:
        mutation_context["service"].apply_plan(actor, plan)

    assert error.value.code == "post_commit_cleanup_required"
    assert mutation_context["store"].get_source(created["source"]["id"]) == source_before
    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'media_avatar'"
    ).fetchone()[0] == 1
    assert avatar_path.exists()
    conn.rollback()


def test_outer_transaction_rollback_discards_collected_avatar_cleanup(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, suffix="outer-cleanup-rollback"
    )
    avatar_path = _insert_health_and_avatar(mutation_context, created)
    source_before = mutation_context["store"].get_source(created["source"]["id"])
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={
            "config": {"url": "https://example.com/outer-cleanup-rollback-new.xml"}
        },
        subscription_updates=None,
        schedule_updates=None,
    )
    cleanup = media_cache_module.PostCommitMediaCleanup()
    conn = mutation_context["store"].connect()
    conn.execute("BEGIN IMMEDIATE")

    result = mutation_context["service"].apply_plan(
        actor,
        plan,
        post_commit_cleanup=cleanup,
    )
    assert "cleanup" not in result
    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'media_avatar'"
    ).fetchone()[0] == 0
    assert avatar_path.exists()

    conn.rollback()
    cleanup.discard()
    assert mutation_context["store"].get_source(created["source"]["id"]) == source_before
    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'media_avatar'"
    ).fetchone()[0] == 1
    assert avatar_path.exists()


def test_commit_false_requires_explicit_post_commit_cleanup_collector(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, suffix="caller-owned-cleanup-required"
    )
    avatar_path = _insert_health_and_avatar(mutation_context, created)
    source_before = mutation_context["store"].get_source(created["source"]["id"])
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={
            "config": {
                "url": "https://example.com/caller-owned-cleanup-required-new.xml"
            }
        },
        subscription_updates=None,
        schedule_updates=None,
    )

    with pytest.raises(SubscriptionMutationError) as error:
        mutation_context["service"].apply_plan(actor, plan, commit=False)

    assert error.value.code == "post_commit_cleanup_required"
    assert mutation_context["store"].connect().in_transaction is False
    assert mutation_context["store"].get_source(created["source"]["id"]) == source_before
    assert mutation_context["store"].connect().execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'media_avatar'"
    ).fetchone()[0] == 1
    assert avatar_path.exists()


def test_rest_source_update_inside_outer_transaction_requires_explicit_cleanup(
    mutation_context,
):
    actor, created = _create_private_subscription(
        mutation_context, user="owner", suffix="rest-outer-cleanup-required"
    )
    avatar_path = _insert_health_and_avatar(mutation_context, created)
    source_before = mutation_context["store"].get_source(created["source"]["id"])
    conn = mutation_context["store"].connect()
    conn.execute("BEGIN IMMEDIATE")

    with pytest.raises(SubscriptionMutationError) as error:
        mutation_context["service"].rest_update_source(
            actor,
            source_id=created["source"]["id"],
            updates={
                "config": {
                    "url": "https://example.com/rest-outer-cleanup-required-new.xml",
                    "name": "REST outer",
                    "enabled": True,
                    "keep_latest_item": False,
                },
                "source_key": "rss:https://example.com/rest-outer-cleanup-required-new.xml",
            },
        )

    assert error.value.code == "post_commit_cleanup_required"
    assert mutation_context["store"].get_source(created["source"]["id"]) == source_before
    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'media_avatar'"
    ).fetchone()[0] == 1
    assert avatar_path.exists()
    conn.rollback()


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
