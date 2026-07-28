"""Preview-first storage cleanup, cold archive, restore, and deletion controls."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from ..storage.service_store import ServiceStore
from .content_timeline import build_search_text
from .maintenance import MaintenanceService
from .media_cache import PostCommitMediaCleanup
from .user_content_store import UserContentStore


StorageOperation = Literal["cleanup", "archive", "restore", "delete_archive"]
_PLAN_TTL = timedelta(minutes=10)
_ARCHIVE_AFTER = timedelta(days=90)
_SQLITE_ID_BATCH = 400
_MEDIA_COLUMNS = (
    "id",
    "workspace_id",
    "user_id",
    "source_id",
    "subscription_id",
    "article_id",
    "asset_kind",
    "remote_url",
    "local_path",
    "mime_type",
    "byte_size",
    "checksum",
    "width",
    "height",
    "alt",
    "visibility_scope",
    "status",
    "created_at",
    "updated_at",
)


class StorageGovernanceError(RuntimeError):
    """Stable service error for preview/apply storage operations."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise StorageGovernanceError(
            "storage_plan_invalid",
            "storage plan contains an invalid timestamp",
            status_code=409,
        ) from exc
    return _utc(parsed)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(str(value))
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return fallback


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _batches(values: list[str], size: int = _SQLITE_ID_BATCH) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    root = path.resolve()
    for candidate in root.rglob("*"):
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(root):
                total += resolved.stat().st_size
        except (FileNotFoundError, OSError):
            continue
    return total


