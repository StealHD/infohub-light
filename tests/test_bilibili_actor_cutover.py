"""Bilibili catalog compatibility and offline data-cutover safety."""

import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from scripts.migrate_bilibili_actor_sources import migrate
from src.models import ApifySocialSubscriptionConfig, RSSSourceConfig
from src.scrapers.base import SourceFetchError
from src.scrapers.rss import RSSScraper
from src.services.apify_actor_source_runtime import with_actorops_runtime_profiles
from src.services.actorops.binding_service import ActorOpsBindingService
from src.services.actorops.source_lifecycle import ActorOpsSourceLifecycle
from src.services.source_type_registry import validate_source_config
from src.services.user_config_builder import build_user_config_data
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _source(store, uid, *, enabled=True):
    return store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
        source_type="rss", display_name=f"UP {uid}", enabled=enabled,
        config=validate_source_config("rss", {"provider": "rsshub", "site": "bilibili",
                                              "route_key": "user_video", "params": {"uid": uid}}),
    )


def test_preview_and_repeated_apply_preserve_disabled_sources_and_catalog(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    active = _source(store, "39627524")
    disabled = _source(store, "123", enabled=False)
    before = {source_id: store.get_source(source_id) for source_id in (active, disabled)}
    # Simulate an existing DB whose migration markers predate this new route.
    connection = store.connect()
    connection.execute("DELETE FROM actor_maintenance_policies_v2 WHERE route_id IN (SELECT route_id FROM actor_routes_v2 WHERE platform='bilibili')")
    connection.execute("DELETE FROM actor_routes_v2 WHERE platform='bilibili'")
    connection.commit()
    store.close()
    database = tmp_path / "service.db"
    original = database.read_bytes()
    preview = migrate(tmp_path)
    assert preview["status"] == "preview"
    assert preview["routes_required"] == 1
    assert database.read_bytes() == original
    result = migrate(tmp_path, apply=True, services_stopped=True)
    assert result["status"] == "applied"
    assert (tmp_path / "backups").joinpath(result["backup_path"]).stat().st_mode & 0o777 == 0o600
    assert migrate(tmp_path, apply=True, services_stopped=True)["status"] == "already_applied"
    store = ServiceStore(tmp_path)
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    assert service.repository.get_binding(active).status == "pending"
    assert service.repository.get_binding(disabled).status == "disabled"
    for source_id in (active, disabled):
        after = store.get_source(source_id)
        assert after["source_key"] == before[source_id]["source_key"]
        assert after["config"] == before[source_id]["config"]
        assert after["enabled"] is False
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
    store.close()


def test_cutover_blocks_live_worker_and_nonempty_queue(tmp_path, monkeypatch):
    store = ServiceStore(tmp_path)
    store.initialize()
    _source(store, "39627524")
    store.close()
    monkeypatch.setattr("scripts.migrate_bilibili_actor_sources.active_workers_fail_closed", lambda _: ["worker"])
    assert migrate(tmp_path)["status"] == "blocked"
    with pytest.raises(RuntimeError, match="stop API/Worker"):
        migrate(tmp_path, apply=True, services_stopped=True)
    assert not (tmp_path / "backups").exists()


def test_new_bilibili_source_is_managed_and_pending_never_projects_as_rss(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    source_id = _source(store, "39627524")
    with store.connect():
        store.connect().execute("BEGIN IMMEDIATE")
        ActorOpsSourceLifecycle(store, workspace_id=DEFAULT_WORKSPACE_ID).after_create(source_id)
    source = store.get_source(source_id)
    binding = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID).repository.get_binding(source_id)
    assert binding.status == "pending" and source["enabled"] is False
    projected = with_actorops_runtime_profiles(store, workspace_id=DEFAULT_WORKSPACE_ID,
                                               records=[{**source, "source_id": source_id}])[0]
    assert projected["type"] == "apify_social"
    assert projected["config"]["enabled"] is False
    assert projected["config"]["target"] == "https://space.bilibili.com/39627524"
    store.close()


def test_unbound_old_subscription_cannot_fall_back_to_rsshub(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    source_id = _source(store, "39627524")
    source = store.get_source(source_id)
    record = {**source, "source_id": source_id}
    projected = with_actorops_runtime_profiles(store, workspace_id=DEFAULT_WORKSPACE_ID, records=[record])[0]
    assert projected["type"] == "apify_social"
    assert projected["config"]["enabled"] is False
    store.close()


def test_ready_subscription_keeps_ids_overrides_window_and_fetch_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    user = store.get_user_by_username("owner")
    source_id = _source(store, "39627524")
    subscription_id = store.create_subscription(user_id=user["id"], source_id=source_id,
                                                personal_tags=["private"], analysis_mode="personal_only")
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    service.ensure(source_id)
    store.connect().execute("UPDATE actor_source_bindings_v2 SET status='ready' WHERE source_id=?", (source_id,))
    store.connect().execute("UPDATE source_catalog SET enabled=1 WHERE id=?", (source_id,))
    store.connect().commit()
    data = build_user_config_data(store=store, workspace_id=DEFAULT_WORKSPACE_ID, user_id=user["id"],
                                  base_config={"filtering": {"rss_initial_fetch_window_hours": 720}})
    assert data["sources"]["rss"] == []
    entry = data["sources"]["apify_social"]["subscriptions"][0]
    assert entry["source_id"] == source_id and entry["subscription_id"] == subscription_id["id"]
    assert entry["catalog_source_type"] == "rss" and entry["platform"] == "bilibili"
    assert entry["analysis_mode"] == "personal_only" and entry["personal_tags"] == ["private"]
    assert entry["service_fetch_window_hours"] == 720
    assert ApifySocialSubscriptionConfig.model_validate(entry).profile_id
    store.close()


def test_direct_rss_fetch_rejects_bilibili_before_any_network():
    import asyncio
    source = RSSSourceConfig(name="Bili", url="http://rsshub:1200/bilibili/user/video/39627524/1",
                             provider="rsshub", site="bilibili", route_key="user_video", params={"uid": "39627524"})
    client = AsyncMock()
    with pytest.raises(SourceFetchError, match="ActorOps"):
        asyncio.run(RSSScraper([source], client).fetch(datetime.now(timezone.utc)))
    client.get.assert_not_called()


def test_cutover_blocks_queued_work_before_backup(tmp_path, monkeypatch):
    from src.services.job_queue import JobQueue
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    source_id = _source(store, "39627524")
    JobQueue(store).create_job(workspace_id=DEFAULT_WORKSPACE_ID,
                              user_id=store.get_user_by_username("owner")["id"],
                              job_type="source_fetch", source_id=source_id)
    store.close()
    assert migrate(tmp_path)["blockers"]["jobs"] == 1
    with pytest.raises(RuntimeError, match="drain the queue"):
        migrate(tmp_path, apply=True, services_stopped=True)
    assert not (tmp_path / "backups").exists()


def test_cutover_rolls_back_partial_binding_changes(tmp_path, monkeypatch):
    from src.storage.bilibili_actor_cutover import apply_cutover, cutover_counts
    store = ServiceStore(tmp_path)
    store.initialize()
    source_id = _source(store, "39627524")
    before = cutover_counts(store.connect())
    store.close()

    def fail_after_bindings(store):
        apply_cutover(store)
        raise RuntimeError("test postcheck failure")

    monkeypatch.setattr("scripts.migrate_bilibili_actor_sources.apply_cutover", fail_after_bindings)
    with pytest.raises(RuntimeError, match="postcheck failure"):
        migrate(tmp_path, apply=True, services_stopped=True)
    store = ServiceStore(tmp_path)
    assert cutover_counts(store.connect()) == before
    assert store.get_source(source_id)["enabled"] is True
    store.close()


def test_history_read_saved_and_notification_dedup_survive_cutover(tmp_path, monkeypatch):
    from src.services.user_item_state import UserItemStateStore
    from src.services.user_feed_store import UserFeedStore
    from tests.test_preferred_source_notifications import _notification_context, _job, _item, _save_snapshot
    from tests.test_bilibili_actor_adapter import UID, URL, KEY, WINDOW, manifest, row
    from src.services.actorops.adapters import build_default_registry
    from src.services.actorops.identity import legacy_rss_item_id

    ctx = _notification_context(tmp_path, monkeypatch)
    store = ctx["store"]
    source_key = f"rss:rsshub:bilibili:user_video:{UID}"
    config = validate_source_config("rss", {"provider": "rsshub", "site": "bilibili",
                                            "route_key": "user_video", "params": {"uid": UID}})
    store.connect().execute("UPDATE source_catalog SET config_json=?, source_key=? WHERE id=?",
                            (json.dumps(config), source_key, ctx["source_id"]))
    store.connect().commit()
    old_id = legacy_rss_item_id(source_key, URL, managed=True)
    UserFeedStore(store).save_snapshot(workspace_id=DEFAULT_WORKSPACE_ID, user_id=ctx["user"]["id"],
                                     job_id="seed", payload={"generated_at": "2026-10-08T00:00:00Z", "items": []})
    first_job = _job(ctx)
    first = _save_snapshot(ctx, first_job, [_item(ctx, old_id, published_at="2026-10-09T00:00:00Z", url=URL)],
                           generated_at="2026-10-10T00:00:00Z")
    assert ctx["service"].stage_for_job(job=first_job, snapshot_id=first["id"], snapshot_created=True) == 1
    store.connect().execute("UPDATE fetch_jobs SET status='succeeded' WHERE id=?", (first_job["id"],))
    store.connect().commit()
    states = UserItemStateStore(store)
    states.update_state(workspace_id=DEFAULT_WORKSPACE_ID, user_id=ctx["user"]["id"],
                        article_id=old_id, is_read=True, is_saved=True)
    before_subscription = store.get_subscription(ctx["subscription_id"])
    before_state = states.get_state(workspace_id=DEFAULT_WORKSPACE_ID, user_id=ctx["user"]["id"], article_id=old_id)
    store.close()
    assert migrate(tmp_path, apply=True, services_stopped=True)["status"] == "applied"
    assert migrate(tmp_path, apply=True, services_stopped=True)["status"] == "already_applied"
    assert store.get_subscription(ctx["subscription_id"]) == before_subscription
    assert states.get_state(workspace_id=DEFAULT_WORKSPACE_ID, user_id=ctx["user"]["id"], article_id=old_id) == before_state
    adapter = build_default_registry().require(KEY)
    item = adapter.validate_output((row(),), adapter.normalize_target({"target": UID}), manifest(), WINDOW).items[0]
    assert item.id == old_id
    store.connect().execute("UPDATE source_catalog SET enabled=1 WHERE id=?", (ctx["source_id"],))
    store.connect().commit()
    second_job = _job(ctx)
    second = _save_snapshot(ctx, second_job, [_item(ctx, item.id, published_at=item.published_at.isoformat(), url=item.url)],
                            generated_at="2026-10-10T01:00:00Z")
    assert ctx["service"].stage_for_job(job=second_job, snapshot_id=second["id"], snapshot_created=True) == 0
    store.connect().commit()
    assert store.connect().execute("SELECT COUNT(*) FROM user_content_items WHERE article_id=?", (old_id,)).fetchone()[0] == 1
    assert store.connect().execute("SELECT COUNT(*) FROM preferred_source_notification_deliveries").fetchone()[0] == 1
    assert len(UserFeedStore(store).snapshot_history(workspace_id=DEFAULT_WORKSPACE_ID, user_id=ctx["user"]["id"])) == 3
    assert states.get_state(workspace_id=DEFAULT_WORKSPACE_ID, user_id=ctx["user"]["id"], article_id=old_id)["is_saved"]
    store.close()


@pytest.mark.parametrize("feed_url", [
    "https://rsshub.example.com/bilibili/user/video/39627524",
    "https://rsshub.example.com/prefix/bilibili/user/video/39627524/1?limit=5",
])
def test_legacy_raw_url_keeps_feed_identity_and_never_runs_rss(tmp_path, feed_url):
    from src.services.actorops.identity import legacy_rss_item_id
    from src.services.actorops.service import ActorOpsV2Service
    from src.services.actorops.adapters import build_default_registry
    from tests.test_bilibili_actor_adapter import KEY, UID, WINDOW, URL, manifest, row
    store = ServiceStore(tmp_path)
    store.initialize()
    source_id = store.create_source(workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
                                    source_type="rss", display_name="Legacy UP", config={"url": feed_url})
    source = store.get_source(source_id)
    store.close()
    assert migrate(tmp_path, apply=True, services_stopped=True)["status"] == "applied"
    projected = with_actorops_runtime_profiles(store, workspace_id=DEFAULT_WORKSPACE_ID,
                                               records=[{**source, "source_id": source_id}])[0]
    assert projected["type"] == "apify_social" and projected["config"]["enabled"] is False
    subscription = ApifySocialSubscriptionConfig.model_validate({**projected["config"], "source_id": source_id,
                                                                  "source_key": source["source_key"]})
    assert "rss_identity_url" not in subscription.model_dump()
    adapter = build_default_registry().require(KEY)
    batch = adapter.validate_output((row(),), adapter.normalize_target({"target": UID}), manifest(), WINDOW)
    item = ActorOpsV2Service._project_items(batch.items, subscription, "actorops_v2")[0]
    assert item.id == legacy_rss_item_id(feed_url, URL, managed=False)
    store.close()
