"""Feed translation authorization, durable idempotency and bounded model work."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from api_service_test_support import client as make_client, login, login_as
from scripts.migrate_content_translations_v49 import migrate, preview
from src.ai.client import CompletionMetrics
from src.ai.translation import chunks, translate
from src.services.content_translation import ContentTranslationService, prune_translations
from src.services.content_translation_input import TranslationError, prepare_input, read_source
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore
from src.services.worker_content_translation import run_content_translation
from src.storage.content_translation_schema import ready
from src.storage.service_store import ServiceStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    client, data_dir = make_client(tmp_path, monkeypatch)
    monkeypatch.setenv("TRANSLATION_TEST_KEY", "test-only-placeholder")
    (data_dir / "config.json").write_text(json.dumps({
        "ai": {"enabled": False, "provider": "openai", "model": "test-model",
               "api_key_env": "TRANSLATION_TEST_KEY"},
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}}, "filtering": {},
    }))
    login(client)
    store = ServiceStore(data_dir)
    owner = store.get_user_by_username("owner")
    UserFeedStore(store).save_snapshot(workspace_id=owner["workspace_id"], user_id=owner["id"],
        job_id="translation-fixture", payload={"schema_version": 2, "items": [{
            "id": "post:1", "title": "Title is not the body", "url": "https://example.test/one",
            "summary_zh": "AI summary must never be translated",
            "presentation": {"content": {"excerpt": "Source excerpt"}},
        }]})
    store.connect().execute("UPDATE user_content_items SET body_text=?,body_completeness='captured'", ("Original text.\n\nSecond paragraph.",))
    store.connect().commit()
    yield client, store, owner
    store.close()
    client.close()


class FakeModel:
    last_completion_metrics = None

    def __init__(self, result='{"translation":"译文正文"}', callback=None):
        self.result, self.callback = result, callback
        self.calls = []
        self.closed = False

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self.callback:
            self.callback()
        return self.result

    async def aclose(self):
        self.closed = True


def execute(store, model):
    queue = JobQueue(store)
    job = queue.claim_next_job(worker_id="translation-test", allowed_job_types={"content_translate"})
    assert job and job["max_attempts"] == 1
    result = run_content_translation(job, data_dir=str(store.data_dir), store=store,
        client_factory=lambda config, **kwargs: model)
    queue.complete_job(job["id"], status="succeeded", result=result,
        worker_id=job["worker_id"], claim_token=job["claim_token"])
    return job


def test_request_worker_cache_and_no_feed_side_effect(setup):
    client, store, owner = setup
    path = "/api/feed/items/post:1/translation"
    response = client.get(path)
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["status"] == "idle"
    first = client.post(path, json={"request_id": "first"}).json()["data"]
    second = client.post(path, json={"request_id": "second"}).json()["data"]
    assert first["status"] == "queued" and first["job_id"] == second["job_id"]
    model = FakeModel()
    model.callback = lambda: assert_no_transaction(store)
    execute(store, model)
    assert model.closed and len(model.calls) == 1
    assert json.loads(model.calls[0]["user"])["text"] == "Original text.\n\nSecond paragraph."
    cached = client.post(path, json={"request_id": "third"}).json()["data"]
    assert cached["cached"] and cached["translation"] == "译文正文"
    assert client.get(path).json()["data"] == cached
    assert store.connect().execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0] == 1
    assert store.connect().execute("SELECT COUNT(*) FROM fetch_jobs").fetchone()[0] == 1
    assert "Original text" not in store.connect().execute("SELECT payload_json FROM fetch_jobs").fetchone()[0]


def assert_no_transaction(store):
    assert not store.connect().in_transaction


def test_all_sources_use_stored_body_and_legacy_summary_is_never_input(setup):
    _, store, owner = setup
    for source in ("twitter", "rss", "telegram", "reddit", "hackernews", "github", "apify_social"):
        conn = store.connect()
        row = json.loads(conn.execute("SELECT item_json FROM user_content_items").fetchone()[0])
        row["source_type"] = source
        conn.execute("UPDATE user_content_items SET item_json=?", (json.dumps(row),))
        conn.commit()
        assert read_source(store, owner, "post:1")[0].startswith("Original text")
    conn.execute("UPDATE user_content_items SET body_completeness='excerpt_only'")
    conn.commit()
    assert read_source(store, owner, "post:1") == ("Source excerpt", "excerpt", False)
    conn.execute("UPDATE user_content_items SET item_json=?", (json.dumps({"summary_zh": "AI only"}),))
    conn.commit()
    with pytest.raises(TranslationError, match="暂无"):
        read_source(store, owner, "post:1")


def test_permissions_and_cross_user_isolation(setup):
    client, store, owner = setup
    other = store.create_user(workspace_id=owner["workspace_id"], username="other", password="password")
    login_as(client, "other", "password")
    path = "/api/feed/items/post:1/translation"
    assert client.get(path).status_code == 404
    assert client.post(path, json={"request_id": "other"}).status_code == 404
    store.create_user(workspace_id=owner["workspace_id"], username="viewer", password="password", role="viewer")
    login_as(client, "viewer", "password")
    assert client.post(path, json={"request_id": "viewer"}).status_code == 403
    assert other["id"] != owner["id"]


def test_concurrent_admission_and_config_invalidation(setup):
    _, store, owner = setup
    def request(number):
        scoped = ServiceStore(store.data_dir)
        try:
            return ContentTranslationService(scoped).request(owner, "post:1", str(number))["job_id"]
        finally:
            scoped.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(request, range(4)))) == 1
    original = prepare_input(store, owner, "post:1").cache_key
    config_path = store.data_dir / "config.json"
    config = json.loads(config_path.read_text())
    config["ai"]["model"] = "other-model"
    config_path.write_text(json.dumps(config))
    assert original != prepare_input(store, owner, "post:1").cache_key
    job = JobQueue(store).claim_next_job(worker_id="translation-test")
    with pytest.raises(TranslationError, match="配置已变化"):
        run_content_translation(job, data_dir=str(store.data_dir), store=store, client_factory=lambda *a, **k: pytest.fail("must not call model"))


def test_cache_expiry_and_content_delete(setup):
    _, store, owner = setup
    service = ContentTranslationService(store)
    service.request(owner, "post:1", "one")
    execute(store, FakeModel())
    store.connect().execute("UPDATE content_translations SET expires_at='2000-01-01'")
    store.connect().commit()
    assert service.get(owner, "post:1")["status"] == "idle"
    prune_translations(store)
    assert store.connect().execute("SELECT COUNT(*) FROM content_translation_requests").fetchone()[0] == 0
    service.request(owner, "post:1", "two")
    store.connect().execute("DELETE FROM user_content_items")
    store.connect().commit()
    assert store.connect().execute("SELECT COUNT(*) FROM content_translations").fetchone()[0] == 0


def test_migration_is_explicit_backup_and_preserves_content(setup, tmp_path):
    client, store, _ = setup
    conn = store.connect()
    conn.execute("DROP TABLE content_translation_requests")
    conn.execute("DROP TABLE content_translations")
    conn.execute("DELETE FROM schema_migrations WHERE version=49")
    conn.commit()
    assert client.get("/api/feed/items/post:1/translation").status_code == 503
    reopened = ServiceStore(store.data_dir)
    reopened.initialize()
    assert not ready(reopened.connect())
    reopened.close()
    assert preview(store.data_dir)["status"] == "migration_required"
    result = migrate(store.data_dir, tmp_path / "backups")
    assert result["status"] == "migrated" and ready(conn)
    assert conn.execute("SELECT COUNT(*) FROM user_content_items").fetchone()[0] == 1
    assert migrate(store.data_dir, tmp_path / "backups")["status"] == "ready"


def test_migration_blocks_active_queue_and_invalid_schema(setup, tmp_path):
    _, store, owner = setup
    job = JobQueue(store).create_job(workspace_id=owner["workspace_id"], user_id=owner["id"], job_type="source_fetch")
    conn = store.connect()
    conn.execute("DROP INDEX content_translation_expiry")
    conn.commit()
    assert not ready(conn)
    with pytest.raises(ValueError, match="invalid global 49"):
        preview(store.data_dir)
    conn.execute("DROP TABLE content_translation_requests")
    conn.execute("DROP TABLE content_translations")
    conn.execute("DELETE FROM schema_migrations WHERE version=49")
    conn.commit()
    assert preview(store.data_dir)["active_jobs"] == 1
    with pytest.raises(ValueError, match="drain the job queue"):
        migrate(store.data_dir, tmp_path / "blocked-backups")
    from src.storage.content_translation_schema import apply_migration
    with pytest.raises(ValueError, match="drain the job queue"):
        apply_migration(conn)
    assert not conn.in_transaction
    conn.execute("DELETE FROM fetch_jobs WHERE id=?", (job["id"],))
    conn.commit()
    assert migrate(store.data_dir, tmp_path / "backups")["status"] == "migrated"


@pytest.mark.parametrize("result", ['', '{}', '{"translation":""}', '{"translation":123}', 'not json'])
def test_invalid_model_output_is_rejected(result):
    with pytest.raises(TranslationError):
        asyncio.run(translate(FakeModel(result), "Original", lambda: None))


def test_long_text_chunking_and_truncation():
    text = "English with 中文\n\n" * 1300
    parts = chunks(text)
    assert "".join(parts) == text and max(map(len, parts)) <= 2000
    boundary_text = "x" * 2000 + " \n" + "y" * 2100
    assert "".join(chunks(boundary_text)) == boundary_text
    assert max(map(len, chunks(boundary_text))) <= 2000
    model = FakeModel()
    asyncio.run(translate(model, text, lambda: None))
    assert len(model.calls) == len(parts)
    model.last_completion_metrics = CompletionMetrics(1, 4096, None, None, "length", 100)
    with pytest.raises(TranslationError, match="完整译文"):
        asyncio.run(translate(model, "Original", lambda: None))


def test_actual_worker_commits_translation_and_does_not_publish(setup, monkeypatch):
    from src.services.worker import run_worker_once

    _, store, owner = setup
    service = ContentTranslationService(store)
    service.request(owner, "post:1", "worker")
    model = FakeModel()
    monkeypatch.setattr("src.services.worker_content_translation.create_ai_client", lambda *a, **k: model)
    monkeypatch.setattr("src.services.worker_cycle.run_worker_housekeeping", lambda *a, **k: None)
    result = run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False)
    assert result["status"] == "succeeded"
    assert service.get(owner, "post:1")["translation"] == "译文正文"
    assert store.connect().execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0] == 1


def test_worker_failure_is_safe_and_explicit_retry_gets_new_job(setup, monkeypatch):
    from src.services.worker import run_worker_once

    _, store, owner = setup
    service = ContentTranslationService(store)
    first = service.request(owner, "post:1", "failure")

    def fail(*args, **kwargs):
        raise RuntimeError("private upstream body and credentials")

    monkeypatch.setattr("src.services.worker_content_translation.create_ai_client", fail)
    monkeypatch.setattr("src.services.worker_cycle.run_worker_housekeeping", lambda *a, **k: None)
    result = run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False)
    assert result["status"] == "failed"
    job = JobQueue(store).get_job(first["job_id"])
    assert job["attempts"] == 1 and "private upstream" not in job["error_message"]
    with pytest.raises(ValueError, match="卡片翻译入口"):
        JobQueue(store).retry_job(job["id"])
    assert service.request(owner, "post:1", "failure")["status"] == "failed"
    assert service.request(owner, "post:1", "explicit-retry")["job_id"] != first["job_id"]


def test_credentials_quota_and_body_change_are_checked(setup, monkeypatch):
    from src.services.quota import QuotaExceeded

    client, store, owner = setup
    original = prepare_input(store, owner, "post:1").cache_key
    store.connect().execute("UPDATE user_content_items SET body_text='Changed body'")
    store.connect().commit()
    assert prepare_input(store, owner, "post:1").cache_key != original
    original = prepare_input(store, owner, "post:1").cache_key
    monkeypatch.setenv("TRANSLATION_TEST_KEY", "rotated-test-only")
    assert prepare_input(store, owner, "post:1").cache_key != original
    monkeypatch.delenv("TRANSLATION_TEST_KEY")
    assert client.get("/api/feed/items/post:1/translation").json()["error"]["code"] == "translation_model_unavailable"
    monkeypatch.setenv("TRANSLATION_TEST_KEY", "test-only-placeholder")

    def reject(*args, **kwargs):
        raise QuotaExceeded("exhausted")

    monkeypatch.setattr("src.services.quota.QuotaService.admit_ai_item", reject)
    assert client.post("/api/feed/items/post:1/translation", json={"request_id": "quota"}).status_code == 429
    assert store.connect().execute("SELECT COUNT(*) FROM fetch_jobs").fetchone()[0] == 0


def test_access_revoked_during_generation_cannot_publish(setup):
    from src.services.job_eligibility import JobIneligibleError

    _, store, owner = setup
    ContentTranslationService(store).request(owner, "post:1", "revoke")
    queue = JobQueue(store)
    job = queue.claim_next_job(worker_id="revoked")

    def revoke():
        conn = store.connect()
        conn.execute("UPDATE users SET enabled=0 WHERE id=?", (owner["id"],))
        conn.commit()

    with pytest.raises((TranslationError, JobIneligibleError)):
        run_content_translation(job, data_dir=str(store.data_dir), store=store,
            client_factory=lambda *a, **k: FakeModel(callback=revoke))
    store.connect().rollback()
    assert store.connect().execute("SELECT translated_text FROM content_translations").fetchone()[0] is None


def test_partial_long_translation_never_becomes_success_cache(setup, monkeypatch):
    from src.services.quota import QuotaExceeded

    _, store, owner = setup
    store.connect().execute("UPDATE user_content_items SET body_text=?", ("Paragraph.\n\n" * 500,))
    store.connect().commit()
    ContentTranslationService(store).request(owner, "post:1", "long")
    attempts = []

    def quota(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 2:
            raise QuotaExceeded("limit")

    monkeypatch.setattr("src.services.quota.QuotaService.admit_ai_attempt", lambda self, **kwargs: quota(**kwargs))
    model = FakeModel()
    with pytest.raises(QuotaExceeded):
        execute(store, model)
    assert len(model.calls) == 1 and model.closed
    assert store.connect().execute("SELECT translated_text FROM content_translations").fetchone()[0] is None


def test_captured_limit_and_user_deletion_cleanup(setup):
    _, store, owner = setup
    store.connect().execute("UPDATE user_content_items SET body_text=?", ("a" * 21_000,))
    store.connect().commit()
    text, scope, truncated = read_source(store, owner, "post:1")
    assert len(text) == 20_000 and scope == "body" and truncated
    ContentTranslationService(store).request(owner, "post:1", "delete")
    store.connect().execute("DELETE FROM users WHERE id=?", (owner["id"],))
    store.connect().commit()
    assert store.connect().execute("SELECT COUNT(*) FROM content_translations").fetchone()[0] == 0
    assert store.connect().execute("SELECT COUNT(*) FROM content_translation_requests").fetchone()[0] == 0


def test_legacy_content_reconcile_preserves_translation_and_its_cascade(setup, tmp_path):
    from scripts.repair_user_content_v5 import reconcile_content
    from test_content_repair_v5 import _force_legacy_unresolved_reason_not_null

    _, store, owner = setup
    service = ContentTranslationService(store)
    service.request(owner, "post:1", "before-reconcile")
    execute(store, FakeModel())
    _force_legacy_unresolved_reason_not_null(store)
    result = reconcile_content(data_dir=store.data_dir, backup_dir=tmp_path / "backups")
    assert result["counts"]["foreign_key_errors"] == 0
    assert service.get(owner, "post:1")["translation"] == "译文正文"
    assert ready(store.connect())
    store.connect().execute("DELETE FROM user_content_items")
    store.connect().commit()
    assert store.connect().execute("SELECT COUNT(*) FROM content_translations").fetchone()[0] == 0


def test_legacy_reconcile_still_rejects_unknown_content_dependencies(setup, tmp_path):
    from scripts.repair_user_content_v5 import reconcile_content
    from test_content_repair_v5 import _force_legacy_unresolved_reason_not_null

    _, store, _ = setup
    _force_legacy_unresolved_reason_not_null(store)
    store.connect().execute("CREATE TABLE unknown_child(content_id TEXT REFERENCES user_content_items(id))")
    store.connect().commit()
    with pytest.raises(RuntimeError, match="inbound foreign keys"):
        reconcile_content(data_dir=store.data_dir, backup_dir=tmp_path / "backups")
    assert store.connect().execute("SELECT COUNT(*) FROM user_content_items").fetchone()[0] == 1