def _cold_metadata_item(value: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(value)
    item["content"] = ""
    item["image_url"] = ""
    item["media_urls"] = []
    presentation = item.get("presentation")
    if isinstance(presentation, dict):
        content = presentation.get("content")
        if isinstance(content, dict):
            content["body_text"] = ""
            content["body_truncated"] = False
            content["body_completeness"] = "excerpt_only"
        media = presentation.get("media")
        if isinstance(media, dict):
            try:
                total = max(
                    int(media.get("total_image_count") or media.get("count") or 0),
                    0,
                )
            except (TypeError, ValueError):
                total = 0
            media["images"] = []
            media["count"] = 0
            media["total_image_count"] = total
            media["truncated"] = total > 0
    return item


class StorageGovernanceService:
    """Workspace-scoped, auditable two-step storage governance."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store
        self.data_dir = Path(store.data_dir)
        self.archive_root = (self.data_dir / "archives").resolve()
        self.media_root = (self.data_dir / "media").resolve()

    def summary(self, *, workspace_id: str) -> dict[str, Any]:
        conn = self.store.connect()
        content = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN archived_at IS NULL THEN 1 ELSE 0 END), 0) AS online,
                COALESCE(SUM(CASE WHEN archived_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS archived
            FROM user_content_items
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        counts = {
            "content_total": int(content["total"] or 0),
            "content_online": int(content["online"] or 0),
            "content_archived": int(content["archived"] or 0),
            "feed_snapshots": int(
                conn.execute(
                    "SELECT COUNT(*) FROM user_feed_snapshots WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()[0]
            ),
            "source_snapshots": int(
                conn.execute(
                    "SELECT COUNT(*) FROM source_content_snapshots WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()[0]
            ),
            "media_assets": int(
                conn.execute(
                    "SELECT COUNT(*) FROM media_assets WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()[0]
            ),
            "archive_batches": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM storage_archive_batches
                    WHERE workspace_id = ? AND status != 'deleted'
                    """,
                    (workspace_id,),
                ).fetchone()[0]
            ),
        }
        migrations = {
            int(row["version"]): str(row["applied_at"])
            for row in conn.execute(
                "SELECT version, applied_at FROM schema_migrations WHERE version IN (3, 11)"
            ).fetchall()
        }
        maintenance = conn.execute(
            "SELECT last_run_at FROM maintenance_state WHERE key = ?",
            (MaintenanceService.STATE_KEY,),
        ).fetchone()
        return {
            "schema_version": 1,
            "policy": {
                "feed_snapshot_days": 30,
                "feed_snapshot_per_user": 20,
                "source_snapshot_days": 7,
                "completed_job_days": 14,
                "analysis_cache_days": 30,
                "usage_event_days": 90,
                "archive_after_days": 90,
                "automatic_permanent_delete": False,
            },
            "bytes": {
                "database": self.store.db_path.stat().st_size if self.store.db_path.exists() else 0,
                "media": _directory_size(self.media_root),
                "archives": _directory_size(self.archive_root),
            },
            "counts": counts,
            "readiness": {
                "feed_storage_v3": 3 in migrations,
                "content_timeline_v11": 11 in migrations,
                "ready": 3 in migrations and 11 in migrations,
            },
            "last_cleanup_at": str(maintenance["last_run_at"]) if maintenance else None,
        }

    def list_archives(self, *, workspace_id: str) -> dict[str, Any]:
        rows = self.store.connect().execute(
            """
            SELECT id, status, cutoff_at, checksum, item_count, media_count,
                   byte_size, created_at, committed_at, restored_at, updated_at
            FROM storage_archive_batches
            WHERE workspace_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (workspace_id,),
        ).fetchall()
        return {
            "schema_version": 1,
            "archives": [dict(row) for row in rows],
        }

    def create_plan(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        actor_role: str,
        operation: StorageOperation,
        payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if operation not in {"cleanup", "archive", "restore", "delete_archive"}:
            raise StorageGovernanceError(
                "storage_operation_invalid",
                "operation must be cleanup, archive, restore, or delete_archive",
            )
        if operation == "delete_archive" and actor_role != "owner":
            raise StorageGovernanceError(
                "forbidden",
                "owner role required for permanent archive deletion",
                status_code=403,
            )
        if operation in {"cleanup", "archive"}:
            self._require_migrations()
        current = _utc(now)
        request_payload = dict(payload or {})
        if operation in {"cleanup", "archive"} and request_payload:
            raise StorageGovernanceError(
                "storage_plan_invalid",
                f"{operation} does not accept payload fields",
            )
        if operation in {"restore", "delete_archive"}:
            if set(request_payload) != {"batch_id"} or not isinstance(
                request_payload.get("batch_id"),
                str,
            ):
                raise StorageGovernanceError(
                    "storage_plan_invalid",
                    f"{operation} requires only a string batch_id",
                )
        parameters, candidates, preview = self._preview(
            workspace_id=workspace_id,
            operation=operation,
            payload=request_payload,
            now=current,
        )
        fingerprint = _fingerprint(candidates)
        plan_id = f"stp_{uuid.uuid4().hex}"
        created_at = current.isoformat()
        expires_at = (current + _PLAN_TTL).isoformat()
        stored_payload = {
            "request": request_payload,
            "parameters": parameters,
            "preview": preview,
        }
        self.store.connect().execute(
            """
            INSERT INTO storage_maintenance_plans (
                id, workspace_id, actor_user_id, operation, status,
                payload_json, result_json, fingerprint, expires_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'previewed', ?, '{}', ?, ?, ?, ?)
            """,
            (
                plan_id,
                workspace_id,
                actor_user_id,
                operation,
                _json(stored_payload),
                fingerprint,
                expires_at,
                created_at,
                created_at,
            ),
        )
        self.store.connect().commit()
        return self._plan(plan_id, workspace_id=workspace_id)

    def apply_plan(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        actor_role: str,
        plan_id: str,
        confirmation: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(plan_id, workspace_id=workspace_id)
        if plan["actor_user_id"] != actor_user_id:
            raise StorageGovernanceError(
                "storage_plan_not_found",
                "storage plan not found",
                status_code=404,
            )
        if plan["status"] == "applied":
            return plan
        if plan["status"] != "previewed":
            raise StorageGovernanceError(
                "storage_plan_unavailable",
                "storage plan can no longer be applied",
                status_code=409,
            )
        current = _utc(now)
        if current >= _parse_time(plan["expires_at"]):
            self.store.connect().execute(
                """
                UPDATE storage_maintenance_plans
                SET status = 'expired', updated_at = ?
                WHERE id = ? AND status = 'previewed'
                """,
                (current.isoformat(), plan_id),
            )
            self.store.connect().commit()
            raise StorageGovernanceError(
                "storage_plan_expired",
                "storage plan expired; create a new preview",
                status_code=409,
            )
        operation = str(plan["operation"])
        if operation == "delete_archive":
            if actor_role != "owner":
                raise StorageGovernanceError(
                    "forbidden",
                    "owner role required for permanent archive deletion",
                    status_code=403,
                )
            batch_id = str(plan["payload"]["parameters"]["batch_id"])
            if confirmation != f"永久删除归档 {batch_id}":
                raise StorageGovernanceError(
                    "storage_confirmation_required",
                    f"confirmation must equal: 永久删除归档 {batch_id}",
                    status_code=409,
                )
        parameters = dict(plan["payload"].get("parameters") or {})
        _parameters, candidates, _preview = self._preview(
            workspace_id=workspace_id,
            operation=operation,  # type: ignore[arg-type]
            payload=parameters,
            now=_parse_time(parameters.get("planned_at") or plan["created_at"]),
            normalized=True,
        )
        if _fingerprint(candidates) != plan["fingerprint"]:
            raise StorageGovernanceError(
                "storage_plan_changed",
                "storage candidates changed; create a new preview",
                status_code=409,
            )
        if operation == "cleanup":
            result = self._apply_cleanup(
                workspace_id=workspace_id,
                candidates=candidates,
                planned_at=_parse_time(parameters["planned_at"]),
                applied_at=current,
            )
        elif operation == "archive":
            result = self._apply_archive(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                cutoff_at=str(parameters["cutoff_at"]),
                expected_ids=[str(value) for value in candidates["content_ids"]],
                applied_at=current,
            )
        elif operation == "restore":
            result = self._apply_restore(
                workspace_id=workspace_id,
                batch_id=str(parameters["batch_id"]),
                applied_at=current,
            )
        else:
            result = self._apply_archive_delete(
                workspace_id=workspace_id,
                batch_id=str(parameters["batch_id"]),
                applied_at=current,
            )
        self.store.connect().execute(
            """
            UPDATE storage_maintenance_plans
            SET status = 'applied', result_json = ?, applied_at = ?, updated_at = ?
            WHERE id = ? AND status = 'previewed'
            """,
            (_json(result), current.isoformat(), current.isoformat(), plan_id),
        )
        self.store.connect().commit()
        return self._plan(plan_id, workspace_id=workspace_id)

    def _require_migrations(self) -> None:
        versions = {
            int(row["version"])
            for row in self.store.connect().execute(
                "SELECT version FROM schema_migrations WHERE version IN (3, 11)"
            ).fetchall()
        }
        if 3 not in versions or 11 not in versions:
            raise StorageGovernanceError(
                "storage_migration_required",
                "Feed Storage v3 and content timeline v11 must be applied first",
                status_code=409,
            )

    def _preview(
        self,
        *,
        workspace_id: str,
        operation: StorageOperation,
        payload: dict[str, Any],
        now: datetime,
        normalized: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if operation == "cleanup":
            planned_at = _parse_time(payload["planned_at"]) if normalized else now
            parameters = {"planned_at": planned_at.isoformat()}
            candidates = self._cleanup_candidates(workspace_id, planned_at)
            preview = {
                "counts": {key: len(value) for key, value in candidates.items()},
                "permanent_content_deletes": 0,
            }
            return parameters, candidates, preview
        if operation == "archive":
            if normalized:
                planned_at = _parse_time(payload["planned_at"])
                cutoff_at = _parse_time(payload["cutoff_at"])
            else:
                planned_at = now
                cutoff_at = now - _ARCHIVE_AFTER
            parameters = {
                "planned_at": planned_at.isoformat(),
                "cutoff_at": cutoff_at.isoformat(),
            }
            content_ids = self._archive_candidate_ids(workspace_id, cutoff_at.isoformat())
            media_count = self._archive_media_count(content_ids)
            candidates = {"content_ids": content_ids}
            preview = {
                "item_count": len(content_ids),
                "media_count": media_count,
                "cutoff_at": cutoff_at.isoformat(),
                "protected_items_excluded": True,
            }
            return parameters, candidates, preview
        batch_id = str(payload.get("batch_id") or "").strip()
        if not batch_id:
            raise StorageGovernanceError(
                "storage_archive_required",
                "batch_id is required",
            )
        row = self._archive_row(workspace_id, batch_id)
        parameters = {
            "planned_at": (
                str(payload["planned_at"])
                if normalized and payload.get("planned_at")
                else now.isoformat()
            ),
            "batch_id": batch_id,
        }
        if operation == "restore":
            if row["status"] == "deleted":
                raise StorageGovernanceError(
                    "storage_archive_deleted",
                    "archive was permanently deleted",
                    status_code=409,
                )
            candidates = {
                "batch_id": batch_id,
                "checksum": str(row["checksum"]),
                "status": str(row["status"]),
            }
            preview = {
                "batch_id": batch_id,
                "item_count": int(row["item_count"]),
                "media_count": int(row["media_count"]),
                "already_restored": row["status"] == "restored",
            }
        else:
            if row["status"] != "restored":
                raise StorageGovernanceError(
                    "storage_archive_not_restored",
                    "restore the archive before permanent deletion",
                    status_code=409,
                )
            active_refs = int(
                self.store.connect().execute(
                    """
                    SELECT COUNT(*) FROM user_content_items
                    WHERE workspace_id = ? AND archive_batch_id = ?
                      AND archived_at IS NOT NULL
                    """,
                    (workspace_id, batch_id),
                ).fetchone()[0]
            )
            if active_refs:
                raise StorageGovernanceError(
                    "storage_archive_in_use",
                    "archive still owns cold content and cannot be deleted",
                    status_code=409,
                )
            candidates = {
                "batch_id": batch_id,
                "checksum": str(row["checksum"]),
                "status": str(row["status"]),
                "active_refs": active_refs,
            }
            preview = {
                "batch_id": batch_id,
                "byte_size": int(row["byte_size"]),
                "permanent": True,
                "required_confirmation": f"永久删除归档 {batch_id}",
            }
        return parameters, candidates, preview

    def _cleanup_candidates(
        self,
        workspace_id: str,
        now: datetime,
    ) -> dict[str, list[str]]:
        conn = self.store.connect()
        policy = MaintenanceService(self.store)
        feed_cutoff = now - timedelta(days=policy.feed_retention_days)
        source_cutoff = now - timedelta(days=policy.source_retention_days)
        feed_rows = conn.execute(
            """
            SELECT id, user_id, generated_at
            FROM user_feed_snapshots
            WHERE workspace_id = ?
            ORDER BY user_id, generated_at DESC, created_at DESC, id DESC
            """,
            (workspace_id,),
        ).fetchall()
        feed_ids: list[str] = []
        positions: dict[str, int] = {}
        for row in feed_rows:
            user_id = str(row["user_id"])
            position = positions.get(user_id, 0)
            positions[user_id] = position + 1
            try:
                generated_at = _parse_time(row["generated_at"])
            except StorageGovernanceError:
                generated_at = now
            if position and (
                position >= policy.max_feed_snapshots_per_user
                or generated_at < feed_cutoff
            ):
                feed_ids.append(str(row["id"]))
        source_rows = conn.execute(
            """
            SELECT id, acquisition_key, generated_at
            FROM source_content_snapshots
            WHERE workspace_id = ?
            ORDER BY acquisition_key, generated_at DESC, created_at DESC, id DESC
            """,
            (workspace_id,),
        ).fetchall()
        source_ids: list[str] = []
        seen: set[str] = set()
        for row in source_rows:
            key = str(row["acquisition_key"])
            if key not in seen:
                seen.add(key)
                continue
            try:
                generated_at = _parse_time(row["generated_at"])
            except StorageGovernanceError:
                continue
            if generated_at < source_cutoff:
                source_ids.append(str(row["id"]))

        def rowids(sql: str, params: tuple[Any, ...]) -> list[str]:
            return [str(row[0]) for row in conn.execute(sql, params).fetchall()]

        analysis_cutoff = (now - timedelta(days=policy.analysis_retention_days)).isoformat()
        usage_cutoff = (now - timedelta(days=policy.usage_retention_days)).isoformat()
        job_cutoff = (now - timedelta(days=policy.job_retention_days)).isoformat()
        orphan_media = [
            str(row["id"])
            for row in conn.execute(
                """
                SELECT media.id
                FROM media_assets AS media
                WHERE media.workspace_id = ?
                  AND media.asset_kind = 'content_image'
                  AND media.user_id IS NOT NULL
                  AND media.article_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM user_content_items AS content
                    WHERE content.workspace_id = media.workspace_id
                      AND content.user_id = media.user_id
                      AND content.article_id = media.article_id
                  )
                """,
                (workspace_id,),
            ).fetchall()
        ]
        return {
            "feed_snapshots": feed_ids,
            "source_snapshots": source_ids,
            "analysis_cache": rowids(
                """
                SELECT rowid FROM user_analysis_cache
                WHERE workspace_id = ? AND updated_at < ?
                ORDER BY rowid
                """,
                (workspace_id, analysis_cutoff),
            ),
            "usage_events": rowids(
                """
                SELECT rowid FROM usage_events
                WHERE workspace_id = ? AND created_at < ?
                ORDER BY rowid
                """,
                (workspace_id, usage_cutoff),
            ),
            "jobs": rowids(
                """
                SELECT rowid FROM fetch_jobs
                WHERE workspace_id = ?
                  AND status IN ('succeeded', 'failed', 'partial', 'cancelled')
                  AND COALESCE(finished_at, updated_at, created_at) < ?
                ORDER BY rowid
                """,
                (workspace_id, job_cutoff),
            ),
            "sessions": rowids(
                """
                SELECT sessions.rowid
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE users.workspace_id = ? AND sessions.expires_at < ?
                ORDER BY sessions.rowid
                """,
                (workspace_id, now.isoformat()),
            ),
            "agent_change_proposals": [
                str(row["id"])
                for row in conn.execute(
                    """
                    SELECT id FROM agent_change_proposals
                    WHERE workspace_id = ?
                      AND status IN ('applied', 'expired')
                      AND updated_at < ?
                    ORDER BY id
                    """,
                    (workspace_id, job_cutoff),
                ).fetchall()
            ],
            "agent_source_resolutions": [
                str(row["id"])
                for row in conn.execute(
                    """
                    SELECT id FROM agent_source_resolutions
                    WHERE workspace_id = ? AND expires_at < ?
                    ORDER BY id
                    """,
                    (
                        workspace_id,
                        (
                            now - timedelta(hours=24)
                        ).isoformat(),
                    ),
                ).fetchall()
            ],
            "orphan_media": orphan_media,
        }

    def _apply_cleanup(
        self,
        *,
        workspace_id: str,
        candidates: dict[str, Any],
        planned_at: datetime,
        applied_at: datetime,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        media_cleanup = PostCommitMediaCleanup()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = self._cleanup_candidates(workspace_id, planned_at)
            if _fingerprint(current) != _fingerprint(candidates):
                raise StorageGovernanceError(
                    "storage_plan_changed",
                    "storage candidates changed; create a new preview",
                    status_code=409,
                )
            media_rows = []
            for batch in _batches(candidates["orphan_media"]):
                placeholders = ",".join("?" for _ in batch)
                media_rows.extend(
                    conn.execute(
                        f"""
                        SELECT id, local_path FROM media_assets
                        WHERE workspace_id = ? AND id IN ({placeholders})
                        """,
                        (workspace_id, *batch),
                    ).fetchall()
                )
            for row in media_rows:
                path = (self.data_dir / str(row["local_path"])).resolve()
                if path.is_relative_to(self.media_root):
                    media_cleanup.add(path)
            self._delete_ids("user_feed_snapshots", "id", candidates["feed_snapshots"])
            self._delete_ids("source_content_snapshots", "id", candidates["source_snapshots"])
            self._delete_ids("user_analysis_cache", "rowid", candidates["analysis_cache"])
            self._delete_ids("usage_events", "rowid", candidates["usage_events"])
            self._delete_ids("fetch_jobs", "rowid", candidates["jobs"])
            self._delete_ids("sessions", "rowid", candidates["sessions"])
            self._delete_ids(
                "agent_change_proposals",
                "id",
                candidates["agent_change_proposals"],
            )
            self._delete_ids(
                "agent_source_resolutions",
                "id",
                candidates["agent_source_resolutions"],
            )
            self._delete_ids("media_assets", "id", candidates["orphan_media"])
            conn.execute(
                """
                INSERT INTO maintenance_state (key, last_run_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    last_run_at = excluded.last_run_at,
                    updated_at = excluded.updated_at
                """,
                (
                    MaintenanceService.STATE_KEY,
                    applied_at.isoformat(),
                    applied_at.isoformat(),
                ),
            )
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            media_cleanup.discard()
            raise
        media_cleanup.run()
        return {
            "operation": "cleanup",
            "deleted": {key: len(value) for key, value in candidates.items()},
            "content_items": 0,
            "applied_at": applied_at.isoformat(),
        }

    def _delete_ids(self, table: str, column: str, values: list[str]) -> None:
        if not values:
            return
        if table not in {
            "user_feed_snapshots",
            "source_content_snapshots",
            "user_analysis_cache",
            "usage_events",
            "fetch_jobs",
            "sessions",
            "agent_change_proposals",
            "agent_source_resolutions",
            "media_assets",
        } or column not in {"id", "rowid"}:
            raise RuntimeError("unsafe storage cleanup target")
        self.store.connect().executemany(
            f"DELETE FROM {table} WHERE {column} = ?",
            ((value,) for value in values),
        )

    def _archive_candidate_ids(self, workspace_id: str, cutoff_at: str) -> list[str]:
        rows = self.store.connect().execute(
            """
            SELECT content.id
            FROM user_content_items AS content
            WHERE content.workspace_id = ?
              AND content.archived_at IS NULL
              AND content.effective_at != ''
              AND content.effective_at < ?
              AND NOT EXISTS (
                SELECT 1 FROM user_item_state AS state
                WHERE state.workspace_id = content.workspace_id
                  AND state.user_id = content.user_id
                  AND state.article_id = content.article_id
                  AND (state.is_saved = 1 OR state.is_later = 1)
              )
              AND NOT EXISTS (
                SELECT 1 FROM preferred_source_notification_deliveries AS delivery
                WHERE delivery.workspace_id = content.workspace_id
                  AND delivery.user_id = content.user_id
                  AND delivery.article_id = content.article_id
                  AND delivery.status IN ('pending', 'sending')
              )
            ORDER BY content.effective_at, content.id
            """,
            (workspace_id, cutoff_at),
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def _archive_media_count(self, content_ids: list[str]) -> int:
        total = 0
        for batch in _batches(content_ids):
            placeholders = ",".join("?" for _ in batch)
            total += int(
                self.store.connect().execute(
                    f"""
                    SELECT COUNT(*)
                    FROM media_assets AS media
                    JOIN user_content_items AS content
                      ON content.workspace_id = media.workspace_id
                     AND content.user_id = media.user_id
                     AND content.article_id = media.article_id
                    WHERE content.id IN ({placeholders})
                      AND media.asset_kind = 'content_image'
                    """,
                    tuple(batch),
                ).fetchone()[0]
            )
        return total

    def _content_rows(self, workspace_id: str, content_ids: list[str]) -> list[Any]:
        rows: list[Any] = []
        for batch in _batches(content_ids):
            placeholders = ",".join("?" for _ in batch)
            rows.extend(
                self.store.connect().execute(
                    f"""
                    SELECT * FROM user_content_items
                    WHERE workspace_id = ? AND id IN ({placeholders})
                    """,
                    (workspace_id, *batch),
                ).fetchall()
            )
        rows.sort(key=lambda row: (str(row["effective_at"]), str(row["id"])))
        return rows

    def _apply_archive(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        cutoff_at: str,
        expected_ids: list[str],
        applied_at: datetime,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        batch_id = f"sta_{uuid.uuid4().hex}"
        self.archive_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.archive_root, 0o700)
        archive_path = self.archive_root / f"{batch_id}.zip"
        temp_handle = tempfile.NamedTemporaryFile(
            prefix=f".{batch_id}-",
            suffix=".tmp",
            dir=self.archive_root,
            delete=False,
        )
        temp_path = Path(temp_handle.name)
        temp_handle.close()
        media_cleanup = PostCommitMediaCleanup()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current_ids = self._archive_candidate_ids(workspace_id, cutoff_at)
            if current_ids != expected_ids:
                raise StorageGovernanceError(
                    "storage_plan_changed",
                    "archive candidates changed; create a new preview",
                    status_code=409,
                )
            content_rows = self._content_rows(workspace_id, current_ids)
            records: list[dict[str, Any]] = []
            media_rows_by_id: dict[str, dict[str, Any]] = {}
            with zipfile.ZipFile(
                temp_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                for content_row in content_rows:
                    content = dict(content_row)
                    media_rows = conn.execute(
                        """
                        SELECT * FROM media_assets
                        WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                          AND asset_kind = 'content_image'
                        ORDER BY id
                        """,
                        (
                            workspace_id,
                            str(content["user_id"]),
                            str(content["article_id"]),
                        ),
                    ).fetchall()
                    media_records: list[dict[str, Any]] = []
                    for media_row in media_rows:
                        media = dict(media_row)
                        path = (self.data_dir / str(media["local_path"])).resolve()
                        if not path.is_relative_to(self.media_root) or not path.is_file():
                            continue
                        suffix = path.suffix[:16]
                        archive_name = f"media/{media['id']}{suffix}"
                        archive.write(path, archive_name)
                        media["archive_name"] = archive_name
                        media_records.append(media)
                        media_rows_by_id[str(media["id"])] = media
                    records.append({"content": content, "media": media_records})
                manifest = {
                    "schema_version": 1,
                    "batch_id": batch_id,
                    "workspace_id": workspace_id,
                    "cutoff_at": cutoff_at,
                    "item_count": len(records),
                    "media_count": len(media_rows_by_id),
                    "created_at": applied_at.isoformat(),
                }
                archive.writestr("manifest.json", _json(manifest))
                archive.writestr(
                    "items.ndjson",
                    "\n".join(_json(record) for record in records) + ("\n" if records else ""),
                )
            with zipfile.ZipFile(temp_path, "r") as archive:
                restored_manifest = _loads(archive.read("manifest.json"), {})
                item_lines = [
                    line
                    for line in archive.read("items.ndjson").decode("utf-8").splitlines()
                    if line.strip()
                ]
                if (
                    restored_manifest.get("batch_id") != batch_id
                    or int(restored_manifest.get("item_count", -1)) != len(item_lines)
                    or int(restored_manifest.get("media_count", -1))
                    != len(media_rows_by_id)
                ):
                    raise RuntimeError("archive verification failed")
            checksum = _file_checksum(temp_path)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, archive_path)
            byte_size = archive_path.stat().st_size
            conn.execute(
                """
                INSERT INTO storage_archive_batches (
                    id, workspace_id, created_by_user_id, status, cutoff_at,
                    archive_path, checksum, item_count, media_count, byte_size,
                    manifest_json, created_at, committed_at, updated_at
                ) VALUES (?, ?, ?, 'committed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    workspace_id,
                    actor_user_id,
                    cutoff_at,
                    str(archive_path.relative_to(self.data_dir.resolve())),
                    checksum,
                    len(records),
                    len(media_rows_by_id),
                    byte_size,
                    _json(manifest),
                    applied_at.isoformat(),
                    applied_at.isoformat(),
                    applied_at.isoformat(),
                ),
            )
            content_store = UserContentStore(self.store)
            for record in records:
                content = record["content"]
                item = _loads(content["item_json"], {})
                item = item if isinstance(item, dict) else {}
                cold_item = _cold_metadata_item(item)
                search_text = build_search_text(
                    cold_item,
                    source_native_title=content.get("source_native_title") or "",
                    include_body=False,
                )
                conn.execute(
                    """
                    UPDATE user_content_items
                    SET item_json = ?, body_text = '', body_truncated = 0,
                        body_completeness = 'excerpt_only',
                        analysis_input_hash = '', search_text = ?,
                        archive_batch_id = ?, archived_at = ?, updated_at = ?
                    WHERE id = ? AND workspace_id = ? AND archived_at IS NULL
                    """,
                    (
                        _json(cold_item),
                        search_text,
                        batch_id,
                        applied_at.isoformat(),
                        applied_at.isoformat(),
                        str(content["id"]),
                        workspace_id,
                    ),
                )
                updated = conn.execute(
                    """
                    SELECT id, workspace_id, user_id, article_id, effective_at, search_text
                    FROM user_content_items WHERE id = ?
                    """,
                    (str(content["id"]),),
                ).fetchone()
                if updated is not None:
                    content_store._replace_search_index(updated)
            for media in media_rows_by_id.values():
                path = (self.data_dir / str(media["local_path"])).resolve()
                if path.is_relative_to(self.media_root):
                    media_cleanup.add(path)
            self._delete_ids("media_assets", "id", sorted(media_rows_by_id))
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            media_cleanup.discard()
            temp_path.unlink(missing_ok=True)
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)
            raise
        media_cleanup.run()
        return {
            "operation": "archive",
            "batch_id": batch_id,
            "item_count": len(records),
            "media_count": len(media_rows_by_id),
            "byte_size": byte_size,
            "checksum": checksum,
            "applied_at": applied_at.isoformat(),
        }

    def _archive_row(self, workspace_id: str, batch_id: str) -> Any:
        row = self.store.connect().execute(
            """
            SELECT * FROM storage_archive_batches
            WHERE workspace_id = ? AND id = ?
            """,
            (workspace_id, batch_id),
        ).fetchone()
        if row is None:
            raise StorageGovernanceError(
                "storage_archive_not_found",
                "storage archive not found",
                status_code=404,
            )
        return row

    def _archive_path(self, row: Any) -> Path:
        path = (self.data_dir / str(row["archive_path"])).resolve()
        if not path.is_relative_to(self.archive_root):
            raise StorageGovernanceError(
                "storage_archive_invalid",
                "archive path is outside the managed archive root",
                status_code=409,
            )
        return path

    def _read_archive(self, row: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        path = self._archive_path(row)
        if not path.is_file() or _file_checksum(path) != str(row["checksum"]):
            raise StorageGovernanceError(
                "storage_archive_corrupt",
                "archive file is missing or failed checksum verification",
                status_code=409,
            )
        with zipfile.ZipFile(path, "r") as archive:
            manifest = _loads(archive.read("manifest.json"), {})
            if (
                manifest.get("batch_id") != row["id"]
                or manifest.get("workspace_id") != row["workspace_id"]
            ):
                raise StorageGovernanceError(
                    "storage_archive_corrupt",
                    "archive manifest does not match the database record",
                    status_code=409,
                )
            records = [
                _loads(line, {})
                for line in archive.read("items.ndjson").decode("utf-8").splitlines()
                if line.strip()
            ]
            if len(records) != int(row["item_count"]):
                raise StorageGovernanceError(
                    "storage_archive_corrupt",
                    "archive item count does not match the manifest",
                    status_code=409,
                )
        return manifest, records

    def _apply_restore(
        self,
        *,
        workspace_id: str,
        batch_id: str,
        applied_at: datetime,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        row = self._archive_row(workspace_id, batch_id)
        if row["status"] == "restored":
            return {
                "operation": "restore",
                "batch_id": batch_id,
                "already_restored": True,
                "item_count": int(row["item_count"]),
                "media_count": int(row["media_count"]),
            }
        if row["status"] != "committed":
            raise StorageGovernanceError(
                "storage_archive_unavailable",
                "archive cannot be restored in its current state",
                status_code=409,
            )
        _manifest, records = self._read_archive(row)
        path = self._archive_path(row)
        created_paths: list[Path] = []
        try:
            with zipfile.ZipFile(path, "r") as archive:
                for record in records:
                    for media in record.get("media") or []:
                        target = (self.data_dir / str(media["local_path"])).resolve()
                        if not target.is_relative_to(self.media_root):
                            raise StorageGovernanceError(
                                "storage_archive_invalid",
                                "archive contains an unsafe media path",
                                status_code=409,
                            )
                        archive_name = str(media["archive_name"])
                        if not archive_name.startswith("media/") or ".." in Path(archive_name).parts:
                            raise StorageGovernanceError(
                                "storage_archive_invalid",
                                "archive contains an unsafe media member",
                                status_code=409,
                            )
                        data = archive.read(archive_name)
                        if hashlib.sha256(data).hexdigest() != str(media["checksum"]):
                            raise StorageGovernanceError(
                                "storage_archive_corrupt",
                                "archived media failed checksum verification",
                                status_code=409,
                            )
                        if target.exists():
                            if _file_checksum(target) != str(media["checksum"]):
                                raise StorageGovernanceError(
                                    "storage_restore_conflict",
                                    "an existing media file has different content",
                                    status_code=409,
                                )
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tempfile.NamedTemporaryFile(
                            prefix=".restore-",
                            dir=target.parent,
                            delete=False,
                        ) as handle:
                            handle.write(data)
                            temp = Path(handle.name)
                        os.chmod(temp, 0o600)
                        os.replace(temp, target)
                        created_paths.append(target)
            conn.execute("BEGIN IMMEDIATE")
            content_store = UserContentStore(self.store)
            restored_items = 0
            restored_media = 0
            for record in records:
                content = dict(record.get("content") or {})
                updated = conn.execute(
                    """
                    UPDATE user_content_items
                    SET item_json = ?, body_text = ?, body_truncated = ?,
                        body_completeness = ?, analysis_input_hash = ?,
                        unresolved_reason = ?, search_text = ?,
                        archive_batch_id = ?, archived_at = NULL, updated_at = ?
                    WHERE id = ? AND workspace_id = ? AND archive_batch_id = ?
                    """,
                    (
                        str(content["item_json"]),
                        str(content["body_text"]),
                        int(content["body_truncated"]),
                        str(content["body_completeness"]),
                        str(content["analysis_input_hash"]),
                        content.get("unresolved_reason"),
                        str(content["search_text"]),
                        batch_id,
                        applied_at.isoformat(),
                        str(content["id"]),
                        workspace_id,
                        batch_id,
                    ),
                )
                restored_items += max(int(updated.rowcount), 0)
                restored_row = conn.execute(
                    """
                    SELECT id, workspace_id, user_id, article_id, effective_at, search_text
                    FROM user_content_items WHERE id = ? AND workspace_id = ?
                    """,
                    (str(content["id"]), workspace_id),
                ).fetchone()
                if restored_row is not None:
                    content_store._replace_search_index(restored_row)
                for media in record.get("media") or []:
                    values = [media.get(column) for column in _MEDIA_COLUMNS]
                    inserted = conn.execute(
                        f"""
                        INSERT OR IGNORE INTO media_assets ({", ".join(_MEDIA_COLUMNS)})
                        VALUES ({", ".join("?" for _ in _MEDIA_COLUMNS)})
                        """,
                        values,
                    )
                    restored_media += max(int(inserted.rowcount), 0)
            conn.execute(
                """
                UPDATE storage_archive_batches
                SET status = 'restored', restored_at = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ? AND status = 'committed'
                """,
                (applied_at.isoformat(), applied_at.isoformat(), batch_id, workspace_id),
            )
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            for created in created_paths:
                created.unlink(missing_ok=True)
            raise
        return {
            "operation": "restore",
            "batch_id": batch_id,
            "already_restored": False,
            "item_count": restored_items,
            "media_count": restored_media,
            "applied_at": applied_at.isoformat(),
        }

    def _apply_archive_delete(
        self,
        *,
        workspace_id: str,
        batch_id: str,
        applied_at: datetime,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        row = self._archive_row(workspace_id, batch_id)
        if row["status"] == "deleted":
            return {
                "operation": "delete_archive",
                "batch_id": batch_id,
                "already_deleted": True,
            }
        if row["status"] != "restored":
            raise StorageGovernanceError(
                "storage_archive_not_restored",
                "restore the archive before permanent deletion",
                status_code=409,
            )
        path = self._archive_path(row)
        deleting_path = path.with_suffix(path.suffix + ".deleting")
        if path.exists():
            os.replace(path, deleting_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE storage_archive_batches
                SET status = 'deleted', archive_path = '', byte_size = 0,
                    updated_at = ?
                WHERE id = ? AND workspace_id = ? AND status = 'restored'
                """,
                (applied_at.isoformat(), batch_id, workspace_id),
            )
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            if deleting_path.exists():
                os.replace(deleting_path, path)
            raise
        deleting_path.unlink(missing_ok=True)
        return {
            "operation": "delete_archive",
            "batch_id": batch_id,
            "already_deleted": False,
            "applied_at": applied_at.isoformat(),
        }

    def _plan(self, plan_id: str, *, workspace_id: str) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT * FROM storage_maintenance_plans
            WHERE id = ? AND workspace_id = ?
            """,
            (plan_id, workspace_id),
        ).fetchone()
        if row is None:
            raise StorageGovernanceError(
                "storage_plan_not_found",
                "storage plan not found",
                status_code=404,
            )
        value = dict(row)
        value["payload"] = _loads(value.pop("payload_json"), {})
        value["result"] = _loads(value.pop("result_json"), {})
        return value
