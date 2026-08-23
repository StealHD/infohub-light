from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.models import ContentItem, SourceType
from src.services.canonical_content import INTERNAL_SOURCE_NATIVE_TITLE_KEY
from src.services.media_cache import MediaCacheService
from src.services.quota import QuotaExceeded, QuotaService
from src.services.source_health import SourceHealthService
from src.services.source_schedule import SOURCE_ALLOWED_INTERVALS, SourceScheduleService
from src.services.source_type_registry import source_key, validate_source_config
from src.services.subscription_mutation import (
    SubscriptionActor,
    SubscriptionChangePlan,
    SubscriptionMutationError,
    SubscriptionMutationService,
)
from src.services.user_config_builder import build_user_config_data
from src.services.user_feed_store import UserFeedStore
from src.services.worker_handlers import source_payload_from_catalog as _source_payload_from_catalog
from src.storage.service_store import ServiceStore
from src.services.feed_payload import serialize_feed_item
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
    try:
        yield {
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
    finally:
        store.close()


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


def test_version_one_plan_snapshot_fails_closed_and_requires_reprepare(
    mutation_context,
):
    _actor, planned = _private_rss_plan(
        mutation_context, suffix="snapshot-v1-reprepare"
    )
    snapshot = planned.to_snapshot()
    assert snapshot["version"] == 2
    snapshot["version"] = 1

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].restore_plan_snapshot(snapshot)

    assert exc_info.value.code == "invalid_plan_snapshot"


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


@pytest.mark.parametrize("schedule_request", [None, {}], ids=["omitted", "empty"])
def test_new_disabled_subscription_create_preview_uses_final_subject_state(
    schedule_request,
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    suffix = f"new-disabled-{schedule_request is None}"

    plan = mutation_context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "Disabled new subscription",
            "config": {"url": f"https://example.com/{suffix}.xml"},
        },
        subscription={"enabled": False},
        schedule=schedule_request,
    )
    result = mutation_context["service"].apply_plan(actor, plan)

    assert plan.payload["schedule_preview"] == {
        "enabled": False,
        "interval_minutes": 60,
    }
    assert result["subscription"]["enabled"] is False
    assert result["schedule"]["enabled"] is False
    assert result["schedule"]["interval_minutes"] == 60


def test_new_disabled_subscription_rejects_explicit_schedule_enable_at_prepare(
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Impossible schedule",
                "config": {"url": "https://example.com/impossible-schedule.xml"},
            },
            subscription={"enabled": False},
            schedule={"enabled": True, "interval_minutes": 180},
        )

    assert exc_info.value.code == "source_schedule_unavailable"
    assert exc_info.value.status_code == 409


def _existing_create_schedule_target(
    context,
    *,
    suffix: str,
    schedule_state: str,
    subscription_enabled: bool = True,
    source_enabled: bool = True,
):
    actor = SubscriptionActor.from_user(context["member"])
    source_id = _create_shared_source(context, suffix=suffix)
    subscription = context["store"].create_subscription(
        user_id=actor.user_id,
        source_id=source_id,
        enabled=True,
    )
    if schedule_state != "absent":
        context["schedules"].update_subscription_schedule(
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            subscription_id=subscription["id"],
            enabled=schedule_state == "enabled",
            interval_minutes=180,
        )
    if not subscription_enabled:
        context["store"].update_subscription(subscription["id"], enabled=False)
    if not source_enabled:
        context["store"].update_source(source_id, enabled=False)
    return actor, source_id, subscription


@pytest.mark.parametrize(
    ("schedule_state", "expected_interval"),
    [("absent", 60), ("disabled", 180), ("enabled", 180)],
)
@pytest.mark.parametrize("schedule_request", [None, {}], ids=["omitted", "empty"])
def test_existing_subscription_create_disable_preview_matches_store_cascade(
    schedule_state,
    expected_interval,
    schedule_request,
    mutation_context,
):
    actor, source_id, subscription = _existing_create_schedule_target(
        mutation_context,
        suffix=f"create-disable-{schedule_state}-{schedule_request is None}",
        schedule_state=schedule_state,
    )

    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={"enabled": False},
        schedule=schedule_request,
    )
    expected = {"enabled": False, "interval_minutes": expected_interval}

    assert plan.payload["schedule_preview"] == expected
    assert plan.preview["schedule"] == expected
    restored = mutation_context["service"].restore_plan_snapshot(
        json.loads(json.dumps(plan.to_snapshot()))
    )
    result = mutation_context["service"].apply_plan(actor, restored)

    assert result["subscription"]["id"] == subscription["id"]
    assert result["subscription"]["enabled"] is False
    assert {
        "enabled": result["schedule"]["enabled"],
        "interval_minutes": result["schedule"]["interval_minutes"],
    } == expected


@pytest.mark.parametrize("existing_subscription", [False, True], ids=["new", "existing"])
def test_agent_create_rejects_disabled_existing_source(
    existing_subscription,
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    source_id = _create_shared_source(
        mutation_context,
        suffix=f"disabled-source-{existing_subscription}",
    )
    if existing_subscription:
        mutation_context["store"].create_subscription(
            user_id=actor.user_id,
            source_id=source_id,
            enabled=False,
        )
    mutation_context["store"].update_source(source_id, enabled=False)

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={"mode": "existing", "source_id": source_id},
            subscription={"enabled": True},
            schedule=None,
        )

    assert exc_info.value.code == "not_found"
    assert exc_info.value.status_code == 404


