from __future__ import annotations

import json

from scripts.reset_local_service import reset_local_service
from src.services.feed_schedule import FeedScheduleService
from src.services.job_queue import JobQueue
from src.services.secret_store import SecretStore
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


def test_reset_local_service_clears_runtime_content_but_preserves_owner_and_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = {"version": "1.0", "marker": "keep-global-config"}
    (data_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert owner is not None
    source_id = store.create_source(
        workspace_id=workspace["id"], scope="public", owner_user_id=owner["id"],
        source_type="rss", display_name="Smoke RSS",
        config={"url": "https://example.com/feed.xml"}, source_key="rss:https://example.com/feed.xml",
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"], user_id=owner["id"], source_id=source_id,
        job_type="source_fetch", payload={},
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"], job_id=job["id"],
        payload={"generated_at": "2026-07-13T00:00:00+00:00", "items": [{"id": "rss:old"}]},
    )
    store.connect().execute(
        """
        INSERT INTO user_source_health (
            subscription_id, workspace_id, user_id, source_id, status,
            last_attempt_at, consecutive_failures, last_fetched_count,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'healthy', ?, 0, 1, ?, ?)
        """,
        (
            subscription["id"], workspace["id"], owner["id"], source_id,
            "2026-07-13T00:00:00+00:00", "2026-07-13T00:00:00+00:00",
            "2026-07-13T00:00:00+00:00",
        ),
    )
    store.connect().commit()
    FeedScheduleService(store).update_user_schedule(
        user_id=owner["id"], workspace_id=workspace["id"], enabled=True, interval_minutes=360,
    )
    store.create_secret_ref(
        workspace_id=workspace["id"], owner_user_id=owner["id"], name="Old Key",
        env_name="OLD_SECRET", kind="ai", provider="gemini",
    )
    SecretStore(data_dir).set("OLD_SECRET", "old-private-value")
    store.close()

    result = reset_local_service(data_dir)

    verify = ServiceStore(data_dir)
    verify.initialize()
    for table in (
        "source_catalog", "user_subscriptions", "user_feed_snapshots", "user_feed_items",
        "user_item_state", "user_item_feedback", "user_source_health",
        "user_source_health_applications", "fetch_jobs", "usage_events", "worker_heartbeats",
        "secret_refs",
    ):
        assert verify.connect().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert verify.connect().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert verify.connect().execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1
    schedule = FeedScheduleService(verify).get_user_schedule(user_id=owner["id"])
    assert schedule["enabled"] is False
    assert schedule["interval_minutes"] == 360
    assert schedule["next_run_at"] is None
    assert json.loads((data_dir / "config.json").read_text()) == config
    assert not (data_dir / "secrets.env").exists()
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_errors"] == 0
