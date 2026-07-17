"""Bounded hourly retention for service-owned SQLite data."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..storage.service_store import ServiceStore


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
        self.feed_retention_days = int(
            feed_retention_days
            if feed_retention_days is not None
            else _env_int("HORIZON_FEED_SNAPSHOT_RETENTION_DAYS", 90)
        )
        self.max_feed_snapshots_per_user = int(
            max_feed_snapshots_per_user
            if max_feed_snapshots_per_user is not None
            else _env_int("HORIZON_MAX_FEED_SNAPSHOTS_PER_USER", 100)
        )
        self.source_retention_days = int(
            source_retention_days
            if source_retention_days is not None
            else _env_int("HORIZON_SOURCE_CONTENT_RETENTION_DAYS", 7)
        )
        self.analysis_retention_days = int(
            analysis_retention_days
            if analysis_retention_days is not None
            else _env_int("HORIZON_ANALYSIS_CACHE_RETENTION_DAYS", 30)
        )
        self.usage_retention_days = int(
            usage_retention_days
            if usage_retention_days is not None
            else _env_int("HORIZON_USAGE_RETENTION_DAYS", 90)
        )
        self.job_retention_days = int(
            job_retention_days
            if job_retention_days is not None
            else _env_int("HORIZON_JOB_RETENTION_DAYS", 14)
        )

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
                return {"ran": False, "deleted": {}}

            deleted = self._prune_locked(current)
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
            return {"ran": True, "deleted": deleted}
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def _prune_locked(self, now: datetime) -> dict[str, int]:
        conn = self.store.connect()
        feed_cutoff = now - timedelta(days=max(self.feed_retention_days, 1))
        source_cutoff = now - timedelta(days=max(self.source_retention_days, 1))

        feed_delete_ids: list[str] = []
        feed_rows = conn.execute(
            """
            SELECT id, user_id, generated_at
            FROM user_feed_snapshots
            ORDER BY user_id, generated_at DESC, created_at DESC, id DESC
            """
        ).fetchall()
        feed_positions: dict[str, int] = {}
        for row in feed_rows:
            user_id = str(row["user_id"])
            position = feed_positions.get(user_id, 0)
            feed_positions[user_id] = position + 1
            generated_at = _parse_time(row["generated_at"])
            if position == 0:
                continue
            if position >= max(self.max_feed_snapshots_per_user, 1) or (
                generated_at is not None and generated_at < feed_cutoff
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
            SELECT id, acquisition_key, generated_at
            FROM source_content_snapshots
            ORDER BY acquisition_key, generated_at DESC, created_at DESC, id DESC
            """
        ).fetchall()
        seen_keys: set[str] = set()
        for row in source_rows:
            acquisition_key = str(row["acquisition_key"])
            if acquisition_key not in seen_keys:
                seen_keys.add(acquisition_key)
                continue
            generated_at = _parse_time(row["generated_at"])
            if generated_at is not None and generated_at < source_cutoff:
                source_delete_ids.append(str(row["id"]))
        if source_delete_ids:
            conn.executemany(
                "DELETE FROM source_content_snapshots WHERE id = ?",
                ((snapshot_id,) for snapshot_id in source_delete_ids),
            )

        content_rows = conn.execute(
            """
            SELECT content.id, content.workspace_id, content.user_id, content.article_id
            FROM user_content_items AS content
            WHERE content.last_seen_at < ?
              AND NOT EXISTS (
                SELECT 1 FROM user_item_state AS state
                WHERE state.workspace_id = content.workspace_id
                  AND state.user_id = content.user_id
                  AND state.article_id = content.article_id
                  AND (state.is_saved = 1 OR state.is_later = 1)
              )
              AND NOT EXISTS (
                SELECT 1 FROM user_feed_items AS feed_item
                WHERE feed_item.workspace_id = content.workspace_id
                  AND feed_item.user_id = content.user_id
                  AND feed_item.article_id = content.article_id
              )
            """,
            (feed_cutoff.isoformat(),),
        ).fetchall()
        media_deleted = 0
        media_root = (Path(self.store.data_dir) / "media").resolve()
        for content in content_rows:
            media_rows = conn.execute(
                """
                SELECT id, local_path FROM media_assets
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                  AND asset_kind = 'content_image'
                """,
                (
                    content["workspace_id"],
                    content["user_id"],
                    content["article_id"],
                ),
            ).fetchall()
            conn.execute(
                """
                DELETE FROM media_assets
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                  AND asset_kind = 'content_image'
                """,
                (
                    content["workspace_id"],
                    content["user_id"],
                    content["article_id"],
                ),
            )
            media_deleted += len(media_rows)
            for media in media_rows:
                path = (Path(self.store.data_dir) / str(media["local_path"])).resolve()
                if path.is_relative_to(media_root):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
            conn.execute("DELETE FROM user_content_items WHERE id = ?", (content["id"],))
            conn.execute(
                """
                DELETE FROM user_item_state
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                  AND is_saved = 0 AND is_later = 0
                """,
                (
                    content["workspace_id"],
                    content["user_id"],
                    content["article_id"],
                ),
            )

        analysis = conn.execute(
            "DELETE FROM user_analysis_cache WHERE updated_at < ?",
            ((now - timedelta(days=max(self.analysis_retention_days, 1))).isoformat(),),
        ).rowcount
        usage = conn.execute(
            "DELETE FROM usage_events WHERE created_at < ?",
            ((now - timedelta(days=max(self.usage_retention_days, 1))).isoformat(),),
        ).rowcount
        jobs = conn.execute(
            """
            DELETE FROM fetch_jobs
            WHERE status IN ('succeeded', 'failed', 'partial', 'cancelled')
              AND COALESCE(finished_at, updated_at, created_at) < ?
            """,
            ((now - timedelta(days=max(self.job_retention_days, 1))).isoformat(),),
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
        return {
            "feed_snapshots": len(feed_delete_ids),
            "source_snapshots": len(source_delete_ids),
            "content_items": len(content_rows),
            "media_assets": media_deleted,
            "analysis_cache": max(int(analysis), 0),
            "usage_events": max(int(usage), 0),
            "jobs": max(int(jobs), 0),
            "sessions": max(int(sessions), 0),
            "agent_change_proposals": proposal_cleanup["deleted"],
        }