def test_existing_disabled_subscription_can_reenable_with_schedule_in_same_create_plan(
    mutation_context,
):
    actor, source_id, subscription = _existing_create_schedule_target(
        mutation_context,
        suffix="create-reenable-subscription",
        schedule_state="absent",
        subscription_enabled=False,
    )

    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={"enabled": True},
        schedule={"enabled": True, "interval_minutes": 180},
    )
    result = mutation_context["service"].apply_plan(actor, plan)

    assert result["subscription"]["id"] == subscription["id"]
    assert plan.preview["schedule"] == {"enabled": True, "interval_minutes": 180}
    assert result["schedule"]["enabled"] is True
    assert result["schedule"]["interval_minutes"] == 180


def test_create_apply_rolls_back_when_actual_schedule_differs_from_sealed_preview(
    mutation_context,
    monkeypatch,
):
    actor, source_id, subscription = _existing_create_schedule_target(
        mutation_context,
        suffix="create-final-schedule-binding",
        schedule_state="enabled",
    )
    before_subscription = mutation_context["store"].get_subscription(
        subscription["id"]
    )
    before_schedule = mutation_context["store"].get_source_schedule(subscription["id"])
    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={"enabled": False},
        schedule=None,
    )
    original_apply_schedule = mutation_context["service"]._apply_schedule

    def return_divergent_schedule(*args, **kwargs):
        actual = original_apply_schedule(*args, **kwargs)
        return {**actual, "enabled": not bool(actual["enabled"])}

    monkeypatch.setattr(
        mutation_context["service"], "_apply_schedule", return_divergent_schedule
    )

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "invalid_plan_snapshot"
    assert mutation_context["store"].get_subscription(subscription["id"]) == before_subscription
    assert mutation_context["store"].get_source_schedule(subscription["id"]) == before_schedule


def test_create_snapshot_rejects_enabled_schedule_after_final_subscription_disable(
    mutation_context,
):
    actor, source_id, _subscription = _existing_create_schedule_target(
        mutation_context,
        suffix="create-forged-final-schedule",
        schedule_state="enabled",
    )
    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={"enabled": False},
        schedule=None,
    )
    snapshot = plan.to_snapshot()
    snapshot["normalized"]["schedule_preview"]["enabled"] = True
    snapshot["preview"]["schedule"]["enabled"] = True

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].restore_plan_snapshot(snapshot)

    assert exc_info.value.code == "invalid_plan_snapshot"


def test_create_apply_live_binding_includes_existing_source_enabled_state(
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    source_id = _create_shared_source(
        mutation_context, suffix="create-source-enabled-live-binding"
    )
    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={"enabled": True},
        schedule=None,
    )
    mutation_context["store"].connect().execute(
        "UPDATE source_catalog SET enabled = 0 WHERE id = ?",
        (source_id,),
    )
    mutation_context["store"].connect().commit()

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "not_found"
    assert (
        mutation_context["store"].get_user_subscription_for_source(
            actor.user_id, source_id
        )
        is None
    )


def _create_schedule_update_target(
    context,
    *,
    suffix: str,
    existing_schedule: bool,
):
    actor = SubscriptionActor.from_user(context["member"])
    plan = context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": f"Schedule target {suffix}",
            "config": {"url": f"https://example.com/{suffix}.xml"},
        },
        subscription={},
        schedule=(
            {"enabled": True, "interval_minutes": 60}
            if existing_schedule
            else None
        ),
    )
    return actor, context["service"].apply_plan(actor, plan)


@pytest.mark.parametrize("disabled_target", ["source", "subscription"])
@pytest.mark.parametrize("existing_schedule", [False, True], ids=["missing", "existing"])
@pytest.mark.parametrize(
    "schedule_updates",
    [None, {}, {"interval_minutes": 180}, {"enabled": False}],
    ids=["omitted", "empty", "interval-only", "explicit-disable"],
)
def test_update_preview_and_apply_show_schedule_disable_cascade_final_state(
    disabled_target,
    existing_schedule,
    schedule_updates,
    mutation_context,
):
    suffix = (
        f"cascade-{disabled_target}-{existing_schedule}-"
        f"{repr(schedule_updates).replace(' ', '')}"
    )
    actor, created = _create_schedule_update_target(
        mutation_context,
        suffix=suffix,
        existing_schedule=existing_schedule,
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={"enabled": False} if disabled_target == "source" else None,
        subscription_updates=(
            {"enabled": False} if disabled_target == "subscription" else None
        ),
        schedule_updates=schedule_updates,
    )
    expected = {
        "enabled": False,
        "interval_minutes": (
            180 if schedule_updates == {"interval_minutes": 180} else 60
        ),
    }

    assert plan.payload["schedule_preview"] == expected
    assert plan.preview["schedule"] == expected
    restored = mutation_context["service"].restore_plan_snapshot(
        json.loads(json.dumps(plan.to_snapshot()))
    )
    result = mutation_context["service"].apply_plan(actor, restored)

    assert {
        "enabled": result["schedule"]["enabled"],
        "interval_minutes": result["schedule"]["interval_minutes"],
    } == expected


