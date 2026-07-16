#!/usr/bin/env python3
"""Inspect, repair, and enqueue maintenance for stable user content."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.migrate_user_content_v4 import _active_workers
from src.ai.analysis_cache import AnalysisCache
from src.models import ContentItem, SourceType
from src.services.content_repair import source_requires_paid_acquisition
from src.services.job_queue import JobQueue
from src.services.media_cache import MediaCacheService
from src.services.user_content_store import (
    clean_captured_body,
    normalize_captured_unresolved_reason,
)
from src.storage.service_store import ServiceStore


def _empty_report(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "counts": {
            "total": 0,
            "captured": 0,
            "excerpt_only": 0,
            "cached_media": 0,
            "legacy_media_candidates": 0,
            "stale_unresolved": 0,
            "reconciled_unresolved": 0,
            "schema_upgraded": 0,
        },
        "repaired_body": 0,
        "repaired_media": 0,
        "enqueued_sources": [],
        "unresolved": [],
        "backup_path": None,
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _json_dict(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stale_unresolved_rows(
    connection: sqlite3.Connection,
) -> list[tuple[str, str | None]]:
    if not _table_exists(connection, "user_content_items"):
        return []
    stale: list[tuple[str, str | None]] = []
    rows = connection.execute(
        """
        SELECT id, body_text, body_completeness, unresolved_reason
        FROM user_content_items
        """
    ).fetchall()
    for row in rows:
        normalized = normalize_captured_unresolved_reason(
            row["unresolved_reason"],
            body_text=row["body_text"],
            body_completeness=str(row["body_completeness"]),
        )
        if normalized != row["unresolved_reason"]:
            stale.append((str(row["id"]), normalized))
    return stale


def _unresolved_reason_is_nullable(connection: sqlite3.Connection) -> bool:
    if not _table_exists(connection, "user_content_items"):
        return False
    column = next(
        (
            row
            for row in connection.execute(
                "PRAGMA table_info(user_content_items)"
            ).fetchall()
            if row["name"] == "unresolved_reason"
        ),
        None,
    )
    return column is not None and not bool(column["notnull"])


def _active_fetch_jobs(db_path: Path) -> bool:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not _table_exists(connection, "fetch_jobs"):
            return False
        return connection.execute(
            "SELECT 1 FROM fetch_jobs WHERE status IN ('queued', 'running') LIMIT 1"
        ).fetchone() is not None
    finally:
        connection.close()


def _legacy_items(connection: sqlite3.Connection) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not (_table_exists(connection, "user_feed_items") and _table_exists(connection, "user_feed_snapshots")):
        return {}
    rows = connection.execute(
        """
        SELECT snapshot.workspace_id, snapshot.user_id, feed_item.article_id,
               feed_item.item_json, snapshot.payload_json
        FROM user_feed_items AS feed_item
        JOIN user_feed_snapshots AS snapshot ON snapshot.id = feed_item.snapshot_id
        ORDER BY snapshot.created_at DESC, feed_item.position
        """
    ).fetchall()
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["workspace_id"]), str(row["user_id"]), str(row["article_id"]))
        candidate = _json_dict(row["item_json"])
        if not candidate:
            payload = _json_dict(row["payload_json"])
            candidate = next(
                (
                    item for item in payload.get("items", [])
                    if isinstance(item, dict) and str(item.get("id")) == key[2]
                ),
                {},
            )
        if candidate and key not in result:
            result[key] = candidate
    return result


def _media_urls(item: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for name in ("remote_media_urls", "media_urls"):
        if isinstance(item.get(name), list):
            values.extend(item[name])
    values.extend([item.get("remote_image_url"), item.get("image_url")])
    presentation = item.get("presentation")
    media = presentation.get("media") if isinstance(presentation, dict) else None
    if isinstance(media, dict):
        for image in media.get("images") or []:
            if isinstance(image, dict):
                values.append(image.get("remote_url") or image.get("url"))
    return list(dict.fromkeys(
        str(value).strip() for value in values
        if str(value or "").strip().startswith(("https://", "http://"))
    ))[:6]


def _captured_body(item: dict[str, Any]) -> tuple[str, bool]:
    presentation = item.get("presentation")
    content = presentation.get("content") if isinstance(presentation, dict) else None
    candidates = []
    if isinstance(content, dict):
        candidates.extend([content.get("body_text"), content.get("body")])
    candidates.extend([item.get("content"), item.get("body")])
    for candidate in candidates:
        body, truncated = clean_captured_body(candidate)
        if body:
            return body, truncated
    return "", False


def _content_item(row: dict[str, Any], legacy: dict[str, Any], body: str) -> ContentItem:
    raw_type = str(legacy.get("source_type") or "rss")
    source_type = {
        "github_release": SourceType.GITHUB,
        "github_user": SourceType.GITHUB,
        "apify_social": SourceType.INSTAGRAM,
    }.get(raw_type)
    if source_type is None:
        try:
            source_type = SourceType(raw_type)
        except ValueError:
            source_type = SourceType.RSS
    published = str(legacy.get("published_at") or row.get("first_seen_at") or "")
    try:
        published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        published_at = datetime(1970, 1, 1, tzinfo=timezone.utc)
    metadata = {
        "source_id": str(row.get("source_id") or legacy.get("source_id") or ""),
        "subscription_id": str(row.get("subscription_id") or legacy.get("subscription_id") or ""),
        "source_display_name": str(legacy.get("source") or ""),
        "catalog_source_type": raw_type,
        "channel": str(legacy.get("channel") or legacy.get("category") or ""),
        "topics": legacy.get("topics") or legacy.get("tags") or [],
        "remote_media_urls": _media_urls(legacy),
    }
    return ContentItem(
        id=str(row["article_id"]),
        source_type=source_type,
        title=str(legacy.get("title") or row["article_id"]),
        url=str(legacy.get("url") or f"https://invalid.local/content/{row['article_id']}"),
        content=body or None,
        author=str(legacy.get("author") or "") or None,
        published_at=published_at,
        metadata=metadata,
    )


def _write_report(path: Path | str, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)


def inspect_content(*, data_dir: Path | str, output: Path | str | None = None) -> dict[str, Any]:
    db_path = Path(data_dir) / "service.db"
    report = _empty_report("inspection_complete")
    if not db_path.exists():
        report["status"] = "database_missing"
        if output is not None:
            _write_report(output, report)
        return report
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if _table_exists(connection, "user_content_items"):
            rows = connection.execute(
                "SELECT body_completeness FROM user_content_items"
            ).fetchall()
            report["counts"]["total"] = len(rows)
            report["counts"]["captured"] = sum(row[0] == "captured" for row in rows)
            report["counts"]["excerpt_only"] = sum(row[0] == "excerpt_only" for row in rows)
            report["counts"]["stale_unresolved"] = len(
                _stale_unresolved_rows(connection)
            )
        if _table_exists(connection, "media_assets"):
            report["counts"]["cached_media"] = int(connection.execute(
                "SELECT COUNT(*) FROM media_assets WHERE asset_kind = 'content_image' AND status = 'ready'"
            ).fetchone()[0])
        legacy = _legacy_items(connection)
        report["counts"]["legacy_media_candidates"] = len({url for item in legacy.values() for url in _media_urls(item)})
    finally:
        connection.close()
    if output is not None:
        _write_report(output, report)
    return report


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"service-user-content-v5-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(target, 0o600)
    return target


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _incoming_user_content_foreign_keys(
    connection: sqlite3.Connection,
) -> list[tuple[str, str]]:
    incoming: list[tuple[str, str]] = []
    tables = connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for table in tables:
        table_name = str(table["name"])
        if table_name == "user_content_items":
            continue
        for foreign_key in connection.execute(
            f"PRAGMA foreign_key_list({_quoted_identifier(table_name)})"
        ).fetchall():
            if str(foreign_key["table"]) == "user_content_items":
                incoming.append((table_name, str(foreign_key["from"])))
    return incoming


def _upgrade_unresolved_reason_to_nullable(
    connection: sqlite3.Connection,
) -> None:
    if _unresolved_reason_is_nullable(connection):
        return
    incoming = _incoming_user_content_foreign_keys(connection)
    if incoming:
        raise RuntimeError(
            "cannot safely rebuild user_content_items with inbound foreign keys: "
            + ", ".join(f"{table}.{column}" for table, column in incoming)
        )
    table_row = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'user_content_items'"
    ).fetchone()
    if table_row is None or not table_row["sql"]:
        raise RuntimeError("user_content_items schema is unavailable")
    table_sql = str(table_row["sql"])
    replacement_table = "user_content_items__reconcile"
    replacement_sql, table_substitutions = re.subn(
        r"^(\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)"
        r"(?:user_content_items|\"user_content_items\"|`user_content_items`|"
        r"\[user_content_items\])",
        lambda match: match.group(1) + replacement_table,
        table_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    replacement_sql, column_substitutions = re.subn(
        r"(\bunresolved_reason\s+TEXT)\s+NOT\s+NULL"
        r"(?:\s+DEFAULT\s+(?:''|NULL))?",
        r"\1",
        replacement_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if table_substitutions != 1 or column_substitutions != 1:
        raise RuntimeError("unsupported user_content_items schema for nullable upgrade")

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
        for row in connection.execute(
            "PRAGMA table_xinfo(user_content_items)"
        ).fetchall()
        if int(row["hidden"] or 0) == 0
    ]
    column_list = ", ".join(_quoted_identifier(column) for column in columns)
    foreign_keys_before = [
        tuple(row)
        for row in connection.execute(
            "PRAGMA foreign_key_list(user_content_items)"
        ).fetchall()
    ]

    connection.execute(replacement_sql)
    connection.execute(
        f"INSERT INTO {_quoted_identifier(replacement_table)} ({column_list}) "
        f"SELECT {column_list} FROM user_content_items"
    )
    connection.execute("DROP TABLE user_content_items")
    connection.execute(
        f"ALTER TABLE {_quoted_identifier(replacement_table)} "
        "RENAME TO user_content_items"
    )
    for sql in objects:
        connection.execute(sql)

    foreign_keys_after = [
        tuple(row)
        for row in connection.execute(
            "PRAGMA foreign_key_list(user_content_items)"
        ).fetchall()
    ]
    if foreign_keys_after != foreign_keys_before:
        raise RuntimeError("user_content_items foreign keys changed during rebuild")
    if not _unresolved_reason_is_nullable(connection):
        raise RuntimeError("unresolved_reason remained NOT NULL after rebuild")


def reconcile_content(
    *, data_dir: Path | str, backup_dir: Path | str
) -> dict[str, Any]:
    data_path = Path(data_dir)
    db_path = data_path / "service.db"
    report = inspect_content(data_dir=data_path)
    if not db_path.exists():
        raise FileNotFoundError(f"service database not found: {db_path}")

    read_only = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    read_only.row_factory = sqlite3.Row
    try:
        schema_upgrade_required = not _unresolved_reason_is_nullable(read_only)
    finally:
        read_only.close()
    if not report["counts"]["stale_unresolved"] and not schema_upgrade_required:
        report["status"] = "already_reconciled"
        return report
    if _active_workers(db_path):
        raise RuntimeError(
            "stop all horizon-worker processes before reconciling user content"
        )
    if _active_fetch_jobs(db_path):
        raise RuntimeError(
            "stop all active fetch jobs before reconciling user content"
        )

    backup = _backup_database(db_path, Path(backup_dir))
    report["backup_path"] = str(backup)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        if schema_upgrade_required:
            _upgrade_unresolved_reason_to_nullable(connection)
        stale = _stale_unresolved_rows(connection)
        for row_id, unresolved_reason in stale:
            connection.execute(
                "UPDATE user_content_items SET unresolved_reason = ? WHERE id = ?",
                (unresolved_reason, row_id),
            )
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity.lower() != "ok":
            raise RuntimeError(f"integrity check failed: {integrity}")
        if foreign_keys:
            raise RuntimeError(
                f"foreign key check failed: {len(foreign_keys)} row(s)"
            )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

    report["status"] = "reconciled"
    report["counts"]["reconciled_unresolved"] = len(stale)
    report["counts"]["stale_unresolved"] = 0
    report["counts"]["schema_upgraded"] = int(schema_upgrade_required)
    report["counts"]["integrity_check"] = "ok"
    report["counts"]["foreign_key_errors"] = 0
    return report


def apply_content_repair(
    *, data_dir: Path | str, backup_dir: Path | str, cache_legacy_media: bool,
    fetch_image: Callable[[str], tuple[bytes, str]] | None = None,
) -> dict[str, Any]:
    data_path = Path(data_dir)
    db_path = data_path / "service.db"
    report = inspect_content(data_dir=data_path)
    if not db_path.exists():
        raise FileNotFoundError(f"service database not found: {db_path}")
    ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        already = bool(_table_exists(ro, "schema_migrations") and ro.execute("SELECT 1 FROM schema_migrations WHERE version = 5").fetchone())
    finally:
        ro.close()
    if already:
        report["status"] = "already_applied"
        return report
    if _active_workers(db_path):
        raise RuntimeError("stop all horizon-worker processes before applying user content v5 repair")

    backup = _backup_database(db_path, Path(backup_dir))
    report["backup_path"] = str(backup)
    store = ServiceStore(data_path)
    store.initialize()
    conn = store.connect()
    legacy = _legacy_items(conn)
    media_cache = MediaCacheService(store, data_dir=data_path, fetch_image=fetch_image)
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM user_content_items ORDER BY first_seen_at, id").fetchall()]
        for row in rows:
            key = (str(row["workspace_id"]), str(row["user_id"]), str(row["article_id"]))
            item_data = legacy.get(key, {})
            body, body_truncated = _captured_body(item_data)
            repaired_body = False
            reasons: list[str] = []
            if row["body_completeness"] != "captured" and body:
                conn.execute(
                    """
                    UPDATE user_content_items
                    SET body_text = ?, body_truncated = ?, body_completeness = 'captured'
                    WHERE id = ?
                    """,
                    (body, 1 if body_truncated else 0, row["id"]),
                )
                row["body_text"] = body
                repaired_body = True
                report["repaired_body"] += 1
            elif row["body_completeness"] != "captured":
                reasons.append("source_body_not_available")

            model_item = _content_item(row, item_data, str(row.get("body_text") or body or ""))
            conn.execute(
                "UPDATE user_content_items SET analysis_input_hash = ? WHERE id = ?",
                (AnalysisCache.content_hash(model_item), row["id"]),
            )
            urls = _media_urls(item_data)
            if cache_legacy_media and urls:
                before = int(conn.execute(
                    "SELECT COUNT(*) FROM media_assets WHERE workspace_id = ? AND user_id = ? AND article_id = ? AND asset_kind = 'content_image' AND status = 'ready'",
                    (row["workspace_id"], row["user_id"], row["article_id"]),
                ).fetchone()[0])
                media_cache.cache_items(
                    workspace_id=str(row["workspace_id"]), user_id=str(row["user_id"]), items=[model_item]
                )
                ready_urls = {
                    str(asset["remote_url"])
                    for asset in conn.execute(
                        "SELECT remote_url FROM media_assets WHERE workspace_id = ? AND user_id = ? AND article_id = ? AND asset_kind = 'content_image' AND status = 'ready'",
                        (row["workspace_id"], row["user_id"], row["article_id"]),
                    ).fetchall()
                }
                after = len(ready_urls)
                report["repaired_media"] += max(after - before, 0)
                failed = [url for url in urls if url not in ready_urls]
                if failed:
                    reasons.append(f"media_cache_failed:{len(failed)}")
            elif urls:
                reasons.append("legacy_media_not_cached")
            reason = ";".join(reasons)
            conn.execute(
                "UPDATE user_content_items SET unresolved_reason = ?, updated_at = updated_at WHERE id = ?",
                (reason, row["id"]),
            )
            if reason:
                report["unresolved"].append({
                    "article_id": row["article_id"], "source_id": row.get("source_id") or "", "reason": reason,
                })
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if foreign_keys:
            raise RuntimeError(f"foreign key check failed: {len(foreign_keys)} row(s)")
        if str(integrity).lower() != "ok":
            raise RuntimeError(f"integrity check failed: {integrity}")
        store.mark_user_content_v5_migrated(commit=False)
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        store.close()
    report["status"] = "applied"
    report["counts"]["foreign_key_errors"] = 0
    report["counts"]["integrity_check"] = "ok"
    return report


def enqueue_content_repair(*, data_dir: Path | str, free_only: bool) -> dict[str, Any]:
    if not free_only:
        raise ValueError("bulk repair requires --free-only; paid sources need per-item authorization")
    report = inspect_content(data_dir=data_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    queue = JobQueue(store)
    try:
        rows = store.connect().execute(
            """
            SELECT content.workspace_id, content.user_id, content.source_id,
                   MIN(content.subscription_id) AS subscription_id
            FROM user_content_items AS content
            WHERE content.body_completeness = 'excerpt_only' AND content.source_id IS NOT NULL
            GROUP BY content.workspace_id, content.user_id, content.source_id
            ORDER BY content.source_id, content.user_id
            """
        ).fetchall()
        for row in rows:
            source = store.get_source(str(row["source_id"]))
            if source is None:
                report["unresolved"].append({"source_id": row["source_id"], "reason": "source_missing"})
                continue
            if source_requires_paid_acquisition(source):
                report["unresolved"].append({"source_id": row["source_id"], "reason": "paid_source_requires_authorization"})
                continue
            active = store.connect().execute(
                """
                SELECT 1 FROM fetch_jobs
                WHERE workspace_id = ? AND user_id = ? AND source_id = ?
                  AND job_type = 'content_repair' AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (row["workspace_id"], row["user_id"], row["source_id"]),
            ).fetchone()
            if active:
                continue
            queue.create_job(
                workspace_id=str(row["workspace_id"]), user_id=str(row["user_id"]),
                job_type="content_repair", source_id=str(row["source_id"]),
                subscription_id=str(row["subscription_id"] or "") or None,
                payload={"hours": 24 * 3650, "maintenance_only": True}, max_attempts=2,
            )
            report["enqueued_sources"].append(str(row["source_id"]))
    finally:
        store.close()
    report["enqueued_sources"] = sorted(set(report["enqueued_sources"]))
    report["status"] = "enqueued"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair stable user content without creating Feed snapshots")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--data-dir", default="data")
    inspect_parser.add_argument("--output", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--data-dir", default="data")
    apply_parser.add_argument("--backup-dir", default="data/backups")
    apply_parser.add_argument("--cache-legacy-media", action="store_true")
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--data-dir", default="data")
    reconcile_parser.add_argument("--backup-dir", default="data/backups")
    enqueue_parser = subparsers.add_parser("enqueue")
    enqueue_parser.add_argument("--data-dir", default="data")
    enqueue_parser.add_argument("--free-only", action="store_true")
    args = parser.parse_args()
    if args.command == "inspect":
        report = inspect_content(data_dir=args.data_dir, output=args.output)
    elif args.command == "apply":
        report = apply_content_repair(data_dir=args.data_dir, backup_dir=args.backup_dir, cache_legacy_media=args.cache_legacy_media)
    elif args.command == "reconcile":
        report = reconcile_content(
            data_dir=args.data_dir, backup_dir=args.backup_dir
        )
    else:
        report = enqueue_content_repair(data_dir=args.data_dir, free_only=args.free_only)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
