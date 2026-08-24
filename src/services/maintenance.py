"""Bounded hourly retention for service-owned SQLite data."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..storage.service_store import ServiceStore
from .media_cache import PostCommitMediaCleanup
from .system_settings import resolve_system_setting


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except (TypeError, ValueError):
        return max(default, minimum)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


class MaintenanceService:
    """Run retention at most once per interval across Worker processes."""

    STATE_KEY = "service_retention_v1"

    def __init__(
        self,
        store: ServiceStore,
        *,
        interval_seconds: int | None = None,
        feed_retention_days: int | None = None,
        max_feed_snapshots_per_user: int | None = None,
        source_retention_days: int | None = None,
        analysis_retention_days: int | None = None,
        usage_retention_days: int | None = None,
        job_retention_days: int | None = None,
    ) -> None:
        self.store = store
        self.interval_seconds = int(
            interval_seconds
            if interval_seconds is not None
            else _env_int("HORIZON_MAINTENANCE_INTERVAL_SECONDS", 3600)
        )
        self.feed_retention_days = feed_retention_days
        self.max_feed_snapshots_per_user = max_feed_snapshots_per_user
        self.source_retention_days = source_retention_days
        self.analysis_retention_days = analysis_retention_days
        self.usage_retention_days = usage_retention_days
        self.job_retention_days = job_retention_days

    def _limit(self, workspace_id: str, attribute: str, key: str) -> int:
        explicit = getattr(self, attribute)
        return int(explicit if explicit is not None else resolve_system_setting(
            self.store, workspace_id, key
        ))

    def run_if_due(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        current = _utc(now)
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError("maintenance requires no active transaction")
        media_cleanup = PostCommitMediaCleanup()
        result: dict[str, Any]
        try:
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                "SELECT last_run_at FROM maintenance_state WHERE key = ?",
                (self.STATE_KEY,),
            ).fetchone()
            last_run = _parse_time(state["last_run_at"]) if state else None
            if (
                not force
                and last_run is not None
                and current < last_run + timedelta(seconds=max(self.interval_seconds, 1))
            ):
                conn.commit()
                result = {"ran": False, "deleted": {}}
            else:
                deleted = self._prune_locked(
                    current,
                    media_cleanup=media_cleanup,
                )
                now_iso = current.isoformat()
                conn.execute(
                    """
                    INSERT INTO maintenance_state (key, last_run_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        last_run_at = excluded.last_run_at,
                        updated_at = excluded.updated_at
                    """,
                    (self.STATE_KEY, now_iso, now_iso),
                )
                conn.commit()
                result = {"ran": True, "deleted": deleted}
        except BaseException:
            try:
                if conn.in_transaction:
                    conn.rollback()
            finally:
                media_cleanup.discard()
            raise
        media_cleanup.run()
        return result

    def _prune_locked(
        self,
        now: datetime,
        *,
        media_cleanup: PostCommitMediaCleanup,
    ) -> dict[str, int]:
        conn = self.store.connect()
        workspace_ids = [str(row[0]) for row in conn.execute("SELECT id FROM workspaces")]
        limits: dict[tuple[str, str], int] = {}

        def limit(workspace_id: str, attribute: str, key: str) -> int:
            cache_key = (workspace_id, key)
            if cache_key not in limits:
                limits[cache_key] = self._limit(workspace_id, attribute, key)
            return limits[cache_key]

        feed_delete_ids: list[str] = []
        feed_rows = conn.execute(
            """
            SELECT id, workspace_id, user_id, generated_at
            FROM user_feed_snapshots
            ORDER BY user_id, generated_at DESC, created_at DESC, id DESC
            """
        ).fetchall()
        feed_positions: dict[str, int] = {}
        for row in feed_rows:
            user_id = str(row["user_id"])
            workspace_id = str(row["workspace_id"])
            position = feed_positions.get(user_id, 0)
            feed_positions[user_id] = position + 1
            generated_at = _parse_time(row["generated_at"])
            if position == 0:
                continue
            if position >= max(limit(workspace_id, "max_feed_snapshots_per_user", "retention.max_feed_snapshots_per_user"), 1) or (
                generated_at is not None and generated_at < now - timedelta(days=max(limit(workspace_id, "feed_retention_days", "retention.feed_snapshot_days"), 1))
            ):
                feed_delete_ids.append(str(row["id"]))
        if feed_delete_ids:
            conn.executemany(
                "DELETE FROM user_feed_snapshots WHERE id = ?",
                ((snapshot_id,) for snapshot_id in feed_delete_ids),
            )

        source_delete_ids: list[str] = []
        source_rows = conn.execute(
            """
            SELECT id, acquisition_key, workspace_id, generated_at
            FROM source_content_snapshots
            ORDER BY acquisition_key, generated_at DESC, created_at DESC, id DESC
            """
        ).fetchall()
        seen_keys: set[str] = set()
        for row in source_rows:
            workspace_id = str(row["workspace_id"])
            acquisition_key = f"{workspace_id}:{row['acquisition_key']}"
            if acquisition_key not in seen_keys:
                seen_keys.add(acquisition_key)
                continue
            generated_at = _parse_time(row["generated_at"])
            if generated_at is not None and generated_at < now - timedelta(days=max(limit(workspace_id, "source_retention_days", "retention.source_content_days"), 1)):
                source_delete_ids.append(str(row["id"]))
        if source_delete_ids:
            conn.executemany(
                "DELETE FROM source_content_snapshots WHERE id = ?",
                ((snapshot_id,) for snapshot_id in source_delete_ids),
            )

        orphan_media_rows = conn.execute(
            """
            SELECT media.id, media.local_path
            FROM media_assets AS media
            WHERE media.asset_kind = 'content_image'
              AND media.user_id IS NOT NULL
              AND media.article_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1
                FROM user_content_items AS content
                WHERE content.workspace_id = media.workspace_id
                  AND content.user_id = media.user_id
                  AND content.article_id = media.article_id
              )
            """
        ).fetchall()
        media_root = (Path(self.store.data_dir) / "media").resolve()
        for media in orphan_media_rows:
            path = (Path(self.store.data_dir) / str(media["local_path"])).resolve()
            if path.is_relative_to(media_root):
                media_cleanup.add(path)
        if orphan_media_rows:
            conn.executemany(
                "DELETE FROM media_assets WHERE id = ?",
                ((str(media["id"]),) for media in orphan_media_rows),
            )

        analysis = usage = jobs = 0
        for workspace_id in workspace_ids:
            analysis += conn.execute(
                "DELETE FROM user_analysis_cache WHERE workspace_id=? AND updated_at < ?",
                (workspace_id, (now - timedelta(days=max(limit(workspace_id, "analysis_retention_days", "retention.analysis_cache_days"), 1))).isoformat()),
            ).rowcount
            usage += conn.execute(
                "DELETE FROM usage_events WHERE workspace_id=? AND created_at < ?",
                (workspace_id, (now - timedelta(days=max(limit(workspace_id, "usage_retention_days", "retention.usage_days"), 1))).isoformat()),
            ).rowcount
            jobs += conn.execute(
                """DELETE FROM fetch_jobs WHERE workspace_id=?
                   AND status IN ('succeeded', 'failed', 'partial', 'cancelled')
                   AND ((expires_at IS NOT NULL AND expires_at < ?)
                     OR (expires_at IS NULL AND COALESCE(finished_at, updated_at, created_at) < ?))""",
                (workspace_id, now.isoformat(), (now - timedelta(days=max(limit(workspace_id, "job_retention_days", "jobs.retention_days"), 1))).isoformat()),
            ).rowcount
        sessions = conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?",
            (now.isoformat(),),
        ).rowcount
        proposal_cleanup = self.store.cleanup_agent_change_proposals(
            now=now.isoformat(),
            maintenance=True,
            commit=False,
        )
        resolution_cleanup = self.store.cleanup_agent_source_resolutions(
            now=now.isoformat(),
            commit=False,
        )
        return {
            "feed_snapshots": len(feed_delete_ids),
            "source_snapshots": len(source_delete_ids),
            "content_items": 0,
            "media_assets": len(orphan_media_rows),
            "analysis_cache": max(int(analysis), 0),
            "usage_events": max(int(usage), 0),
            "jobs": max(int(jobs), 0),
            "sessions": max(int(sessions), 0),
            "agent_change_proposals": proposal_cleanup["deleted"],
            "agent_source_resolutions": resolution_cleanup["deleted"],
        }