@pytest.mark.parametrize("existing_schedule", [False, True], ids=["missing", "existing"])
@pytest.mark.parametrize(
    ("schedule_updates", "expected_interval"),
    [
        (None, 60),
        ({}, 60),
        ({"interval_minutes": 180}, 180),
    ],
    ids=["omitted", "empty", "interval-only"],
)
def test_update_schedule_final_state_merges_live_state_and_requested_delta(
    existing_schedule,
    schedule_updates,
    expected_interval,
    mutation_context,
):
    suffix = f"merge-{existing_schedule}-{expected_interval}-{schedule_updates is None}"
    actor, created = _create_schedule_update_target(
        mutation_context,
        suffix=suffix,
        existing_schedule=existing_schedule,
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates=None,
        subscription_updates={"priority": 10},
        schedule_updates=schedule_updates,
    )
    expected = {
        "enabled": existing_schedule,
        "interval_minutes": expected_interval,
    }

    assert plan.payload["schedule_preview"] == expected
    assert plan.preview["schedule"] == expected
    result = mutation_context["service"].apply_plan(actor, plan)
    assert {
        "enabled": result["schedule"]["enabled"],
        "interval_minutes": result["schedule"]["interval_minutes"],
    } == expected


@pytest.mark.parametrize(
    "target_state",
    [
        "disable-source",
        "disable-subscription",
        "source-already-disabled",
        "subscription-already-disabled",
    ],
)
def test_update_rejects_explicit_schedule_enable_when_final_target_is_disabled(
    target_state,
    mutation_context,
):
    actor, created = _create_schedule_update_target(
        mutation_context,
        suffix=f"unavailable-{target_state}",
        existing_schedule=False,
    )
    source_updates = None
    subscription_updates = None
    if target_state == "disable-source":
        source_updates = {"enabled": False}
    elif target_state == "disable-subscription":
        subscription_updates = {"enabled": False}
    elif target_state == "source-already-disabled":
        mutation_context["store"].update_source(
            created["source"]["id"], enabled=False
        )
    else:
        mutation_context["store"].update_subscription(
            created["subscription"]["id"], enabled=False
        )

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_update(
            actor,
            subscription_id=created["subscription"]["id"],
            source_updates=source_updates,
            subscription_updates=subscription_updates,
            schedule_updates={"enabled": True},
        )

    assert exc_info.value.code == "source_schedule_unavailable"
    assert exc_info.value.status_code == 409


@pytest.mark.parametrize("reenabled_target", ["source", "subscription"])
def test_update_allows_schedule_enable_when_same_plan_reenables_final_target(
    reenabled_target,
    mutation_context,
):
    actor, created = _create_schedule_update_target(
        mutation_context,
        suffix=f"reenable-{reenabled_target}",
        existing_schedule=False,
    )
    if reenabled_target == "source":
        mutation_context["store"].update_source(
            created["source"]["id"], enabled=False
        )
        source_updates = {"enabled": True}
        subscription_updates = None
    else:
        mutation_context["store"].update_subscription(
            created["subscription"]["id"], enabled=False
        )
        source_updates = None
        subscription_updates = {"enabled": True}

    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates=source_updates,
        subscription_updates=subscription_updates,
        schedule_updates={"enabled": True, "interval_minutes": 180},
    )
    result = mutation_context["service"].apply_plan(actor, plan)

    assert plan.preview["schedule"] == {
        "enabled": True,
        "interval_minutes": 180,
    }
    assert result["schedule"]["enabled"] is True
    assert result["schedule"]["interval_minutes"] == 180


def test_update_snapshot_rejects_forged_enabled_schedule_after_subject_disable(
    mutation_context,
):
    actor, created = _create_schedule_update_target(
        mutation_context,
        suffix="forged-final-schedule",
        existing_schedule=True,
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates={"enabled": False},
        subscription_updates=None,
        schedule_updates=None,
    )
    snapshot = plan.to_snapshot()
    snapshot["normalized"]["schedule_preview"]["enabled"] = True
    snapshot["preview"]["schedule"]["enabled"] = True

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].restore_plan_snapshot(snapshot)

    assert exc_info.value.code == "invalid_plan_snapshot"


def test_update_apply_live_binding_includes_complete_final_schedule_snapshot(
    mutation_context,
):
    actor, created = _create_schedule_update_target(
        mutation_context,
        suffix="schedule-live-binding",
        existing_schedule=True,
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=created["subscription"]["id"],
        source_updates=None,
        subscription_updates={"priority": 10},
        schedule_updates=None,
    )
    mutation_context["store"].connect().execute(
        """
        UPDATE user_source_schedules
        SET enabled = 0, next_run_at = NULL
        WHERE subscription_id = ?
        """,
        (created["subscription"]["id"],),
    )
    mutation_context["store"].connect().commit()

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "invalid_plan_snapshot"


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


