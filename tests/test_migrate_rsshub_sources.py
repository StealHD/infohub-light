from __future__ import annotations

import json

import pytest

from scripts.migrate_rsshub_sources import migrate_rsshub_sources
from src.services.source_schedule import SourceScheduleService
from src.storage.service_store import ServiceStore


def _config() -> dict:
    return {
        "version": "1.0",
        "ai": {
            "enabled": False,
            "provider": "openai",
            "model": "test",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {
            "rss": [
                {
                    "name": "Legacy Bilibili",
                    "url": (
                        "https://third-party.example/bilibili/user/video/"
                        "39627524/1"
                    ),
                    "keep_latest_item": True,
                },
                {
                    "name": "Direct",
                    "url": "https://example.com/feed.xml",
                },
            ]
        },
        "filtering": {},
    }


def test_rsshub_migration_preserves_catalog_subscription_and_schedule_state(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    (tmp_path / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Legacy Bilibili",
        config={
            "name": "Legacy Bilibili",
            "url": (
                "https://third-party.example/bilibili/user/video/39627524/1"
            ),
            "keep_latest_item": True,
        },
        source_key=(
            "rss:https://third-party.example/bilibili/user/video/39627524/1"
        ),
        enforce_public_network=True,
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
        priority=37,
    )
    schedule = SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscription["id"],
        enabled=True,
        interval_minutes=360,
    )
    store.close()

    dry_run = migrate_rsshub_sources(
        data_dir=tmp_path,
        base_url="http://host.docker.internal:1200/",
        apply=False,
    )
    assert dry_run["applied"] is False
    assert dry_run["database_source_count"] == 1
    assert dry_run["config_source_count"] == 1
    assert dry_run["database_sources"][0]["id"] == source_id
    assert dry_run["database_sources"][0]["uid"] == "39627524"

    result = migrate_rsshub_sources(
        data_dir=tmp_path,
        base_url="http://host.docker.internal:1200/",
        apply=True,
    )
    assert result["applied"] is True
    assert result["backup_dir"]

    migrated_store = ServiceStore(tmp_path)
    migrated = migrated_store.get_source(source_id)
    assert migrated["source_key"] == (
        "rss:rsshub:bilibili:user_video:39627524"
    )
    assert migrated["config"]["provider"] == "rsshub"
    assert migrated["config"]["params"] == {"uid": "39627524"}
    assert migrated["config"]["url"] == (
        "https://space.bilibili.com/39627524"
    )
    assert migrated["enforce_public_network"] is False
    preserved_subscription = migrated_store.get_subscription(subscription["id"])
    preserved_schedule = migrated_store.get_source_schedule(subscription["id"])
    assert preserved_subscription["source_id"] == source_id
    assert preserved_subscription["priority"] == 37
    assert preserved_schedule["source_id"] == source_id
    assert preserved_schedule["enabled"] is True
    assert preserved_schedule["interval_minutes"] == schedule["interval_minutes"]
    migrated_store.close()

    migrated_config = json.loads(
        (tmp_path / "config.json").read_text(encoding="utf-8")
    )
    assert migrated_config["rsshub"] == {
        "base_url": "http://host.docker.internal:1200"
    }
    assert migrated_config["sources"]["rss"][0]["provider"] == "rsshub"
    assert migrated_config["sources"]["rss"][1]["url"] == (
        "https://example.com/feed.xml"
    )

    idempotent = migrate_rsshub_sources(
        data_dir=tmp_path,
        base_url="http://host.docker.internal:1200",
        apply=False,
    )
    assert idempotent["database_source_count"] == 0
    assert idempotent["config_source_count"] == 0


def test_rsshub_migration_refuses_active_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    (tmp_path / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    store.upsert_worker_heartbeat("active-worker", "idle")
    store.close()

    with pytest.raises(RuntimeError, match="stop all horizon-worker"):
        migrate_rsshub_sources(
            data_dir=tmp_path,
            base_url="http://host.docker.internal:1200",
            apply=True,
        )
