#!/usr/bin/env python3
"""Dry-run-first, free-only source avatar backfill."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.services.media_cache import MediaCacheService
from src.services.source_avatar import SourceAvatarService
from src.storage.service_store import ServiceStore


FREE_SOURCE_TYPES = frozenset(
    {
        "rss",
        "github_release",
        "github_user",
        "reddit_subreddit",
        "reddit_user",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve source avatars without running Feed, AI, notifications, "
            "Source Health, scheduler, or paid Actors."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--workspace-id")
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--free-only",
        action="store_true",
        help="Required with --apply; paid providers are always skipped.",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Include rows that already have a ready avatar.",
    )
    return parser


def _safe_record(source: dict[str, Any], status: str) -> dict[str, str]:
    return {
        "source_id": str(source["id"]),
        "source_type": str(source.get("type") or ""),
        "display_name": str(source.get("display_name") or ""),
        "status": status,
    }


def main() -> int:
    args = _parser().parse_args()
    if args.apply and not args.free_only:
        raise SystemExit("--apply requires --free-only")
    data_dir = args.data_dir.resolve()
    database = data_dir / "service.db"
    if not database.is_file():
        raise SystemExit(f"service database not found: {database}")

    store = ServiceStore(data_dir)
    try:
        workspace = store.get_default_workspace()
        if workspace is None:
            raise SystemExit("workspace not found")
        if args.workspace_id and str(args.workspace_id) != str(workspace["id"]):
            raise SystemExit("workspace not found")
        sources = store.list_workspace_sources(
            workspace_id=str(workspace["id"]),
            include_disabled=False,
        )
        requested = {str(value) for value in args.source_id if value}
        if requested:
            sources = [
                source for source in sources if str(source["id"]) in requested
            ]
            missing = requested - {str(source["id"]) for source in sources}
            if missing:
                raise SystemExit(
                    "source not found or disabled: " + ", ".join(sorted(missing))
                )

        media_cache = MediaCacheService(store, data_dir=data_dir)
        avatar_service = SourceAvatarService(
            store,
            data_dir=str(data_dir),
            media_cache=media_cache,
        )
        records: list[dict[str, str]] = []
        for source in sources:
            source_id = str(source["id"])
            source_type = str(source.get("type") or "")
            current = media_cache.avatar_for_source(
                workspace_id=str(workspace["id"]),
                source_id=source_id,
            )
            if current is not None and not args.include_existing:
                records.append(_safe_record(source, "existing"))
                continue
            if source_type not in FREE_SOURCE_TYPES:
                records.append(
                    _safe_record(
                        source,
                        "paid_source_skipped"
                        if source_type == "apify_social"
                        else "platform_fallback",
                    )
                )
                continue
            if not args.apply:
                records.append(_safe_record(source, "eligible"))
                continue
            refresh = avatar_service.refresh_sources(
                workspace_id=str(workspace["id"]),
                source_ids=[source_id],
                resolve_missing_source_ids=[source_id],
            )[0]
            records.append(_safe_record(source, refresh.status))

        verified = 0
        media_root = (data_dir / "media").resolve()
        for source in sources:
            avatar = media_cache.avatar_for_source(
                workspace_id=str(workspace["id"]),
                source_id=str(source["id"]),
            )
            if avatar is None:
                continue
            path = (data_dir / str(avatar["local_path"])).resolve()
            if media_root in path.parents and path.is_file():
                verified += 1
        counts = Counter(record["status"] for record in records)
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": "apply" if args.apply else "dry_run",
                    "workspace_id": str(workspace["id"]),
                    "source_count": len(records),
                    "verified_ready_files": verified,
                    "status_counts": dict(sorted(counts.items())),
                    "sources": records,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