@pytest.mark.parametrize(
    ("url", "secret_text"),
    [
        (
            "https://example.com/feed#" + "AIza" + "A" * 35,
            "AIza" + "A" * 35,
        ),
        (
            "https://example.com/feed#gsk%255F" + "B" * 32,
            "gsk%255F" + "B" * 32,
        ),
        (
            "https://example.com/feed#ｈｆ＿" + "C" * 32,
            "ｈｆ＿" + "C" * 32,
        ),
    ],
    ids=["raw-aiza-fragment", "encoded-gsk-fragment", "fullwidth-hf-fragment"],
)
def test_projector_makes_known_prefix_fragments_opaque_without_echo(
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
        display_name="Legacy fragment source",
        config={"url": url},
        source_key=f"legacy-prefix-fragment:{len(secret_text)}:{url[-1]}",
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


@pytest.mark.parametrize("display_name", ["Bearer Market Report", "SK-Internationalization"])
def test_projector_keeps_safe_business_title_public(display_name, mutation_context):
    member = mutation_context["member"]
    source_id = mutation_context["store"].create_source(
        workspace_id=member["workspace_id"],
        scope="private",
        owner_user_id=member["id"],
        source_type="rss",
        display_name=display_name,
        config={"url": "https://example.com/bearer-market-report.xml"},
        source_key=f"rss:https://example.com/{display_name.lower()}.xml",
    )
    actor = SubscriptionActor.from_user(member)

    plan = mutation_context["service"].plan_create(
        actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={},
        schedule=None,
    )

    assert plan.preview["source"] == {
        "display_name": display_name,
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


def test_agent_bilibili_create_keeps_rsshub_origin_out_of_plan_and_catalog(
    mutation_context,
    monkeypatch,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    plan = mutation_context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "bilibili",
            "display_name": "食贫道",
            "config": {
                "site": "bilibili",
                "route_key": "user_video",
                "params": {"uid": "39627524"},
            },
        },
        subscription={},
        schedule=None,
    )

    assert plan.preview["source"] == {
        "display_name": "食贫道",
        "type": "bilibili",
        "public_target": {
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "39627524"},
        },
    }
    assert "rsshub:1200" not in repr(plan.to_snapshot()).lower()

    created = mutation_context["service"].apply_plan(actor, plan)
    source = mutation_context["store"].get_source(created["source"]["id"])
    assert source["type"] == "rss"
    assert source["source_key"] == "rss:rsshub:bilibili:user_video:39627524"
    assert source["enforce_public_network"] is False
    assert source["config"]["url"] == "https://space.bilibili.com/39627524"

    monkeypatch.setattr(
        "src.services.worker.StorageManager.load_config",
        lambda _self: SimpleNamespace(
            rsshub=SimpleNamespace(base_url="https://rsshub.example.com")
        ),
    )
    worker_payload = _source_payload_from_catalog(
        {"source_id": source["id"], "payload_json": {}},
        store=mutation_context["store"],
    )
    assert worker_payload["url"] == (
        "https://rsshub.example.com/bilibili/user/video/39627524/1"
    )
    assert worker_payload["enforce_public_network"] is False


@pytest.mark.parametrize("agent_type", ["apify"])
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


@pytest.mark.parametrize(
    "display_name",
    [
        "Feed " + "AIza" + "A" * 35,
        "Feed%20gsk%255F" + "B" * 32,
        "Feed ｈｆ＿" + "C" * 32,
    ],
    ids=["raw-aiza", "encoded-gsk", "fullwidth-hf"],
)
def test_agent_create_rejects_embedded_known_prefixes_in_private_metadata(
    display_name,
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": display_name,
                "config": {"url": "https://example.com/private-prefix.xml"},
            },
            subscription={},
            schedule=None,
        )

    assert exc_info.value.code == "invalid_source_config"
    assert str(exc_info.value) == "credentials are not accepted; configure secrets in Web"
    assert display_name not in str(exc_info.value)


def test_agent_metadata_classifier_fails_closed_without_echoing_parser_errors(
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    display_name = "https://alice:do-not-echo@[broken"

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].plan_create(
            actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": display_name,
                "config": {"url": "https://example.com/parser-failure.xml"},
            },
            subscription={},
            schedule=None,
        )

    assert exc_info.value.code == "invalid_source_config"
    assert str(exc_info.value) == "credentials are not accepted; configure secrets in Web"
    assert "do-not-echo" not in str(exc_info.value)


def test_agent_create_keeps_safe_long_sk_business_title(mutation_context):
    actor = SubscriptionActor.from_user(mutation_context["member"])

    plan = mutation_context["service"].plan_create(
        actor,
        source={
            "mode": "private",
            "type": "rss",
            "display_name": "SK-Internationalization",
            "config": {"url": "https://example.com/internationalization.xml"},
        },
        subscription={},
        schedule=None,
    )

    assert plan.preview["source"]["display_name"] == "SK-Internationalization"


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


