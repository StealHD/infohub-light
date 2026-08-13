import json
from datetime import datetime, timezone

from src.models import ContentItem, SourceType
from src.services.feed_run import FeedRunResult, SourceOutcome
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


def _store_with_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert workspace is not None and owner is not None
    return store, workspace, owner


def test_worker_safely_stops_running_refresh_without_publication_side_effects(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Safe Stop Feed",
        config={"url": "https://example.com/safe-stop.xml"},
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    job, created = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "manual_service_refresh", "refresh_scope": "all"},
    )
    assert created is True

    class CancellingOrchestrator:
        def __init__(self, _config, _storage):
            pass

        async def execute(self, **_kwargs):
            concurrent = ServiceStore(tmp_path)
            concurrent.initialize()
            accepted = JobQueue(concurrent).cancel_job(job["id"], user_id=owner["id"])
            assert accepted["status"] == "running"
            concurrent.close()
            item = ContentItem(
                id="rss:item:safe-stop",
                source_type=SourceType.RSS,
                title="Must not publish",
                url="https://example.com/safe-stop/item",
                published_at=datetime.now(timezone.utc),
                metadata={"source_id": source_id, "channel": "AI", "topics": ["Codex"]},
            )
            return FeedRunResult(
                run_id="run_safe_stop",
                status="succeeded",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                items=(item,),
                source_outcomes=(
                    SourceOutcome(
                        source_id=source_id,
                        subscription_id=subscription["id"],
                        source_key="rss:safe-stop",
                        analysis_mode="full",
                        status="succeeded",
                        fetched_count=1,
                    ),
                ),
            )

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", CancellingOrchestrator)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="safe-stop-worker")

    assert result["status"] == "cancelled"
    assert result["error_code"] == "job_cancelled"
    assert result["result_json"] == {"invalidation_reason": "user_cancelled"}
    assert UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"]
    ) is None
    assert store.connect().execute(
        "SELECT COUNT(*) AS count FROM user_source_health WHERE user_id = ?",
        (owner["id"],),
    ).fetchone()["count"] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) AS count FROM user_source_health_applications"
    ).fetchone()["count"] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) AS count FROM preferred_source_notification_deliveries WHERE user_id = ?",
        (owner["id"],),
    ).fetchone()["count"] == 0


def test_worker_reclamps_queued_admin_refresh_after_role_downgrade(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store_with_owner(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=None,
        source_type="rss",
        display_name="Role Clamp Feed",
        config={"url": "https://example.com/role-clamp.xml"},
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)
    job, _created = JobQueue(store).create_user_feed_refresh_if_absent(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payload={"reason": "manual_service_refresh", "refresh_scope": "all"},
    )
    store.connect().execute("UPDATE users SET role = 'member' WHERE id = ?", (owner["id"],))
    store.connect().commit()

    result = run_worker_once(data_dir=str(tmp_path), worker_id="role-clamp-worker")

    assert result["id"] == job["id"]
    assert result["status"] == "cancelled"
    assert result["result_json"] == {"invalidation_reason": "no_enabled_subscriptions"}
