import json
from datetime import datetime, timezone

import pytest

from src.models import ContentItem, SourceType
from src.apify_actor_identity import source_target_fingerprint
from src.services.feed_run import FeedRunResult, SourceAvatarHint, SourceOutcome
from src.services.job_queue import JobQueue
from src.services.catalog_source_runner import (
    build_catalog_source_config_data,
    run_catalog_source_fetch,
)
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


def _base_config():
    return {
        "version": "1.0",
        "ai": {
            "enabled": False,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"time_window_hours": 24},
    }


def _write_config(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text(json.dumps(_base_config()), encoding="utf-8")


def _store_with_rss_source(tmp_path, monkeypatch):
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
        display_name="Runner RSS",
        default_channel="AI",
        default_topics=["Codex"],
        config={"name": "Runner RSS", "url": "https://github.blog/feed/"},
        source_key="rss:https://github.blog/feed/",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
        override_channel="产品机会",
        override_topics=["价格监控"],
        personal_tags=["高定"],
        analysis_mode="personal_only",
    )
    return store, workspace, owner, source_id, subscription


def test_build_catalog_source_config_data_uses_subscription_overrides(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _store_with_rss_source(tmp_path, monkeypatch)

    data = build_catalog_source_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        base_config=_base_config(),
    )

    rss = data["sources"]["rss"]
    assert len(rss) == 1
    assert rss[0]["name"] == "Runner RSS"
    assert rss[0]["url"] == "https://github.blog/feed/"
    assert rss[0]["channel"] == "产品机会"
    assert rss[0]["category"] == "产品机会"
    assert rss[0]["topics"] == ["价格监控"]
    assert rss[0]["tags"] == ["价格监控"]
    assert rss[0]["personal_tags"] == ["高定"]
    assert rss[0]["analysis_mode"] == "personal_only"
    assert rss[0]["service_fetch_window_hours"] == 168
    assert data["sources"]["github"] == []
    assert data["sources"]["hackernews"]["enabled"] is False


def test_catalog_rss_config_disables_global_hackernews(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _store_with_rss_source(tmp_path, monkeypatch)
    base = _base_config()
    base["sources"]["hackernews"] = {
        "enabled": True,
        "fetch_top_stories": 20,
        "min_score": 100,
    }

    data = build_catalog_source_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        base_config=base,
    )

    assert data["sources"]["hackernews"] == {
        "enabled": False,
        "fetch_top_stories": 20,
        "min_score": 100,
    }