def test_shared_source_reuse_uses_content_item_native_title_not_donor_ai_title(
    mutation_context,
):
    store = mutation_context["store"]
    workspace = mutation_context["workspace"]
    owner = mutation_context["owner"]
    member = mutation_context["member"]
    source_id = _create_shared_source(
        mutation_context,
        suffix="reuse-native-title",
    )
    owner_subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    donor = ContentItem(
        id="rss:reuse:native-title",
        source_type=SourceType.RSS,
        title="CANONICAL_SOURCE_TITLE",
        url="https://example.com/reuse-native-title/article",
        content="Canonical source excerpt",
        author="Canonical author",
        published_at=datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc),
        metadata={
            "title_zh": "DONOR_AI_TRANSLATED_TITLE",
            "source_id": source_id,
            "source_ids": [source_id],
            "subscription_id": owner_subscription["id"],
            "subscription_ids": [owner_subscription["id"]],
            "source_key": "rss:https://example.com/reuse-native-title.xml",
            "source_keys": ["rss:https://example.com/reuse-native-title.xml"],
            "source_display_name": "Shared RSS",
            "catalog_source_type": "rss",
            "analysis_mode": "full",
        },
    )
    serialized = serialize_feed_item(donor, featured_threshold=8.0)
    assert serialized["title"] == "DONOR_AI_TRANSLATED_TITLE"
    assert (
        serialized[INTERNAL_SOURCE_NATIVE_TITLE_KEY]
        == "CANONICAL_SOURCE_TITLE"
    )
    owner_snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-owner-reuse-native-title",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-24T01:10:00+00:00",
            "items": [serialized],
        },
    )
    stored_owner = store.connect().execute(
        """
        SELECT source_native_title, item_json
        FROM user_content_items
        WHERE workspace_id = ? AND user_id = ? AND article_id = ?
        """,
        (workspace["id"], owner["id"], donor.id),
    ).fetchone()
    assert stored_owner["source_native_title"] == "CANONICAL_SOURCE_TITLE"
    assert INTERNAL_SOURCE_NATIVE_TITLE_KEY not in stored_owner["item_json"]
    assert INTERNAL_SOURCE_NATIVE_TITLE_KEY not in json.dumps(
        owner_snapshot["payload"],
        ensure_ascii=False,
        sort_keys=True,
    )
    owner_feed_item_json = store.connect().execute(
        """
        SELECT item_json FROM user_feed_items
        WHERE workspace_id = ? AND user_id = ? AND article_id = ?
        """,
        (workspace["id"], owner["id"], donor.id),
    ).fetchone()["item_json"]
    assert INTERNAL_SOURCE_NATIVE_TITLE_KEY not in owner_feed_item_json
    member_subscription = store.create_subscription(
        user_id=member["id"],
        source_id=source_id,
    )

    result = UserFeedStore(store).reuse_source_content(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=member_subscription["id"],
    )

    assert result["reused_count"] == 1
    member_item = result["snapshot"]["payload"]["items"][0]
    assert member_item["title"] == "CANONICAL_SOURCE_TITLE"
    assert member_item["presentation"]["content"]["title"] == "CANONICAL_SOURCE_TITLE"
    assert "DONOR_AI_TRANSLATED_TITLE" not in json.dumps(
        result["snapshot"]["payload"],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert INTERNAL_SOURCE_NATIVE_TITLE_KEY not in json.dumps(
        result["snapshot"]["payload"],
        ensure_ascii=False,
        sort_keys=True,
    )
    stored_member_title = store.connect().execute(
        """
        SELECT source_native_title FROM user_content_items
        WHERE workspace_id = ? AND user_id = ? AND article_id = ?
        """,
        (workspace["id"], member["id"], donor.id),
    ).fetchone()["source_native_title"]
    assert stored_member_title == "CANONICAL_SOURCE_TITLE"
    latest_owner = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )
    assert latest_owner is not None
    assert latest_owner["id"] == owner_snapshot["id"]
    assert latest_owner["payload"]["items"][0]["title"] == "DONOR_AI_TRANSLATED_TITLE"


def test_shared_source_reuse_skips_legacy_donor_without_native_title(
    mutation_context,
):
    store = mutation_context["store"]
    workspace = mutation_context["workspace"]
    owner = mutation_context["owner"]
    member = mutation_context["member"]
    source_id = _create_shared_source(
        mutation_context,
        suffix="reuse-legacy-title",
    )
    owner_subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-owner-reuse-legacy-title",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-24T01:10:00+00:00",
            "items": [
                {
                    "id": "rss:reuse:legacy-title",
                    "title": "UNPROVEN_DONOR_DISPLAY_TITLE",
                    "source_id": source_id,
                    "subscription_id": owner_subscription["id"],
                    "presentation": {
                        "content": {
                            "title": "UNPROVEN_PRESENTATION_TITLE",
                        }
                    },
                }
            ],
        },
    )
    member_subscription = store.create_subscription(
        user_id=member["id"],
        source_id=source_id,
    )

    result = UserFeedStore(store).reuse_source_content(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=member_subscription["id"],
    )

    assert result == {"reused_count": 0, "snapshot": None}
    assert UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=member["id"],
    ) is None


