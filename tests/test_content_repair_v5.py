from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import repair_user_content_v5 as repair_v5
from scripts.repair_user_content_v5 import (
    apply_content_repair,
    enqueue_content_repair,
    inspect_content,
)
from src.models import ContentItem, SourceType
from src.services.content_repair import repair_existing_content
from src.services.job_queue import JobQueue
from src.services.user_content_store import UserContentStore
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


PNG = b"\x89PNG\r\n\x1a\n" + b"safe-image"


def _store(tmp_path, monkeypatch):
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
        display_name="Repair RSS",
        config={"url": "https://example.com/feed.xml"},
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="legacy-repair-snapshot",
        payload={
            "generated_at": "2026-07-14T01:00:00+00:00",
            "items": [{
                "id": "rss:repair:1",
                "title": "Repair me",
                "url": "https://example.com/post",
                "source_type": "rss",
                "source_id": source_id,
                "subscription_id": subscription["id"],
                "published_at": "2026-07-14T00:00:00+00:00",
                "summary_zh": "短摘要",
            }],
        },
    )
    legacy_item = {
        "id": "rss:repair:1",
        "title": "Repair me",
        "url": "https://example.com/post",
        "source_type": "rss",
        "source_id": source_id,
        "subscription_id": subscription["id"],
        "published_at": "2026-07-14T00:00:00+00:00",
        "summary_zh": "短摘要",
        "remote_media_urls": ["https://example.com/a.png", "https://example.com/b.png"],
        "presentation": {
            "content": {
                "body_text": "来源接口提供的完整正文。",
                "body_completeness": "captured",
                "body_truncated": False,
            },
        },
    }
    payload = {
        "generated_at": "2026-07-14T01:00:00+00:00",
        "items": [legacy_item],
    }
    store.connect().execute(
        "UPDATE user_feed_snapshots SET payload_json = ? WHERE job_id = ?",
        (json.dumps(payload, ensure_ascii=False), "legacy-repair-snapshot"),
    )
    store.connect().execute(
        "UPDATE user_feed_items SET item_json = ? WHERE article_id = ?",
        (json.dumps(legacy_item, ensure_ascii=False), "rss:repair:1"),
    )
    store.connect().execute(
        "UPDATE user_content_items SET body_text = '短摘要', body_completeness = 'excerpt_only', analysis_input_hash = '' WHERE article_id = ?",
        ("rss:repair:1",),
    )
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 5")
    store.connect().commit()
    return store, workspace, owner, source_id, subscription


