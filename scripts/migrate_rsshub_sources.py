#!/usr/bin/env python3
"""Move exact Bilibili RSSHub feed URLs to controlled workspace routes.

Dry-run is the default. Applying requires the Worker to be stopped, creates a
SQLite/config backup, preserves source/subscription/schedule identifiers, and
sets the environment-specific RSSHub Base URL in ``data/config.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.migrate_user_feed_v2 import _active_workers
from src.rsshub import normalize_rsshub_base_url
from src.services.source_type_registry import (
    source_key,
    validate_source_config,
)


_BILIBILI_USER_VIDEO_PATH = re.compile(
    r"^/bilibili/user/video/([1-9][0-9]{0,18})(?:/1)?/?$"
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_uid(config: Any) -> str | None:
    if not isinstance(config, dict) or config.get("provider") == "rsshub":
        return None
    raw_url = config.get("url")
    if not isinstance(raw_url, str):
        return None
    try:
        parsed = urlsplit(raw_url.strip())
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = _BILIBILI_USER_VIDEO_PATH.fullmatch(parsed.path)
    return match.group(1) if match is not None else None


def _managed_config(config: dict[str, Any], uid: str) -> dict[str, Any]:
    retained = {
        key: config[key]
        for key in (
            "name",
            "keep_latest_item",
            "enabled",
            "category",
            "channel",
            "topics",
            "tags",
            "personal_tags",
            "analysis_mode",
        )
        if key in config
    }
    return validate_source_config(
        "rss",
        {
            **retained,
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": uid},
        },
    )


def _load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json must contain an object")
    return data


def _database_candidates(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'source_catalog'
            """
        ).fetchone()
        if not exists:
            return []
        rows = connection.execute(
            """
            SELECT id, workspace_id, display_name, config_json, source_key
            FROM source_catalog
            WHERE type = 'rss'
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            config = json.loads(str(row["config_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
        uid = _candidate_uid(config)
        if uid is None:
            continue
        managed = _managed_config(config, uid)
        result.append(
            {
                "id": str(row["id"]),
                "workspace_id": str(row["workspace_id"]),
                "display_name": str(row["display_name"]),
                "old_source_key": str(row["source_key"]),
                "new_source_key": source_key("rss", managed),
                "uid": uid,
                "config": managed,
            }
        )
    return result


def _config_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    sources = data.get("sources")
    rss_sources = sources.get("rss") if isinstance(sources, dict) else None
    if not isinstance(rss_sources, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(rss_sources):
        uid = _candidate_uid(item)
        if uid is None:
            continue
        result.append(
            {
                "index": index,
                "uid": uid,
                "config": _managed_config(item, uid),
            }
        )
    return result


def _backup_database(source_path: Path, destination: Path) -> None:
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    os.chmod(destination, 0o600)


def migrate_rsshub_sources(
    *,
    data_dir: Path | str,
    base_url: str,
    apply: bool,
    backup_root: Path | str | None = None,
) -> dict[str, Any]:
    data_path = Path(data_dir)
    config_path = data_path / "config.json"
    db_path = data_path / "service.db"
    if not config_path.exists():
        raise FileNotFoundError(f"configuration file not found: {config_path}")

    normalized_base_url = normalize_rsshub_base_url(base_url)
    config_data = _load_config(config_path)
    database_candidates = _database_candidates(db_path)
    config_candidates = _config_candidates(config_data)
    result: dict[str, Any] = {
        "applied": False,
        "rsshub_base_url": normalized_base_url,
        "database_source_count": len(database_candidates),
        "config_source_count": len(config_candidates),
        "database_sources": [
            {
                "id": item["id"],
                "display_name": item["display_name"],
                "uid": item["uid"],
                "new_source_key": item["new_source_key"],
            }
            for item in database_candidates
        ],
        "config_sources": [
            {"index": item["index"], "uid": item["uid"]}
            for item in config_candidates
        ],
        "backup_dir": None,
    }
    if not apply:
        return result

    active_workers = _active_workers(db_path)
    if active_workers:
        raise RuntimeError(
            "stop all horizon-worker processes before applying RSSHub migration"
        )

    backup_dir = Path(
        backup_root
        or data_path / "backups" / f"rsshub-{_stamp()}"
    )
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, backup_dir / "config.json")
    os.chmod(backup_dir / "config.json", 0o600)
    if db_path.exists():
        _backup_database(db_path, backup_dir / "service.db")

    rss_sources = config_data.setdefault("sources", {}).setdefault("rss", [])
    for item in config_candidates:
        rss_sources[item["index"]] = item["config"]
    config_data["rsshub"] = {"base_url": normalized_base_url}

    if database_candidates:
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for item in database_candidates:
                conflict = connection.execute(
                    """
                    SELECT id FROM source_catalog
                    WHERE workspace_id = ? AND source_key = ? AND id <> ?
                    """,
                    (
                        item["workspace_id"],
                        item["new_source_key"],
                        item["id"],
                    ),
                ).fetchone()
                if conflict is not None:
                    raise RuntimeError(
                        "managed RSSHub source key conflicts with an existing source"
                    )
                connection.execute(
                    """
                    UPDATE source_catalog
                    SET config_json = ?, source_key = ?,
                        enforce_public_network = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(
                            item["config"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        item["new_source_key"],
                        _now_iso(),
                        item["id"],
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    temporary_path = config_path.with_name(
        f".{config_path.name}.rsshub-{_stamp()}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, config_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    result["applied"] = True
    result["backup_dir"] = str(backup_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--backup-root")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply after stopping the Worker; otherwise perform a dry run.",
    )
    args = parser.parse_args()
    result = migrate_rsshub_sources(
        data_dir=args.data_dir,
        base_url=args.base_url,
        apply=args.apply,
        backup_root=args.backup_root,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