def test_catalog_source_runner_ignores_legacy_x_binding(
    tmp_path, monkeypatch
):
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
        source_type="apify_social",
        display_name="Bound X source",
        config={"platform": "x", "kind": "profile", "target": "OpenAI"},
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    route = store.connect().execute(
        """
        SELECT route_id FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (workspace["id"],),
    ).fetchone()
    assert route is not None
    route_id = str(route["route_id"])
    # A historical v1 Binding is not an online projection authority.
    store.connect().execute(
        """INSERT INTO apify_source_route_bindings (
               binding_id, workspace_id, source_id, route_id,
               target_fingerprint, mode, validation_status, generation,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, 'primary', 'valid', 1, ?, ?)""",
        (
            "legacy-binding",
            workspace["id"],
            source_id,
            route_id,
            source_target_fingerprint(
                workspace["id"], route_id, "OpenAI", platform="x"
            ),
            "2026-08-22T00:00:00+00:00",
            "2026-08-22T00:00:00+00:00",
        ),
    )
    store.connect().commit()
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)

    data = build_catalog_source_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        base_config=_base_config(),
    )

    assert "profile_id" not in data["sources"]["apify_social"]["subscriptions"][0]
    assert any("actor_source_bindings_v2" in statement for statement in statements)


def test_catalog_runner_injects_ready_v2_binding_without_legacy_binding(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="V2-bound Instagram source",
        config={"platform": "instagram", "kind": "profile", "target": "example"},
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    connection = store.connect()
    route = connection.execute(
        """SELECT route_id FROM actor_routes_v2
           WHERE workspace_id=? AND platform=? AND target_type=? AND capability=?""",
        (workspace["id"], "instagram", "profile", "items"),
    ).fetchone()
    assert route is not None
    route_id = str(route["route_id"])
    connection.execute(
        """INSERT INTO actor_source_bindings_v2 (
               binding_id, workspace_id, source_id, route_id, target_fingerprint,
               status, binding_version, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, 'ready', 1, ?, ?)""",
        (
            "v2-catalog-binding",
            workspace["id"],
            source_id,
            route_id,
            source_target_fingerprint(workspace["id"], route_id, "example", platform="instagram"),
            "2026-08-21T00:00:00+00:00",
            "2026-08-21T00:00:00+00:00",
        ),
    )
    connection.commit()

    data = build_catalog_source_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        base_config=_base_config(),
    )

    assert data["sources"]["apify_social"]["subscriptions"][0]["profile_id"] == route_id


def test_catalog_runner_fallback_preserves_persisted_public_network_marker(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _store_with_rss_source(
        tmp_path, monkeypatch
    )
    store.update_source(source_id, enforce_public_network=True)
    store.delete_subscription(subscription["id"], user_id=owner["id"])

    data = build_catalog_source_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        base_config=_base_config(),
    )

    assert data["sources"]["rss"][0]["enforce_public_network"] is True


def test_run_catalog_source_fetch_saves_snapshot_and_returns_source_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_SHARED_ACQUISITION_ENABLED", "true")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    _write_config(tmp_path)
    store, workspace, owner, source_id, subscription = _store_with_rss_source(tmp_path, monkeypatch)
    calls = []
    acquisition_coordinators = []
    apify_coordinators = []

    class FakeOrchestrator:
        def __init__(self, config, _storage):
            self.config = config
            calls.append(config.sources.rss[0].channel)

        def set_service_acquisition_coordinator(self, coordinator):
            acquisition_coordinators.append(coordinator)

        def set_service_apify_coordinator(self, coordinator):
            apify_coordinators.append(coordinator)

        async def execute(self, **kwargs):
            assert kwargs["enrich"] is False
            assert kwargs["force_hours"] == 6
            item = ContentItem(
                id="rss:item:runner",
                source_type=SourceType.RSS,
                title="Runner",
                url="https://example.com/runner",
                published_at=datetime.now(timezone.utc),
                metadata={
                    "feed_name": "Runner RSS",
                    "source_id": source_id,
                    "subscription_id": subscription["id"],
                    "channel": "产品机会",
                    "topics": ["价格监控"],
                },
                ai_score=8.1,
            )
            return FeedRunResult(
                run_id="run_catalog",
                status="succeeded",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                items=(item,),
                source_outcomes=(
                    SourceOutcome(
                        source_id=source_id,
                        subscription_id=subscription["id"],
                        source_key="rss:https://github.blog/feed/",
                        analysis_mode="personal_only",
                        status="succeeded",
                        fetched_count=1,
                    ),
                ),
            )

    monkeypatch.setattr("src.services.catalog_source_runner.HorizonOrchestrator", FakeOrchestrator)

    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_fetch",
        payload={"hours": 6},
    )
    result = run_catalog_source_fetch(
        job,
        data_dir=str(tmp_path),
        store=store,
    )
    latest = UserFeedStore(store).latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])

    assert calls == ["产品机会"]
    assert len(acquisition_coordinators) == 1
    assert acquisition_coordinators[0].user_id == owner["id"]
    assert len(apify_coordinators) == 1
    assert apify_coordinators[0].workspace_id == workspace["id"]
    assert result["ok"] is True
    assert result["job_type"] == "source_fetch"
    assert result["source_id"] == source_id
    assert result["source_type"] == "rss"
    assert result["source_key"] == "rss:https://github.blog/feed/"
    assert result["snapshot_id"] == latest["id"]
    assert result["fetched_count"] == 1
    assert result["item_count"] == 1
    assert result["new_item_count"] == 1
    assert result["acquisition_usage"] == {
        "cache_hits": 0,
        "cache_misses": 0,
        "upstream_attempts": 0,
        "waits": 0,
    }


def test_catalog_source_fetch_successful_empty_result_reuses_unchanged_snapshot(
    tmp_path,
    monkeypatch,
):
    _write_config(tmp_path)
    store, workspace, owner, source_id, subscription = _store_with_rss_source(
        tmp_path,
        monkeypatch,
    )
    run_index = 0
    avatar_runs = []

    class AvatarService:
        def __init__(self, _store, *, data_dir):
            assert data_dir == str(tmp_path)

        def refresh_run_result(
            self,
            *,
            workspace_id,
            result,
            commit=True,
            media_cleanup=None,
        ):
            avatar_runs.append((workspace_id, result))
            return []

    class EmptyOrchestrator:
        def __init__(self, _config, _storage):
            pass

        def set_service_apify_coordinator(self, _coordinator):
            pass

        async def execute(self, **_kwargs):
            nonlocal run_index
            run_index += 1
            now = datetime.now(timezone.utc).isoformat()
            return FeedRunResult(
                run_id=f"run_empty_{run_index}",
                status="succeeded",
                started_at=now,
                finished_at=now,
                items=(),
                source_outcomes=(
                    SourceOutcome(
                        source_id=source_id,
                        subscription_id=subscription["id"],
                        source_key="rss:https://github.blog/feed/",
                        analysis_mode="personal_only",
                        status="succeeded",
                        fetched_count=0,
                        avatar_hints=(
                            SourceAvatarHint(
                                source_id=source_id,
                                remote_url="https://example.com/avatar.png",
                                origin="rss_feed_icon",
                            ),
                        ),
                    ),
                ),
            )

    monkeypatch.setattr(
        "src.services.catalog_source_runner.HorizonOrchestrator",
        EmptyOrchestrator,
    )
    monkeypatch.setattr(
        "src.services.catalog_source_runner.SourceAvatarService",
        AvatarService,
    )

    results = []
    for index in range(2):
        job = JobQueue(store).create_job(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            source_id=source_id,
            subscription_id=subscription["id"],
            job_type="source_fetch",
            payload={"hours": 6},
        )
        results.append(
            run_catalog_source_fetch(
                job,
                data_dir=str(tmp_path),
                store=store,
            )
        )

    assert results[0]["fetched_count"] == 0
    assert results[0]["new_item_count"] == 0
    assert results[1]["fetched_count"] == 0
    assert results[1]["new_item_count"] == 0
    assert results[1]["snapshot_created"] is False
    assert results[1]["snapshot_id"] == results[0]["snapshot_id"]
    assert len(avatar_runs) == 2
    assert all(workspace_id == workspace["id"] for workspace_id, _ in avatar_runs)
    assert all(result.items == () for _, result in avatar_runs)


def test_catalog_stale_publication_rolls_back_feed_and_media_files(
    tmp_path,
    monkeypatch,
) -> None:
    _write_config(tmp_path)
    store, workspace, owner, source_id, subscription = _store_with_rss_source(
        tmp_path,
        monkeypatch,
    )
    old_path = tmp_path / "media" / "catalog-old-avatar.png"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"\x89PNG\r\n\x1a\nold-avatar")
    now = datetime.now(timezone.utc).isoformat()
    store.connect().execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, source_id, asset_kind, remote_url, local_path,
            mime_type, byte_size, checksum, visibility_scope, status,
            created_at, updated_at
        ) VALUES ('med_catalog_old', ?, ?, 'source_avatar',
                  'https://old.example/avatar.png',
                  'media/catalog-old-avatar.png', 'image/png', 18,
                  'old-checksum', 'public', 'ready', ?, ?)
        """,
        (workspace["id"], source_id, now, now),
    )
    store.connect().commit()
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_fetch",
        payload={},
    )

    class StaleOrchestrator:
        def __init__(self, _config, _storage):
            self.fence_calls = 0

        async def execute(self, **_kwargs):
            item = ContentItem(
                id="rss:catalog-stale",
                source_type=SourceType.RSS,
                title="Catalog stale",
                url="https://example.com/catalog-item",
                published_at=datetime.now(timezone.utc),
                metadata={
                    "source_id": source_id,
                    "subscription_id": subscription["id"],
                    "remote_media_urls": ["https://media.example/catalog.png"],
                },
            )
            return FeedRunResult(
                run_id="run-catalog-stale",
                status="succeeded",
                started_at=now,
                finished_at=now,
                items=(item,),
                source_outcomes=(
                    SourceOutcome(
                        source_id,
                        subscription["id"],
                        "rss:catalog-stale",
                        "full",
                        "succeeded",
                        1,
                        avatar_hints=(
                            SourceAvatarHint(
                                source_id=source_id,
                                remote_url="https://new.example/avatar.png",
                                origin="rss_feed_icon",
                            ),
                        ),
                    ),
                ),
            )

        def assert_service_apify_actor_ops_publishable(self):
            self.fence_calls += 1
            if self.fence_calls == 3:
                raise RuntimeError("stale route generation")

    monkeypatch.setattr(
        "src.services.catalog_source_runner.HorizonOrchestrator",
        StaleOrchestrator,
    )
    monkeypatch.setattr(
        "src.services.media_cache.MediaCacheService._download",
        lambda _self, _url, *, max_bytes: (
            b"\x89PNG\r\n\x1a\nnew-media",
            "image/png",
        ),
    )

    with pytest.raises(RuntimeError, match="stale route generation"):
        run_catalog_source_fetch(
            job,
            data_dir=str(tmp_path),
            store=store,
            commit=True,
        )

    assert UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    ) is None
    rows = store.connect().execute(
        "SELECT id, local_path FROM media_assets ORDER BY id"
    ).fetchall()
    assert [(row["id"], row["local_path"]) for row in rows] == [
        ("med_catalog_old", "media/catalog-old-avatar.png")
    ]
    assert old_path.exists()
    assert [path for path in (tmp_path / "media").rglob("*") if path.is_file()] == [
        old_path
    ]