def test_shared_source_reuse_reprojects_donor_content_for_target_user(
    mutation_context,
):
    store = mutation_context["store"]
    workspace = mutation_context["workspace"]
    owner = mutation_context["owner"]
    member = mutation_context["member"]
    source_id = _create_shared_source(mutation_context, suffix="reuse-isolation")
    owner_subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
        override_channel="Owner Channel",
        override_topics=["Owner Topic"],
        personal_tags=["Owner Personal"],
        analysis_mode="full",
        priority=91,
    )
    store.connect().execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, user_id, source_id, article_id, asset_kind,
            remote_url, local_path, mime_type, byte_size, checksum, alt,
            visibility_scope, status, created_at, updated_at
        ) VALUES (
            'med-current-source-avatar', ?, NULL, ?, NULL, 'source_avatar',
            '', 'media/current-source-avatar.png', 'image/png', 3,
            'current-source-avatar-sum', 'Shared RSS', 'workspace', 'ready',
            '2026-07-24T00:00:00+00:00', '2026-07-24T00:00:00+00:00'
        )
        """,
        (workspace["id"], source_id),
    )
    store.connect().commit()
    owner_payload = {
        "id": "rss:reuse:isolation",
        "title": "Canonical donor title",
        INTERNAL_SOURCE_NATIVE_TITLE_KEY: "Canonical donor title",
        "source": "Shared RSS",
        "source_type": "rss",
        "author": "Canonical author",
        "url": "https://example.com/reuse-isolation/article",
        "discussion_url": "https://example.com/reuse-isolation/discussion",
        "published_at": "2026-07-24T01:00:00+00:00",
        "fetched_at": "2026-07-24T01:05:00+00:00",
        "source_id": source_id,
        "source_ids": [source_id],
        "subscription_id": owner_subscription["id"],
        "subscription_ids": [owner_subscription["id"]],
        "source_priority": 91,
        "channel": "Owner Channel",
        "category": "Owner Channel",
        "topics": ["Owner Topic"],
        "tags": ["Owner Topic"],
        "personal_tags": ["Owner Personal"],
        "analysis_mode": "full",
        "interest_score": 9.5,
        "show_in_personal_feed": True,
        "score": 9.8,
        "summary_zh": "OWNER_AI_SUMMARY",
        "signal_strength": "strong",
        "signal_type": "owner_signal",
        "entities": ["Owner Entity"],
        "is_featured": True,
        "show_on_featured_home": True,
        "image_url": "/api/media/owner-private-image",
        "media_urls": ["/api/media/owner-private-image"],
        "user_state": {
            "is_read": True,
            "is_saved": True,
            "is_later": True,
            "dismissed": True,
        },
        "presentation": {
            "version": 1,
            "source": {
                "id": source_id,
                "catalog_type": "rss",
                "platform": "rss",
                "name": "Shared RSS",
                "avatar_url": "/api/media/owner-private-avatar",
            },
            "author": {"name": "Canonical author", "kind": "person"},
            "timing": {
                "published_at": "2026-07-24T01:00:00+00:00",
                "fetched_at": "2026-07-24T01:05:00+00:00",
            },
            "links": {
                "canonical_url": "https://example.com/reuse-isolation/article",
                "source_url": "https://example.com/reuse-isolation/discussion",
            },
            "content": {
                "title": "Canonical donor title",
                "title_origin": "native",
                "excerpt": "Canonical excerpt",
                "content_kind": "feed_summary",
                "excerpt_truncated": False,
                "body_text": "Canonical captured body",
                "body_truncated": False,
                "body_completeness": "captured",
                "unresolved_reason": "",
            },
            "taxonomy": {
                "channel": "Owner Channel",
                "configured_topics": ["Owner Topic"],
                "inferred_topics": ["Owner Inferred"],
                "topics": ["Owner Topic", "Owner Inferred"],
                "entities": ["Owner Entity"],
            },
            "engagement": {
                "native_score": 12,
                "likes": 3,
                "comments": 2,
                "reposts": None,
                "shares": None,
                "upvote_ratio": None,
            },
            "analysis": {
                "status": "ai",
                "score": 9.8,
                "signal_strength": "strong",
                "signal_type": "owner_signal",
                "summary_zh": "OWNER_AI_SUMMARY",
                "action_suggestion": "OWNER_AI_ACTION",
            },
            "media": {
                "images": [
                    {
                        "asset_id": "owner-private-image",
                        "url": "/api/media/owner-private-image",
                    }
                ],
                "count": 1,
                "total_image_count": 1,
                "truncated": False,
            },
        },
    }
    legacy_ai_only_payload = {
        "id": "rss:reuse:legacy-ai-only",
        "title": "Legacy canonical title",
        "source_id": source_id,
        "source_ids": [source_id],
        "subscription_id": owner_subscription["id"],
        "subscription_ids": [owner_subscription["id"]],
        "summary_zh": "OWNER_LEGACY_AI_BODY",
    }
    owner_snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-owner-reuse-isolation",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-24T01:10:00+00:00",
            "items": [owner_payload, legacy_ai_only_payload],
        },
    )
    feed_store = UserFeedStore(store)
    assert feed_store.reuse_source_content(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=owner_subscription["id"],
    ) == {"reused_count": 0, "snapshot": None}
    unrelated_source_id = _create_shared_source(
        mutation_context,
        suffix="reuse-isolation-unrelated",
    )
    unrelated_subscription = store.create_subscription(
        user_id=member["id"],
        source_id=unrelated_source_id,
    )
    assert feed_store.reuse_source_content(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=unrelated_subscription["id"],
    ) == {"reused_count": 0, "snapshot": None}
    member_subscription = store.create_subscription(
        user_id=member["id"],
        source_id=source_id,
        enabled=False,
    )
    assert feed_store.reuse_source_content(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=member_subscription["id"],
    ) == {"reused_count": 0, "snapshot": None}
    assert feed_store.latest_snapshot(
        workspace_id=workspace["id"],
        user_id=member["id"],
    ) is None

    member_result = mutation_context["service"].rest_create_subscription(
        SubscriptionActor.from_user(member),
        source_id=source_id,
        values={
            "enabled": True,
            "override_channel": "Member Channel",
            "override_topics": ["Member Topic"],
            "personal_tags": ["Member Personal"],
            "analysis_mode": "personal_only",
            "priority": 7,
        },
    )
    member_snapshot = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=member["id"],
    )

    assert member_result["reused_item_count"] == 1
    assert member_snapshot is not None
    member_item = next(
        item
        for item in member_snapshot["payload"]["items"]
        if item["id"] == owner_payload["id"]
    )
    assert [item["id"] for item in member_snapshot["payload"]["items"]] == [
        owner_payload["id"]
    ]
    assert member_item["id"] == owner_payload["id"]
    assert member_item["title"] == "Canonical donor title"
    assert member_item["subscription_id"] == member_result["id"]
    assert member_item["subscription_ids"] == [member_result["id"]]
    assert member_item["source_id"] == source_id
    assert member_item["source_ids"] == [source_id]
    assert member_item["source_priority"] == 7
    assert member_item["channel"] == "Member Channel"
    assert member_item["topics"] == ["Member Topic"]
    assert member_item["personal_tags"] == ["Member Personal"]
    assert member_item["analysis_mode"] == "personal_only"
    assert member_item["presentation"]["taxonomy"] == {
        "channel": "Member Channel",
        "configured_topics": ["Member Topic"],
        "inferred_topics": [],
        "topics": ["Member Topic"],
        "entities": [],
    }
    assert member_item["presentation"]["analysis"]["status"] == "personal_only"
    assert member_item["presentation"]["analysis"]["score"] == 0
    assert member_item["presentation"]["analysis"]["summary_zh"] == "Canonical excerpt"
    assert (
        member_item["presentation"]["source"]["avatar_url"]
        == "/api/media/med-current-source-avatar"
    )
    assert "user_state" not in member_item
    assert member_item["image_url"] == ""
    assert member_item["media_urls"] == []
    serialized_member = json.dumps(
        member_snapshot["payload"]["items"],
        ensure_ascii=False,
        sort_keys=True,
    )
    for owner_only in (
        "Owner Channel",
        "Owner Topic",
        "Owner Personal",
        "Owner Inferred",
        "Owner Entity",
        "OWNER_AI_SUMMARY",
        "OWNER_AI_ACTION",
        "OWNER_LEGACY_AI_BODY",
        "owner_signal",
        "owner-private-avatar",
        "owner-private-image",
    ):
        assert owner_only not in serialized_member
    latest_owner_snapshot = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )
    assert latest_owner_snapshot is not None
    assert latest_owner_snapshot["id"] == owner_snapshot["id"]
    assert latest_owner_snapshot["payload"] == owner_snapshot["payload"]


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


@pytest.mark.parametrize(
    ("source_type", "initial_config", "valid_update", "invalid_update"),
    [
        (
            "github_release",
            {"owner": "openai", "repo": "codex"},
            {"owner": "anthropics", "repo": "claude-code"},
            {"owner": "-invalid", "repo": "claude-code"},
        ),
        (
            "reddit_subreddit",
            {"subreddit": "LocalLLaMA"},
            {"subreddit": "python"},
            {"subreddit": "python/comments/abc/post"},
        ),
        (
            "telegram_channel",
            {"channel": "durov"},
            {"channel": "openai"},
            {"channel": "proxy"},
        ),
    ],
)
def test_agent_catalog_config_updates_share_canonical_reverse_validator(
    source_type,
    initial_config,
    valid_update,
    invalid_update,
    mutation_context,
):
    actor = SubscriptionActor.from_user(mutation_context["member"])
    normalized_initial = validate_source_config(source_type, initial_config)
    source_id = mutation_context["store"].create_source(
        workspace_id=actor.workspace_id,
        scope="private",
        owner_user_id=actor.user_id,
        source_type=source_type,
        display_name=f"Reverse update {source_type}",
        config=normalized_initial,
        source_key=source_key(source_type, normalized_initial),
    )
    subscription = mutation_context["store"].create_subscription(
        user_id=actor.user_id,
        source_id=source_id,
    )
    valid_plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription["id"],
        source_updates={"config": valid_update},
        subscription_updates=None,
        schedule_updates=None,
    )

    with pytest.raises(SubscriptionMutationError) as planning_error:
        mutation_context["service"].plan_update(
            actor,
            subscription_id=subscription["id"],
            source_updates={"config": invalid_update},
            subscription_updates=None,
            schedule_updates=None,
        )
    assert planning_error.value.code == "invalid_source_config"

    forged = valid_plan.to_snapshot()
    invalid_normalized = validate_source_config(source_type, invalid_update)
    forged["normalized"]["source_updates"]["config"] = invalid_normalized
    forged["normalized"]["source_updates"]["source_key"] = source_key(
        source_type, invalid_normalized
    )
    with pytest.raises(SubscriptionMutationError) as restore_error:
        mutation_context["service"].restore_plan_snapshot(forged)
    assert restore_error.value.code == "invalid_plan_snapshot"


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


def _inactive_private_quota_target(
    context,
    *,
    suffix: str,
    source_enabled: bool,
    subscription_enabled: bool,
):
    actor, _active = _create_private_subscription(
        context, suffix=f"active-capacity-{suffix}"
    )
    context["quota"].max_sources_per_user = 1
    source_id = context["store"].create_source(
        workspace_id=actor.workspace_id,
        scope="private",
        owner_user_id=actor.user_id,
        source_type="rss",
        display_name=f"Inactive quota target {suffix}",
        config={"url": f"https://example.com/inactive-quota-{suffix}.xml"},
        source_key=f"rss:https://example.com/inactive-quota-{suffix}.xml",
        enabled=source_enabled,
    )
    subscription = context["store"].create_subscription(
        user_id=actor.user_id,
        source_id=source_id,
        enabled=subscription_enabled,
    )
    return actor, source_id, subscription


def test_subscription_update_on_disabled_source_is_quota_neutral(mutation_context):
    actor, source_id, subscription = _inactive_private_quota_target(
        mutation_context,
        suffix="disabled-source-update",
        source_enabled=False,
        subscription_enabled=False,
    )

    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription["id"],
        source_updates=None,
        subscription_updates={"enabled": True},
        schedule_updates=None,
    )
    result = mutation_context["service"].apply_plan(actor, plan)

    assert result["subscription"]["enabled"] is True
    assert mutation_context["store"].get_source(source_id)["enabled"] is False


def test_same_plan_source_disable_and_subscription_enable_is_quota_neutral(
    mutation_context,
):
    actor, source_id, subscription = _inactive_private_quota_target(
        mutation_context,
        suffix="same-plan-disable-enable",
        source_enabled=True,
        subscription_enabled=False,
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription["id"],
        source_updates={"enabled": False},
        subscription_updates={"enabled": True},
        schedule_updates=None,
    )

    result = mutation_context["service"].apply_plan(actor, plan)

    assert result["source"]["enabled"] is False
    assert result["subscription"]["enabled"] is True


def test_subscription_enable_on_enabled_source_still_obeys_active_quota(
    mutation_context,
):
    actor, source_id, subscription = _inactive_private_quota_target(
        mutation_context,
        suffix="enabled-source",
        source_enabled=True,
        subscription_enabled=False,
    )
    plan = mutation_context["service"].plan_update(
        actor,
        subscription_id=subscription["id"],
        source_updates=None,
        subscription_updates={"enabled": True},
        schedule_updates=None,
    )

    with pytest.raises(SubscriptionMutationError) as exc_info:
        mutation_context["service"].apply_plan(actor, plan)

    assert exc_info.value.code == "quota_exceeded"
    assert mutation_context["store"].get_subscription(subscription["id"])[
        "enabled"
    ] is False
    assert mutation_context["store"].get_source(source_id)["enabled"] is True


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
    # Both choices preserve the source definition.  The final private
    # subscription removal soft-disables it in either case so there is no
    # ownerless polling lifecycle.
    ("disposition", "source_enabled"), (("keep", False), ("disable_private", False))
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


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("revocation", ["user", "source"])
def test_rest_notification_mutation_rechecks_actor_and_source_inside_lock(
    mutation_context,
    monkeypatch,
    operation,
    revocation,
):
    source_id = _create_shared_source(
        mutation_context,
        suffix=f"notification-race-{operation}-{revocation}",
    )
    actor = SubscriptionActor.from_user(mutation_context["member"])
    subscription = None
    if operation == "update":
        subscription = mutation_context["service"].rest_create_subscription(
            actor,
            source_id=source_id,
            values={"notify_on_new_items": False},
        )
    admin_store = ServiceStore(mutation_context["data_dir"])
    admin_store.initialize()
    original_live_actor = mutation_context["service"]._live_actor
    live_checks = 0

    def revoke_after_outer_check(candidate):
        nonlocal live_checks
        user = original_live_actor(candidate)
        live_checks += 1
        if live_checks == 1:
            if revocation == "user":
                admin_store.update_user(actor.user_id, enabled=False)
            else:
                admin_store.update_source(source_id, enabled=False)
        return user

    monkeypatch.setattr(
        mutation_context["service"],
        "_live_actor",
        revoke_after_outer_check,
    )

    with pytest.raises(SubscriptionMutationError) as exc_info:
        if operation == "create":
            mutation_context["service"].rest_create_subscription(
                actor,
                source_id=source_id,
                values={"notify_on_new_items": True},
            )
        else:
            mutation_context["service"].rest_update_subscription(
                actor,
                subscription_id=subscription["id"],
                updates={"notify_on_new_items": True},
            )

    if revocation == "user":
        assert exc_info.value.code == "not_found"
    else:
        assert exc_info.value.code in {
            "not_found",
            "invalid_subscription_notification",
        }
    if subscription is None:
        assert (
            admin_store.get_user_subscription_for_source(
                actor.user_id,
                source_id,
            )
            is None
        )
    else:
        stored = admin_store.get_subscription(subscription["id"])
        assert stored is not None
        assert stored["notify_on_new_items"] is False
        assert stored["notification_enabled_at"] is None
    admin_store.close()