def _force_legacy_unresolved_reason_not_null(store: ServiceStore) -> None:
    connection = store.connect()
    unresolved = next(
        row
        for row in connection.execute("PRAGMA table_info(user_content_items)").fetchall()
        if row["name"] == "unresolved_reason"
    )
    if unresolved["notnull"]:
        return

    table_sql = str(
        connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'user_content_items'"
        ).fetchone()["sql"]
    )
    objects = [
        str(row["sql"])
        for row in connection.execute(
            """
            SELECT sql FROM sqlite_schema
            WHERE tbl_name = 'user_content_items'
              AND type IN ('index', 'trigger') AND sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
    ]
    columns = [
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(user_content_items)").fetchall()
    ]
    legacy_table = "user_content_items_legacy_not_null"
    legacy_sql = table_sql.replace(
        "CREATE TABLE user_content_items", f"CREATE TABLE {legacy_table}", 1
    )
    legacy_sql = re.sub(
        r"unresolved_reason\s+TEXT(?:\s+NOT\s+NULL)?"
        r"(?:\s+DEFAULT\s+(?:NULL|'[^']*'))?",
        "unresolved_reason TEXT NOT NULL DEFAULT ''",
        legacy_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    column_list = ", ".join(f'"{column}"' for column in columns)

    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE user_content_items SET unresolved_reason = '' "
            "WHERE unresolved_reason IS NULL"
        )
        connection.execute(legacy_sql)
        connection.execute(
            f"INSERT INTO {legacy_table} ({column_list}) "
            f"SELECT {column_list} FROM user_content_items"
        )
        connection.execute("DROP TABLE user_content_items")
        connection.execute(
            f"ALTER TABLE {legacy_table} RENAME TO user_content_items"
        )
        for sql in objects:
            connection.execute(sql)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _reconcile_database_state(db_path: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        columns = [
            str(row[1])
            for row in connection.execute("PRAGMA table_info(user_content_items)")
            if str(row[1]) != "unresolved_reason"
        ]
        column_list = ", ".join(f'"{column}"' for column in columns)
        return {
            "content": connection.execute(
                f"SELECT {column_list} FROM user_content_items ORDER BY id"
            ).fetchall(),
            "media": connection.execute(
                "SELECT * FROM media_assets ORDER BY id"
            ).fetchall(),
            "snapshots": connection.execute(
                "SELECT * FROM user_feed_snapshots ORDER BY id"
            ).fetchall(),
            "jobs": connection.execute("SELECT * FROM fetch_jobs ORDER BY id").fetchall(),
            "objects": connection.execute(
                """
                SELECT type, name, sql FROM sqlite_schema
                WHERE tbl_name = 'user_content_items'
                  AND type IN ('index', 'trigger') AND sql IS NOT NULL
                ORDER BY type, name
                """
            ).fetchall(),
            "foreign_keys": connection.execute(
                "PRAGMA foreign_key_list(user_content_items)"
            ).fetchall(),
        }
    finally:
        connection.close()


def _add_reconcile_rows(
    store: ServiceStore, *, workspace_id: str, user_id: str
) -> None:
    UserContentStore(store).upsert_items(
        workspace_id=workspace_id,
        user_id=user_id,
        items=[
            {"id": "rss:repair:only-stale", "title": "Only stale reason"},
            {"id": "rss:repair:stale-tail", "title": "Stale tail reason"},
            {"id": "rss:repair:stale-surrounded", "title": "Stale surrounded reason"},
            {"id": "rss:repair:exactness", "title": "Exact token only"},
            {"id": "rss:repair:blank", "title": "Blank captured body"},
            {"id": "rss:repair:excerpt", "title": "Excerpt only"},
        ],
        seen_at="2026-07-14T03:00:00+00:00",
    )
    store.connect().executemany(
        """
        UPDATE user_content_items
        SET body_text = ?, body_completeness = ?, analysis_input_hash = ?,
            unresolved_reason = ?
        WHERE article_id = ?
        """,
        [
            (
                "Captured body one",
                "captured",
                "hash-one",
                "source_body_not_available;media_cache_failed:2",
                "rss:repair:1",
            ),
            (
                "Captured body two",
                "captured",
                "hash-two",
                "source_body_not_available",
                "rss:repair:only-stale",
            ),
            (
                "Captured whitespace tail",
                "captured",
                "hash-tail",
                "source_body_not_available;   ",
                "rss:repair:stale-tail",
            ),
            (
                "Captured whitespace surrounded",
                "captured",
                "hash-surrounded",
                " ; source_body_not_available ; ",
                "rss:repair:stale-surrounded",
            ),
            (
                "Captured exactness",
                "captured",
                "hash-exact",
                "source_body_not_available_extra;"
                "prefix_source_body_not_available",
                "rss:repair:exactness",
            ),
            (
                " \n\t ",
                "captured",
                "hash-blank",
                "source_body_not_available",
                "rss:repair:blank",
            ),
            (
                "Excerpt text",
                "excerpt_only",
                "hash-excerpt",
                "source_body_not_available",
                "rss:repair:excerpt",
            ),
        ],
    )
    store.connect().commit()


def test_v5_inspect_is_read_only_and_apply_repairs_body_media_with_backup(tmp_path, monkeypatch):
    store, workspace, owner, _source_id, _subscription = _store(tmp_path, monkeypatch)
    store.close()
    report_path = tmp_path / "inspection.json"

    inspected = inspect_content(data_dir=tmp_path, output=report_path)
    assert inspected["status"] == "inspection_complete"
    assert inspected["counts"]["excerpt_only"] == 1
    assert inspected["counts"]["legacy_media_candidates"] == 2
    assert inspected["backup_path"] is None
    assert report_path.is_file()
    assert not (tmp_path / "backups").exists()

    calls: list[str] = []

    def fetch_image(url: str):
        calls.append(url)
        if url.endswith("b.png"):
            raise TimeoutError("expired")
        return PNG, "image/png"

    applied = apply_content_repair(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        cache_legacy_media=True,
        fetch_image=fetch_image,
    )
    reopened = ServiceStore(tmp_path)
    reopened.initialize()
    row = reopened.connect().execute(
        "SELECT body_text, body_completeness, analysis_input_hash, unresolved_reason FROM user_content_items WHERE article_id = ?",
        ("rss:repair:1",),
    ).fetchone()
    detail = __import__("src.services.user_content_store", fromlist=["UserContentStore"]).UserContentStore(reopened).detail_item(
        workspace_id=workspace["id"], user_id=owner["id"], article_id="rss:repair:1"
    )

    assert applied["status"] == "applied"
    assert applied["repaired_body"] == 1
    assert applied["repaired_media"] == 1
    assert len(calls) == 2
    backup = Path(applied["backup_path"])
    assert backup.is_file() and backup.stat().st_mode & 0o777 == 0o600
    assert row["body_text"] == "来源接口提供的完整正文。"
    assert row["body_completeness"] == "captured"
    assert len(row["analysis_input_hash"]) == 64
    assert "media_cache_failed" in row["unresolved_reason"]
    assert detail["presentation"]["media"]["count"] == 1
    assert all(image["url"].startswith("/api/media/") for image in detail["presentation"]["media"]["images"])
    assert "https://example.com/a.png" not in json.dumps(detail)
    assert reopened.connect().execute("SELECT 1 FROM schema_migrations WHERE version = 5").fetchone()
    assert reopened.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert reopened.connect().execute("PRAGMA foreign_key_check").fetchall() == []

    second = apply_content_repair(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        cache_legacy_media=True,
        fetch_image=fetch_image,
    )
    assert second["status"] == "already_applied"
    assert second["backup_path"] is None


def test_inspect_counts_exact_stale_tokens_and_reconcile_is_safe_and_idempotent(
    tmp_path, monkeypatch
):
    store, workspace, owner, source_id, subscription = _store(tmp_path, monkeypatch)
    _add_reconcile_rows(
        store, workspace_id=workspace["id"], user_id=owner["id"]
    )
    historical_job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="content_repair",
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"maintenance_only": True},
    )
    store.connect().execute(
        "UPDATE fetch_jobs SET status = 'succeeded' WHERE id = ?",
        (historical_job["id"],),
    )
    store.connect().execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, user_id, source_id, subscription_id, article_id,
            asset_kind, remote_url, local_path, mime_type, byte_size, checksum,
            width, height, alt, visibility_scope, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "med_reconcile_unchanged",
            workspace["id"],
            owner["id"],
            source_id,
            subscription["id"],
            "rss:repair:1",
            "content_image",
            "https://example.com/unchanged.png",
            "media/unchanged.png",
            "image/png",
            18,
            "checksum-before-reconcile",
            320,
            180,
            "unchanged",
            "private",
            "ready",
            "2026-07-14T04:00:00+00:00",
            "2026-07-14T04:00:00+00:00",
        ),
    )
    store.connect().execute(
        "CREATE INDEX test_user_content_article ON user_content_items(article_id)"
    )
    store.connect().execute(
        """
        CREATE TRIGGER test_user_content_body_audit
        AFTER UPDATE OF body_text ON user_content_items
        BEGIN
            SELECT 1;
        END
        """
    )
    store.connect().commit()
    _force_legacy_unresolved_reason_not_null(store)
    store.close()

    db_path = tmp_path / "service.db"
    database_bytes = db_path.read_bytes()
    inspection_path = tmp_path / "inspection.json"
    inspected = inspect_content(data_dir=tmp_path, output=inspection_path)

    assert inspected["counts"]["stale_unresolved"] == 4
    assert inspected["counts"]["reconciled_unresolved"] == 0
    assert db_path.read_bytes() == database_bytes
    assert json.loads(inspection_path.read_text(encoding="utf-8")) == inspected

    before = _reconcile_database_state(db_path)
    reconciled = repair_v5.reconcile_content(
        data_dir=tmp_path, backup_dir=tmp_path / "backups"
    )
    after = _reconcile_database_state(db_path)

    assert set(reconciled) == {
        "status",
        "counts",
        "repaired_body",
        "repaired_media",
        "enqueued_sources",
        "unresolved",
        "backup_path",
    }
    assert reconciled["status"] == "reconciled"
    assert reconciled["counts"]["reconciled_unresolved"] == 4
    assert reconciled["counts"]["stale_unresolved"] == 0
    assert reconciled["counts"]["schema_upgraded"] == 1
    assert reconciled["counts"]["integrity_check"] == "ok"
    assert reconciled["counts"]["foreign_key_errors"] == 0
    backup = Path(reconciled["backup_path"])
    assert backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600
    assert before == after

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        reasons = {
            str(row["article_id"]): row["unresolved_reason"]
            for row in connection.execute(
                "SELECT article_id, unresolved_reason FROM user_content_items"
            ).fetchall()
        }
        unresolved_column = next(
            row
            for row in connection.execute(
                "PRAGMA table_info(user_content_items)"
            ).fetchall()
            if row["name"] == "unresolved_reason"
        )
    finally:
        connection.close()
    assert reasons["rss:repair:1"] == "media_cache_failed:2"
    assert reasons["rss:repair:only-stale"] is None
    assert reasons["rss:repair:stale-tail"] is None
    assert reasons["rss:repair:stale-surrounded"] is None
    assert reasons["rss:repair:exactness"] == (
        "source_body_not_available_extra;prefix_source_body_not_available"
    )
    assert reasons["rss:repair:blank"] == "source_body_not_available"
    assert reasons["rss:repair:excerpt"] == "source_body_not_available"
    assert unresolved_column["notnull"] == 0
    assert inspect_content(data_dir=tmp_path)["counts"]["stale_unresolved"] == 0

    backups_before = sorted((tmp_path / "backups").iterdir())
    second = repair_v5.reconcile_content(
        data_dir=tmp_path, backup_dir=tmp_path / "backups"
    )
    assert second["status"] == "already_reconciled"
    assert second["backup_path"] is None
    assert second["counts"]["reconciled_unresolved"] == 0
    assert second["counts"]["stale_unresolved"] == 0
    assert second["counts"]["schema_upgraded"] == 0
    assert sorted((tmp_path / "backups").iterdir()) == backups_before


def test_reconcile_upgrades_legacy_not_null_schema_even_without_stale_rows(
    tmp_path, monkeypatch
):
    store, _workspace, _owner, _source_id, _subscription = _store(
        tmp_path, monkeypatch
    )
    store.connect().execute(
        """
        UPDATE user_content_items
        SET body_text = 'Captured', body_completeness = 'captured',
            unresolved_reason = 'media_cache_failed:1'
        """
    )
    store.connect().commit()
    _force_legacy_unresolved_reason_not_null(store)
    store.close()

    reconciled = repair_v5.reconcile_content(
        data_dir=tmp_path, backup_dir=tmp_path / "backups"
    )

    assert reconciled["status"] == "reconciled"
    assert reconciled["counts"]["reconciled_unresolved"] == 0
    assert reconciled["counts"]["stale_unresolved"] == 0
    assert reconciled["counts"]["schema_upgraded"] == 1
    assert Path(reconciled["backup_path"]).is_file()
    connection = sqlite3.connect(tmp_path / "service.db")
    try:
        unresolved_column = next(
            row
            for row in connection.execute(
                "PRAGMA table_info(user_content_items)"
            ).fetchall()
            if row[1] == "unresolved_reason"
        )
        reason = connection.execute(
            "SELECT unresolved_reason FROM user_content_items"
        ).fetchone()[0]
    finally:
        connection.close()
    assert unresolved_column[3] == 0
    assert reason == "media_cache_failed:1"


def test_reconcile_converts_legacy_captured_empty_reason_to_null(
    tmp_path, monkeypatch
):
    store, _workspace, _owner, _source_id, _subscription = _store(
        tmp_path, monkeypatch
    )
    store.connect().execute(
        """
        UPDATE user_content_items
        SET body_text = 'Captured', body_completeness = 'captured',
            unresolved_reason = ''
        """
    )
    store.connect().commit()
    _force_legacy_unresolved_reason_not_null(store)
    store.close()

    assert inspect_content(data_dir=tmp_path)["counts"]["stale_unresolved"] == 1

    reconciled = repair_v5.reconcile_content(
        data_dir=tmp_path, backup_dir=tmp_path / "backups"
    )

    assert reconciled["status"] == "reconciled"
    assert reconciled["counts"]["reconciled_unresolved"] == 1
    assert reconciled["counts"]["schema_upgraded"] == 1
    connection = sqlite3.connect(tmp_path / "service.db")
    try:
        reason = connection.execute(
            "SELECT unresolved_reason FROM user_content_items"
        ).fetchone()[0]
    finally:
        connection.close()
    assert reason is None
    assert inspect_content(data_dir=tmp_path)["counts"]["stale_unresolved"] == 0


def test_reconcile_refuses_active_workers_before_backup(tmp_path, monkeypatch):
    store, _workspace, _owner, _source_id, _subscription = _store(
        tmp_path, monkeypatch
    )
    store.connect().execute(
        """
        UPDATE user_content_items
        SET body_text = 'Captured', body_completeness = 'captured',
            unresolved_reason = 'source_body_not_available'
        """
    )
    store.connect().commit()
    store.close()
    monkeypatch.setattr(
        repair_v5, "_active_workers", lambda _db_path: ["worker-active"]
    )

    with pytest.raises(RuntimeError, match="stop all horizon-worker"):
        repair_v5.reconcile_content(
            data_dir=tmp_path, backup_dir=tmp_path / "backups"
        )

    assert not (tmp_path / "backups").exists()
    connection = sqlite3.connect(tmp_path / "service.db")
    try:
        reason = connection.execute(
            "SELECT unresolved_reason FROM user_content_items"
        ).fetchone()[0]
    finally:
        connection.close()
    assert reason == "source_body_not_available"


@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_reconcile_refuses_active_jobs_before_backup(
    tmp_path, monkeypatch, job_status
):
    store, workspace, owner, source_id, subscription = _store(tmp_path, monkeypatch)
    store.connect().execute(
        """
        UPDATE user_content_items
        SET body_text = 'Captured', body_completeness = 'captured',
            unresolved_reason = 'source_body_not_available'
        """
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="content_repair",
        source_id=source_id,
        subscription_id=subscription["id"],
        payload={"private_marker": "must-not-leak"},
    )
    store.connect().execute(
        "UPDATE fetch_jobs SET status = ? WHERE id = ?",
        (job_status, job["id"]),
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError) as exc_info:
        repair_v5.reconcile_content(
            data_dir=tmp_path, backup_dir=tmp_path / "backups"
        )

    assert "active fetch job" in str(exc_info.value).lower()
    assert "must-not-leak" not in str(exc_info.value)
    assert not (tmp_path / "backups").exists()
    connection = sqlite3.connect(tmp_path / "service.db")
    try:
        reason = connection.execute(
            "SELECT unresolved_reason FROM user_content_items"
        ).fetchone()[0]
        stored_status = connection.execute(
            "SELECT status FROM fetch_jobs WHERE id = ?", (job["id"],)
        ).fetchone()[0]
    finally:
        connection.close()
    assert reason == "source_body_not_available"
    assert stored_status == job_status


def test_reconcile_rolls_back_reason_changes_when_foreign_key_check_fails(
    tmp_path, monkeypatch
):
    store, _workspace, _owner, _source_id, _subscription = _store(
        tmp_path, monkeypatch
    )
    connection = store.connect()
    connection.execute(
        """
        UPDATE user_content_items
        SET body_text = 'Captured', body_completeness = 'captured',
            unresolved_reason = 'source_body_not_available'
        """
    )
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        "UPDATE user_content_items SET source_id = 'missing-source'"
    )
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")
    store.close()

    with pytest.raises(RuntimeError, match="foreign key check failed"):
        repair_v5.reconcile_content(
            data_dir=tmp_path, backup_dir=tmp_path / "backups"
        )

    connection = sqlite3.connect(tmp_path / "service.db")
    try:
        reason = connection.execute(
            "SELECT unresolved_reason FROM user_content_items"
        ).fetchone()[0]
    finally:
        connection.close()
    assert reason == "source_body_not_available"
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_reconcile_cli_subcommand_prints_fixed_report(tmp_path, monkeypatch, capsys):
    store, _workspace, _owner, _source_id, _subscription = _store(
        tmp_path, monkeypatch
    )
    store.close()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repair_user_content_v5.py",
            "reconcile",
            "--data-dir",
            str(tmp_path),
            "--backup-dir",
            str(tmp_path / "backups"),
        ],
    )

    repair_v5.main()

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "already_reconciled"
    assert report["counts"]["stale_unresolved"] == 0


def test_enqueue_free_content_repairs_skips_paid_sources(tmp_path, monkeypatch):
    store, workspace, owner, source_id, _subscription = _store(tmp_path, monkeypatch)
    paid_source_id = store.create_source(
        workspace_id=workspace["id"], scope="private", owner_user_id=owner["id"],
        source_type="apify_social", display_name="Paid Instagram",
        config={"platform": "instagram", "kind": "profile", "target": "example", "fetch_limit": 1},
        secret_env="APIFY_TOKEN",
    )
    store.create_subscription(user_id=owner["id"], source_id=paid_source_id)
    store.connect().execute(
        "UPDATE user_content_items SET source_id = ? WHERE article_id = ?",
        (paid_source_id, "rss:repair:1"),
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"], job_id="free-extra",
        payload={"generated_at": "2026-07-14T02:00:00+00:00", "items": [{
            "id": "rss:repair:free", "title": "Free", "source_id": source_id,
            "subscription_id": store.get_user_subscription_for_source(owner["id"], source_id)["id"],
        }]},
    )
    store.close()

    report = enqueue_content_repair(data_dir=tmp_path, free_only=True)
    reopened = ServiceStore(tmp_path)
    reopened.initialize()
    jobs = reopened.connect().execute(
        "SELECT job_type, source_id FROM fetch_jobs WHERE job_type = 'content_repair'"
    ).fetchall()

    assert report["status"] == "enqueued"
    assert report["enqueued_sources"] == [source_id]
    assert [(row["job_type"], row["source_id"]) for row in jobs] == [("content_repair", source_id)]
    assert any(item["source_id"] == paid_source_id and item["reason"] == "paid_source_requires_authorization" for item in report["unresolved"])


def test_content_repair_job_updates_only_existing_items_without_snapshot_or_ai(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _store(tmp_path, monkeypatch)
    before_snapshots = store.connect().execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0]
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"], user_id=owner["id"], job_type="content_repair",
        source_id=source_id, subscription_id=subscription["id"], payload={"hours": 87600},
    )
    existing = ContentItem(
        id="rss:repair:1", source_type=SourceType.RSS, title="Repair me",
        url="https://example.com/post", content="重新抓取到的来源正文。",
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        metadata={"source_id": source_id, "remote_media_urls": []},
    )
    unseen = existing.model_copy(update={"id": "rss:repair:new", "title": "Must not be inserted"})

    result = repair_existing_content(
        job, data_dir=str(tmp_path), store=store,
        fetch_items=lambda _job, _data_dir, _store: [existing, unseen],
    )
    row = store.connect().execute(
        "SELECT body_text, body_completeness FROM user_content_items WHERE article_id = 'rss:repair:1'"
    ).fetchone()

    assert result["job_type"] == "content_repair"
    assert result["matched_items"] == 1
    assert result["ignored_new_items"] == 1
    assert result["analysis_calls"] == 0
    assert row["body_text"] == "重新抓取到的来源正文。"
    assert row["body_completeness"] == "captured"
    assert store.connect().execute("SELECT COUNT(*) FROM user_feed_snapshots").fetchone()[0] == before_snapshots
    assert store.connect().execute("SELECT COUNT(*) FROM user_content_items WHERE article_id = 'rss:repair:new'").fetchone()[0] == 0
