"""SQLite service database for small-group multi-user runtime state."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..ui.auth import hash_password, verify_password_hash


DEFAULT_WORKSPACE_ID = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"
ROLES = {"owner", "admin", "member", "viewer"}
SOURCE_SCOPES = {"public", "workspace", "private"}
JOB_STATUSES = {"queued", "running", "succeeded", "failed", "partial", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _bool(value: Any) -> bool:
    return bool(int(value or 0))


def _env_username() -> str:
    return os.getenv("HORIZON_AUTH_USER", "admin").strip() or "admin"


def _env_password_hash() -> str | None:
    stored_hash = os.getenv("HORIZON_AUTH_PASSWORD_HASH")
    if stored_hash:
        return stored_hash
    password = os.getenv("HORIZON_AUTH_PASSWORD")
    if password:
        return hash_password(password)
    return None


class ServiceStore:
    """Repository for users, source catalog, subscriptions, jobs, and usage."""

    def __init__(
        self,
        data_dir: Path | str,
        db_path: Path | str | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path) if db_path is not None else self.data_dir / "service.db"
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def initialize(self) -> None:
        conn = self.connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, username),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS source_catalog (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                owner_user_id TEXT,
                type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                default_channel TEXT,
                default_topics_json TEXT NOT NULL DEFAULT '[]',
                config_json TEXT NOT NULL DEFAULT '{}',
                source_key TEXT,
                secret_env TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                override_channel TEXT,
                override_topics_json TEXT NOT NULL DEFAULT '[]',
                personal_tags_json TEXT NOT NULL DEFAULT '[]',
                analysis_mode TEXT NOT NULL DEFAULT 'full',
                priority INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, source_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS fetch_jobs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                source_id TEXT,
                subscription_id TEXT,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                worker_id TEXT,
                next_run_at TEXT,
                locked_until TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                cancelled_at TEXT,
                expires_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE SET NULL,
                FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fetch_jobs_status ON fetch_jobs(status, priority DESC, created_at);

            CREATE TABLE IF NOT EXISTS user_feed_snapshots (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                job_id TEXT,
                generated_at TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_feed_snapshots_user_time
                ON user_feed_snapshots(user_id, generated_at DESC, created_at DESC);

            CREATE TABLE IF NOT EXISTS user_feed_items (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                topics_json TEXT NOT NULL DEFAULT '[]',
                score REAL,
                published_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(snapshot_id) REFERENCES user_feed_snapshots(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_feed_items_user_article
                ON user_feed_items(user_id, article_id);
            CREATE INDEX IF NOT EXISTS idx_user_feed_items_snapshot
                ON user_feed_items(snapshot_id);

            CREATE TABLE IF NOT EXISTS user_item_state (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                is_saved INTEGER NOT NULL DEFAULT 0,
                is_later INTEGER NOT NULL DEFAULT 0,
                read_at TEXT,
                saved_at TEXT,
                later_at TEXT,
                dismissed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, user_id, article_id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_item_state_user_article
                ON user_item_state(user_id, article_id);

            CREATE TABLE IF NOT EXISTS user_item_feedback (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                value INTEGER,
                reason TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_item_feedback_user_article_time
                ON user_item_feedback(user_id, article_id, created_at);

            CREATE TABLE IF NOT EXISTS usage_events (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                provider TEXT,
                cost_estimate REAL NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_usage_events_user_type_time
                ON usage_events(user_id, event_type, created_at);

            CREATE TABLE IF NOT EXISTS secret_refs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                owner_user_id TEXT,
                name TEXT NOT NULL,
                env_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            """
        )
        self._ensure_column("source_catalog", "source_key", "TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_source_catalog_workspace_source_key
                ON source_catalog(workspace_id, source_key)
                WHERE source_key IS NOT NULL AND source_key != ''
            """
        )
        self._ensure_column("fetch_jobs", "max_attempts", "INTEGER NOT NULL DEFAULT 3")
        self._ensure_column("fetch_jobs", "next_run_at", "TEXT")
        self._ensure_column("fetch_jobs", "locked_until", "TEXT")
        self._ensure_column("fetch_jobs", "cancelled_at", "TEXT")
        self._ensure_column("fetch_jobs", "expires_at", "TEXT")
        self._bootstrap_default_workspace()
        self._bootstrap_admin_user()
        conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in self.connect().execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            self.connect().execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _bootstrap_default_workspace(self) -> None:
        now = _now_iso()
        self.connect().execute(
            """
            INSERT OR IGNORE INTO workspaces (id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (DEFAULT_WORKSPACE_ID, DEFAULT_WORKSPACE_NAME, now, now),
        )

    def _bootstrap_admin_user(self) -> None:
        username = _env_username()
        password_hash = _env_password_hash()
        if not password_hash:
            return
        existing = self.get_user_by_username(username)
        if existing:
            return
        now = _now_iso()
        self.connect().execute(
            """
            INSERT INTO users (
                id, workspace_id, username, display_name, role,
                password_hash, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("usr"),
                DEFAULT_WORKSPACE_ID,
                username,
                username,
                "owner",
                password_hash,
                1,
                now,
                now,
            ),
        )

    @staticmethod
    def _workspace(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _user(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        return data

    @staticmethod
    def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in user.items()
            if key not in {"password_hash"}
        }

    @staticmethod
    def _source(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        data["default_topics"] = _json_loads(data.pop("default_topics_json", None), [])
        data["config"] = _json_loads(data.pop("config_json", None), {})
        return data

    @staticmethod
    def _subscription(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        data["override_topics"] = _json_loads(data.pop("override_topics_json", None), [])
        data["personal_tags"] = _json_loads(data.pop("personal_tags_json", None), [])
        return data

    @staticmethod
    def _job(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["payload_json"] = _json_loads(data.get("payload_json"), {})
        data["result_json"] = _json_loads(data.get("result_json"), None)
        return data

    def get_default_workspace(self) -> dict[str, Any]:
        row = self.connect().execute(
            "SELECT * FROM workspaces WHERE id = ?",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()
        if row is None:
            raise LookupError("default workspace not initialized")
        return self._workspace(row)

    def list_users(self, *, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            "SELECT * FROM users WHERE workspace_id = ? ORDER BY created_at, username",
            (workspace_id,),
        ).fetchall()
        return [user for row in rows if (user := self._user(row))]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return self._user(row)

    def get_user_by_username(
        self,
        username: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM users WHERE workspace_id = ? AND username = ?",
            (workspace_id, username),
        ).fetchone()
        return self._user(row)

    def create_user(
        self,
        *,
        workspace_id: str,
        username: str,
        password: str,
        role: str = "member",
        display_name: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        username = str(username or "").strip()
        if not username:
            raise ValueError("username is required")
        if role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(sorted(ROLES))}")
        if not password:
            raise ValueError("password is required")
        now = _now_iso()
        user_id = _new_id("usr")
        self.connect().execute(
            """
            INSERT INTO users (
                id, workspace_id, username, display_name, role,
                password_hash, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                workspace_id,
                username,
                display_name or username,
                role,
                hash_password(password),
                1 if enabled else 0,
                now,
                now,
            ),
        )
        self.connect().commit()
        user = self.get_user(user_id)
        if user is None:
            raise LookupError("created user not found")
        return user

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        enabled: bool | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_user(user_id)
        if current is None:
            raise LookupError("user not found")
        if role is not None and role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(sorted(ROLES))}")
        self.connect().execute(
            """
            UPDATE users
            SET role = ?, enabled = ?, display_name = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                role or current["role"],
                1 if (current["enabled"] if enabled is None else enabled) else 0,
                display_name if display_name is not None else current["display_name"],
                _now_iso(),
                user_id,
            ),
        )
        self.connect().commit()
        updated = self.get_user(user_id)
        if updated is None:
            raise LookupError("updated user not found")
        return updated

    def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user_by_username(username)
        if not user or not user["enabled"]:
            return None
        if not verify_password_hash(password, user["password_hash"]):
            return None
        return user

    def create_session(self, user_id: str, *, ttl_seconds: int = 7 * 24 * 60 * 60) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        self.connect().execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, expires_at.isoformat(), now.isoformat()),
        )
        self.connect().commit()
        return token

    def get_session_user(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        row = self.connect().execute(
            """
            SELECT u.*
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, _now_iso()),
        ).fetchone()
        user = self._user(row)
        return user if user and user["enabled"] else None

    def delete_session(self, token: str | None) -> None:
        if token:
            self.connect().execute("DELETE FROM sessions WHERE token = ?", (token,))
            self.connect().commit()

    def create_source(
        self,
        *,
        workspace_id: str,
        scope: str,
        owner_user_id: str | None,
        source_type: str,
        display_name: str,
        config: dict[str, Any],
        description: str = "",
        default_channel: str | None = None,
        default_topics: list[str] | None = None,
        source_key: str | None = None,
        secret_env: str | None = None,
        enabled: bool = True,
    ) -> str:
        if scope not in SOURCE_SCOPES:
            raise ValueError("scope must be public, workspace, or private")
        if not source_type:
            raise ValueError("source type is required")
        if not display_name:
            raise ValueError("display_name is required")
        now = _now_iso()
        source_id = _new_id("src")
        self.connect().execute(
            """
            INSERT INTO source_catalog (
                id, workspace_id, scope, owner_user_id, type, display_name,
                description, default_channel, default_topics_json, config_json,
                source_key, secret_env, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                workspace_id,
                scope,
                owner_user_id,
                source_type,
                display_name,
                description,
                default_channel,
                _json_dumps(default_topics or []),
                _json_dumps(config),
                source_key,
                secret_env,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        self.connect().commit()
        return source_id

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM source_catalog WHERE id = ?",
            (source_id,),
        ).fetchone()
        return self._source(row)

    def get_source_by_key(self, *, workspace_id: str, source_key: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM source_catalog WHERE workspace_id = ? AND source_key = ?",
            (workspace_id, source_key),
        ).fetchone()
        return self._source(row)

    def list_visible_sources(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT *
            FROM source_catalog
            WHERE workspace_id = ?
              AND enabled = 1
              AND (
                scope IN ('public', 'workspace')
                OR (scope = 'private' AND owner_user_id = ?)
              )
            ORDER BY scope, display_name
            """,
            (user["workspace_id"], user["id"]),
        ).fetchall()
        return [source for row in rows if (source := self._source(row))]

    def update_source(
        self,
        source_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        default_channel: str | None = None,
        default_topics: list[str] | None = None,
        config: dict[str, Any] | None = None,
        source_key: str | None = None,
        secret_env: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get_source(source_id)
        if current is None:
            raise LookupError("source not found")
        self.connect().execute(
            """
            UPDATE source_catalog
            SET display_name = ?, description = ?, default_channel = ?,
                default_topics_json = ?, config_json = ?, source_key = ?, secret_env = ?,
                enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                display_name if display_name is not None else current["display_name"],
                description if description is not None else current["description"],
                default_channel if default_channel is not None else current["default_channel"],
                _json_dumps(default_topics if default_topics is not None else current["default_topics"]),
                _json_dumps(config if config is not None else current["config"]),
                source_key if source_key is not None else current.get("source_key"),
                secret_env if secret_env is not None else current["secret_env"],
                1 if (current["enabled"] if enabled is None else enabled) else 0,
                _now_iso(),
                source_id,
            ),
        )
        self.connect().commit()
        updated = self.get_source(source_id)
        if updated is None:
            raise LookupError("updated source not found")
        return updated

    def create_subscription(
        self,
        *,
        user_id: str,
        source_id: str,
        enabled: bool = True,
        override_channel: str | None = None,
        override_topics: list[str] | None = None,
        personal_tags: list[str] | None = None,
        analysis_mode: str = "full",
        priority: int = 0,
    ) -> dict[str, Any]:
        if analysis_mode not in {"full", "personal_only"}:
            raise ValueError("analysis_mode must be full or personal_only")
        now = _now_iso()
        sub_id = _new_id("sub")
        self.connect().execute(
            """
            INSERT INTO user_subscriptions (
                id, user_id, source_id, enabled, override_channel,
                override_topics_json, personal_tags_json, analysis_mode,
                priority, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, source_id) DO UPDATE SET
                enabled=excluded.enabled,
                override_channel=excluded.override_channel,
                override_topics_json=excluded.override_topics_json,
                personal_tags_json=excluded.personal_tags_json,
                analysis_mode=excluded.analysis_mode,
                priority=excluded.priority,
                updated_at=excluded.updated_at
            """,
            (
                sub_id,
                user_id,
                source_id,
                1 if enabled else 0,
                override_channel,
                _json_dumps(override_topics or []),
                _json_dumps(personal_tags or []),
                analysis_mode,
                int(priority),
                now,
                now,
            ),
        )
        self.connect().commit()
        row = self.connect().execute(
            "SELECT * FROM user_subscriptions WHERE user_id = ? AND source_id = ?",
            (user_id, source_id),
        ).fetchone()
        subscription = self._subscription(row)
        if subscription is None:
            raise LookupError("created subscription not found")
        return subscription

    def list_user_subscriptions(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT us.*, sc.display_name AS source_display_name, sc.type AS source_type
            FROM user_subscriptions us
            JOIN source_catalog sc ON sc.id = us.source_id
            WHERE us.user_id = ?
            ORDER BY us.priority DESC, us.created_at
            """,
            (user_id,),
        ).fetchall()
        return [subscription for row in rows if (subscription := self._subscription(row))]

    def list_enabled_user_subscriptions_with_sources(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT
                us.id AS subscription_id,
                us.user_id,
                us.source_id,
                us.enabled AS subscription_enabled,
                us.override_channel,
                us.override_topics_json,
                us.personal_tags_json,
                us.analysis_mode,
                us.priority,
                sc.workspace_id,
                sc.scope,
                sc.owner_user_id,
                sc.type,
                sc.display_name,
                sc.description,
                sc.default_channel,
                sc.default_topics_json,
                sc.config_json,
                sc.source_key,
                sc.secret_env,
                sc.enabled AS source_enabled
            FROM user_subscriptions us
            JOIN source_catalog sc ON sc.id = us.source_id
            WHERE us.user_id = ?
              AND sc.workspace_id = ?
              AND us.enabled = 1
              AND sc.enabled = 1
            ORDER BY us.priority DESC, us.created_at
            """,
            (user_id, workspace_id),
        ).fetchall()
        records = []
        for row in rows:
            data = dict(row)
            data["subscription_enabled"] = _bool(data["subscription_enabled"])
            data["source_enabled"] = _bool(data["source_enabled"])
            data["override_topics"] = _json_loads(data.pop("override_topics_json"), [])
            data["personal_tags"] = _json_loads(data.pop("personal_tags_json"), [])
            data["default_topics"] = _json_loads(data.pop("default_topics_json"), [])
            data["config"] = _json_loads(data.pop("config_json"), {})
            records.append(data)
        return records

    def list_user_subscriptions_with_sources(
        self,
        *,
        workspace_id: str,
        user_id: str,
        include_disabled_sources: bool = False,
    ) -> list[dict[str, Any]]:
        source_filter = "" if include_disabled_sources else "AND sc.enabled = 1"
        rows = self.connect().execute(
            f"""
            SELECT
                us.id AS subscription_id,
                us.user_id,
                us.source_id,
                us.enabled AS subscription_enabled,
                us.override_channel,
                us.override_topics_json,
                us.personal_tags_json,
                us.analysis_mode,
                us.priority,
                sc.workspace_id,
                sc.scope,
                sc.owner_user_id,
                sc.type,
                sc.display_name,
                sc.description,
                sc.default_channel,
                sc.default_topics_json,
                sc.config_json,
                sc.source_key,
                sc.secret_env,
                sc.enabled AS source_enabled
            FROM user_subscriptions us
            JOIN source_catalog sc ON sc.id = us.source_id
            WHERE us.user_id = ?
              AND sc.workspace_id = ?
              {source_filter}
            ORDER BY us.priority DESC, us.created_at
            """,
            (user_id, workspace_id),
        ).fetchall()
        records = []
        for row in rows:
            data = dict(row)
            data["subscription_enabled"] = _bool(data["subscription_enabled"])
            data["source_enabled"] = _bool(data["source_enabled"])
            data["override_topics"] = _json_loads(data.pop("override_topics_json"), [])
            data["personal_tags"] = _json_loads(data.pop("personal_tags_json"), [])
            data["default_topics"] = _json_loads(data.pop("default_topics_json"), [])
            data["config"] = _json_loads(data.pop("config_json"), {})
            records.append(data)
        return records

    def get_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM user_subscriptions WHERE id = ?",
            (subscription_id,),
        ).fetchone()
        return self._subscription(row)

    def get_user_subscription_for_source(self, user_id: str, source_id: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            """
            SELECT *
            FROM user_subscriptions
            WHERE user_id = ? AND source_id = ?
            """,
            (user_id, source_id),
        ).fetchone()
        return self._subscription(row)

    def update_subscription(
        self,
        subscription_id: str,
        *,
        enabled: bool | None = None,
        override_channel: str | None = None,
        override_topics: list[str] | None = None,
        personal_tags: list[str] | None = None,
        analysis_mode: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        current = self.get_subscription(subscription_id)
        if current is None:
            raise LookupError("subscription not found")
        mode = analysis_mode or current["analysis_mode"]
        if mode not in {"full", "personal_only"}:
            raise ValueError("analysis_mode must be full or personal_only")
        self.connect().execute(
            """
            UPDATE user_subscriptions
            SET enabled = ?, override_channel = ?, override_topics_json = ?,
                personal_tags_json = ?, analysis_mode = ?, priority = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                1 if (current["enabled"] if enabled is None else enabled) else 0,
                override_channel if override_channel is not None else current["override_channel"],
                _json_dumps(override_topics if override_topics is not None else current["override_topics"]),
                _json_dumps(personal_tags if personal_tags is not None else current["personal_tags"]),
                mode,
                int(priority if priority is not None else current["priority"]),
                _now_iso(),
                subscription_id,
            ),
        )
        self.connect().commit()
        updated = self.get_subscription(subscription_id)
        if updated is None:
            raise LookupError("updated subscription not found")
        return updated

    def delete_subscription(self, subscription_id: str, *, user_id: str) -> bool:
        cur = self.connect().execute(
            "DELETE FROM user_subscriptions WHERE id = ? AND user_id = ?",
            (subscription_id, user_id),
        )
        self.connect().commit()
        return cur.rowcount > 0

    def record_usage_event(
        self,
        *,
        workspace_id: str,
        user_id: str,
        event_type: str,
        quantity: int = 1,
        provider: str | None = None,
        cost_estimate: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = _new_id("use")
        self.connect().execute(
            """
            INSERT INTO usage_events (
                id, workspace_id, user_id, event_type, quantity,
                provider, cost_estimate, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                workspace_id,
                user_id,
                event_type,
                int(quantity),
                provider,
                float(cost_estimate),
                _json_dumps(metadata or {}),
                _now_iso(),
            ),
        )
        self.connect().commit()
        row = self.connect().execute(
            "SELECT * FROM usage_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return dict(row)

    def count_usage_since(
        self,
        *,
        workspace_id: str,
        user_id: str,
        event_types: list[str],
        since: datetime,
    ) -> int:
        placeholders = ",".join("?" for _ in event_types)
        row = self.connect().execute(
            f"""
            SELECT COALESCE(SUM(quantity), 0) AS total
            FROM usage_events
            WHERE workspace_id = ?
              AND user_id = ?
              AND event_type IN ({placeholders})
              AND created_at >= ?
            """,
            [workspace_id, user_id, *event_types, since.isoformat()],
        ).fetchone()
        return int(row["total"] or 0)
