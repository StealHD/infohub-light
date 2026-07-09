import json

from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


def test_worker_source_test_job_builds_payload_from_catalog_source(tmp_path, monkeypatch):
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
        display_name="Public Feed",
        config={"name": "Public Feed", "url": "https://example.com/feed.xml"},
    )
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={},
    )
    calls = []

    def fake_run_source_test(payload):
        calls.append(payload)
        return {"ok": True, "source_type": payload["source_type"]}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert calls == [
        {
            "source_type": "rss",
            "name": "Public Feed",
            "url": "https://example.com/feed.xml",
            "enabled": True,
        }
    ]


def test_worker_source_test_payload_uses_registry_and_secret_env_name(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("APIFY_TOKEN", "real-token-value")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="OpenAI on X",
        config={"platform": "x", "kind": "profile", "target": "openai"},
        secret_env="APIFY_TOKEN",
        source_key="apify_social:x:profile:openai",
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={"reason": "test"},
    )
    calls = []

    def fake_run_source_test(payload):
        calls.append(payload)
        return {"ok": True, "source_type": payload["source_type"]}

    monkeypatch.setattr("src.services.worker.run_source_test", fake_run_source_test)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert result["status"] == "succeeded"
    assert calls[0]["source_type"] == "apify_social"
    assert calls[0]["platform"] == "x"
    assert calls[0]["kind"] == "profile"
    assert calls[0]["target"] == "openai"
    assert calls[0]["token_env"] == "APIFY_TOKEN"
    assert "real-token-value" not in repr(calls[0])


def test_worker_source_fetch_with_catalog_source_uses_catalog_runner(tmp_path, monkeypatch):
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
        display_name="Fetch RSS",
        config={"name": "Fetch RSS", "url": "https://github.blog/feed/"},
        source_key="rss:https://github.blog/feed/",
    )
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_fetch",
        payload={"hours": 12},
    )
    calls = []

    def fake_run_catalog_source_fetch(catalog_job, *, data_dir, store):
        calls.append(
            {
                "job_id": catalog_job["id"],
                "source_id": catalog_job["source_id"],
                "hours": catalog_job["payload_json"]["hours"],
                "data_dir": data_dir,
            }
        )
        return {
            "ok": True,
            "job_type": "source_fetch",
            "source_id": catalog_job["source_id"],
            "source_type": "rss",
            "source_key": "rss:https://github.blog/feed/",
            "snapshot_id": "snap_worker",
            "item_count": 2,
        }

    monkeypatch.setattr(
        "src.services.catalog_source_runner.run_catalog_source_fetch",
        fake_run_catalog_source_fetch,
    )

    result = run_worker_once(data_dir=str(tmp_path), worker_id="test-worker")

    assert calls == [
        {
            "job_id": job["id"],
            "source_id": source_id,
            "hours": 12,
            "data_dir": str(tmp_path),
        }
    ]
    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert result["result_json"]["snapshot_id"] == "snap_worker"
    assert result["result_json"]["source_key"] == "rss:https://github.blog/feed/"


def test_worker_retries_failed_job_before_final_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
        max_attempts=2,
    )

    def failing_run_source_test(_payload):
        raise RuntimeError("temporary source failure")

    monkeypatch.setattr("src.services.worker.run_source_test", failing_run_source_test)

    first = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1", retry_base_seconds=0)
    second = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1", retry_base_seconds=0)

    assert first["id"] == job["id"]
    assert first["status"] == "queued"
    assert first["attempts"] == 1
    assert second["status"] == "failed"
    assert second["attempts"] == 2
    assert second["error_code"] == "RuntimeError"


def test_worker_user_feed_refresh_saves_user_snapshot(tmp_path, monkeypatch):
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
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
        payload={},
    )

    class FakeOrchestrator:
        def __init__(self, _config, storage):
            self.storage = storage

        async def run(self, **_kwargs):
            site_dir = self.storage.data_dir / "site"
            site_dir.mkdir(parents=True, exist_ok=True)
            (site_dir / "radar-data.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-09T10:00:00+08:00",
                        "items": [{"id": "rss:item:worker", "channel": "AI", "topics": ["Codex"]}],
                    }
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr("src.orchestrator.HorizonOrchestrator", FakeOrchestrator)

    result = run_worker_once(data_dir=str(tmp_path), worker_id="worker-1")
    latest = UserFeedStore(store).latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])

    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    assert result["result_json"]["snapshot_id"] == latest["id"]
    assert result["result_json"]["item_count"] == 1
    assert latest["payload"]["items"][0]["id"] == "rss:item:worker"
