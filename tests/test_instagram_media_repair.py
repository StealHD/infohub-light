import json
import sqlite3

import pytest

from src.apify_actor_identity import source_target_fingerprint
from src.services.instagram_media_repair import preview_media_repair, apply_media_repair, MediaRepairError
from src.services.user_feed_store import UserFeedStore
from src.services.user_content_store import UserContentStore
from test_actorops_v2_presentation_mapping import _repository


@pytest.fixture
def repair(tmp_path):
    store, repository, candidate = _repository(tmp_path)
    workspace = store.get_default_workspace()["id"]
    user = store.create_user(workspace_id=workspace, username="repair", password="test-only-password")["id"]
    source = store.create_source(workspace_id=workspace, scope="workspace", owner_user_id=None,
        source_type="apify_social", display_name="Instagram", config={"platform": "instagram", "target": "openai"})
    subscription = store.create_subscription(user_id=user, source_id=source)
    conn = store.connect()
    route = candidate.route_id
    fingerprint = source_target_fingerprint(workspace, route, "openai", platform="instagram")
    conn.execute("""INSERT INTO actor_source_bindings_v2(binding_id,workspace_id,source_id,
        route_id,target_fingerprint,status,binding_version,created_at,updated_at)
        VALUES('media-binding',?,?,?,?,'ready',1,'2026-08-20','2026-08-20')""",
        (workspace, source, route, fingerprint))
    conn.commit()
    item = {"id": "legacy-one", "title": "Keep title", "url": "https://www.instagram.com/p/one/",
        "source_type": "instagram", "source_id": source, "subscription_id": subscription["id"],
        "published_at": "2026-08-20T00:00:00Z", "summary_zh": "Keep analysis",
        "presentation": {"content": {"body_text": "Keep caption", "format": "social_post"}}}
    UserFeedStore(store).save_snapshot(workspace_id=workspace, user_id=user, job_id="media-snapshot",
        payload={"generated_at": "2026-08-20T00:00:00Z", "items": [item]})
    # Simulate privately stored legacy URLs; snapshots deliberately stay unchanged.
    item["remote_media_urls"] = ["https://cdn.example/a.png", "https://cdn.example/b.png"]
    conn.execute("UPDATE user_content_items SET item_json=? WHERE article_id='legacy-one'", (json.dumps(item),))
    conn.commit()
    yield store, dict(workspace_id=workspace, user_id=user, source_id=source, article_id="legacy-one"), candidate
    store.close()


def image(url):
    return b"\x89PNG\r\n\x1a\n" + url.encode(), "image/png"


def record(store):
    return dict(store.connect().execute("SELECT * FROM user_content_items WHERE article_id='legacy-one'").fetchone())


def test_preview_apply_idempotence_and_exact_media_only_mutation(repair):
    store, args, _ = repair
    conn = store.connect()
    before = record(store)
    immutable = {name: [tuple(row) for row in conn.execute(f"SELECT * FROM {name}")] for name in
        ("user_feed_snapshots", "user_feed_items", "actor_source_bindings_v2", "actor_attempts_v2", "apify_actor_runs")}
    def no_dataset(*_):
        pytest.fail("saved URLs must not read a Dataset")
    plan = preview_media_repair(store, **args, reader=no_dataset)
    assert record(store) == before
    result = apply_media_repair(store, plan, expected_preview=plan.fingerprint, fetch_image=image)
    assert result["cached_images"] == 2 and result["updated"]
    after = record(store)
    for key in before.keys() - {"item_json", "updated_at"}:
        assert before[key] == after[key]
    parsed = json.loads(after["item_json"])
    assert parsed["summary_zh"] == "Keep analysis"
    assert parsed["presentation"]["content"]["body_text"] == "Keep caption"
    assert all(x["url"].startswith("/api/media/") for x in parsed["presentation"]["media"]["images"])
    detail = UserContentStore(store).detail_item(**{key: value for key, value in args.items() if key != "source_id"})
    assert [x["url"] for x in detail["presentation"]["media"]["images"]] == parsed["media_urls"]
    for name, rows in immutable.items():
        assert [tuple(row) for row in conn.execute(f"SELECT * FROM {name}")] == rows
    again = preview_media_repair(store, **args, reader=no_dataset)
    assert not apply_media_repair(store, again, expected_preview=again.fingerprint, fetch_image=image)["updated"]
    assert conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 2


def test_concurrent_update_and_wrong_scope_refused(repair):
    store, args, _ = repair
    plan = preview_media_repair(store, **args)
    store.connect().execute("UPDATE user_content_items SET updated_at='concurrent'")
    store.connect().commit()
    with pytest.raises(MediaRepairError, match="preview_changed"):
        apply_media_repair(store, plan, expected_preview=plan.fingerprint, fetch_image=image)
    with pytest.raises(MediaRepairError, match="unavailable"):
        preview_media_repair(store, **{**args, "user_id": "other"})
    assert store.connect().execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 0


def test_partial_download_retry_and_rollback_cleans_new_files(repair):
    store, args, _ = repair
    plan = preview_media_repair(store, **args)
    def partial(url):
        if url.endswith("b.png"):
            raise ValueError("expired")
        return image(url)
    result = apply_media_repair(store, plan, expected_preview=plan.fingerprint, fetch_image=partial)
    assert result["status"] == "partial" and result["cached_images"] == 1
    plan = preview_media_repair(store, **args)
    files = set((store.data_dir / "media").rglob("*.png"))
    store.connect().execute("""CREATE TRIGGER reject_media_projection BEFORE UPDATE ON user_content_items
        BEGIN SELECT RAISE(ABORT,'test rollback'); END""")
    store.connect().commit()
    # Trigger alters DB schema, not item state; the projection transaction rolls back.
    with pytest.raises(sqlite3.IntegrityError, match="test rollback"):
        apply_media_repair(store, plan, expected_preview=plan.fingerprint, fetch_image=image)
    assert set((store.data_dir / "media").rglob("*.png")) == files
    assert store.connect().execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 1


def test_changed_preview_media_is_refused(repair):
    store, args, _ = repair
    plan = preview_media_repair(store, **args)
    with pytest.raises(MediaRepairError, match="preview_changed"):
        apply_media_repair(store, plan, expected_preview="different", fetch_image=image)


def test_retry_restores_original_order_instead_of_appending_missing_middle(repair):
    store, args, _ = repair
    original = json.loads(record(store)["item_json"])
    original["remote_media_urls"].append("https://cdn.example/c.png")
    store.connect().execute("UPDATE user_content_items SET item_json=?", (json.dumps(original),))
    store.connect().commit()
    def partial(url):
        if url.endswith("b.png"):
            raise ValueError("expired")
        return image(url)
    plan = preview_media_repair(store, **args)
    apply_media_repair(store, plan, expected_preview=plan.fingerprint, fetch_image=partial)
    plan = preview_media_repair(store, **args)
    apply_media_repair(store, plan, expected_preview=plan.fingerprint, fetch_image=image)
    urls = json.loads(record(store)["item_json"])["media_urls"]
    remote = {f"/api/media/{row['id']}": row["remote_url"] for row in store.connect().execute("SELECT * FROM media_assets")}
    assert [remote[url] for url in urls] == original["remote_media_urls"]
