"""SQLite service database for small-group multi-user runtime state."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ..security import (
    classification_copies,
    is_sensitive_credential_key,
    text_contains_credential,
    url_contains_credentials,
)
from ..ui.auth import hash_password, verify_password_hash


DEFAULT_WORKSPACE_ID = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"
ROLES = {"owner", "admin", "member", "viewer"}
SOURCE_SCOPES = {"public", "workspace", "private"}
JOB_STATUSES = {"queued", "running", "succeeded", "failed", "partial", "cancelled"}
WORKER_STATES = {"starting", "idle", "running", "stopping"}
SQLITE_JOURNAL_MODES = {"WAL", "DELETE"}
AGENT_DELEGATION_READ_SCOPE = "inteliscope:read"
AGENT_DELEGATION_WRITE_SCOPE = "inteliscope:subscriptions:write"
AGENT_DELEGATION_SCOPE = AGENT_DELEGATION_READ_SCOPE
AGENT_DELEGATION_TTL_DAYS = 90
AGENT_DELEGATION_MAX_ACTIVE = 5
AGENT_DELEGATION_USAGE_TOUCH_MINUTES = 15
AGENT_DELEGATION_SCOPES_JSON_MAX_LENGTH = 512
AGENT_DELEGATION_SCOPES_JSON_MAX_DEPTH = 4
AGENT_PROPOSAL_TTL_MINUTES = 10
AGENT_PROPOSAL_MAX_PENDING = 10
AGENT_PROPOSAL_PREPARE_EXPIRED_RETENTION_HOURS = 24
AGENT_PROPOSAL_MAINTENANCE_RETENTION_DAYS = 30
_UNSET = object()

_PROPOSAL_PROHIBITED_CONTENT_KEYS = {
    "article_body",
    "article_content",
    "body",
    "error_message",
    "html",
    "job_payload",
    "payload",
    "raw_error",
    "raw_result",
}


class SourceKeyConflictError(ValueError):
    """A catalog source key is already owned by an incompatible source."""

    def __init__(self, source_key: str) -> None:
        self.source_key = source_key
        super().__init__("source_key already belongs to another catalog source")


class SecretEnvConflictError(ValueError):
    """A workspace already registered the requested secret environment name."""


class AgentDelegationLimitError(ValueError):
    """A user already owns the maximum number of active agent connections."""


class AgentProposalLimitError(ValueError):
    """A delegation already owns the maximum number of pending proposals."""


class AgentProposalAuthorizationError(ValueError):
    """A proposal write no longer has an active writable principal."""


class AgentProposalExpiredTransitionError(ValueError):
    """An apply transition reached the authoritative expiry boundary."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proposal_utc_now() -> datetime:
    """Return the authoritative proposal lifecycle clock in UTC."""

    return datetime.now(timezone.utc)


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


def _scopes_for_access(access: str) -> list[str]:
    if access == "read":
        return [AGENT_DELEGATION_READ_SCOPE]
    if access == "subscriptions_write":
        return [AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE]
    raise ValueError("access must be read or subscriptions_write")


def _bounded_agent_delegation_scopes_json(value: Any) -> list[str] | None:
    """Parse delegation scope storage without accepting SQLite dynamic values."""

    if not isinstance(value, str) or len(value) > AGENT_DELEGATION_SCOPES_JSON_MAX_LENGTH:
        return None
    depth = 0
    in_string = False
    escaped = False
    for character in value:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > AGENT_DELEGATION_SCOPES_JSON_MAX_DEPTH:
                return None
        elif character in "]}":
            depth -= 1
            if depth < 0:
                return None
    if depth != 0 or in_string:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, list) else None


def _safe_agent_delegation_scopes(scopes_json: Any) -> list[str]:
    raw_scopes = _bounded_agent_delegation_scopes_json(scopes_json)
    if (
        not isinstance(raw_scopes, list)
        or not all(isinstance(scope, str) for scope in raw_scopes)
        or len(raw_scopes) != len(set(raw_scopes))
    ):
        return []
    scopes = set(raw_scopes)
    if scopes == {AGENT_DELEGATION_READ_SCOPE}:
        return [AGENT_DELEGATION_READ_SCOPE]
    if scopes == {AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE}:
        return [AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE]
    return []


def _access_for_scopes(scopes: list[str]) -> str:
    if scopes == [AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE]:
        return "subscriptions_write"
    return "read"


def _proposal_classification_copies(value: str) -> tuple[str, ...] | None:
    """Build bounded, non-persistent copies for credential classification."""

    return classification_copies(value)


def _normalized_sensitive_key(value: Any) -> str:
    candidate = str(value)
    candidate = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", candidate)
    candidate = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", candidate)
    return re.sub(r"[^a-z0-9]+", "_", candidate.casefold()).strip("_")


def _is_sensitive_proposal_key(value: Any) -> bool:
    copies = _proposal_classification_copies(str(value))
    if copies is None:
        return True
    return any(_is_classified_sensitive_proposal_key(copy) for copy in copies)


def _is_classified_sensitive_proposal_key(value: str) -> bool:
    normalized = _normalized_sensitive_key(value)
    if normalized in _PROPOSAL_PROHIBITED_CONTENT_KEYS:
        return True
    return is_sensitive_credential_key(value)


def _contains_sensitive_query(value: str) -> bool:
    return url_contains_credentials(value)


def _proposal_data_contains_sensitive_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or _is_sensitive_proposal_key(key):
                return True
            if _proposal_data_contains_sensitive_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(_proposal_data_contains_sensitive_content(item) for item in value)
    if isinstance(value, str):
        copies = _proposal_classification_copies(value)
        if copies is None:
            return True
        return text_contains_credential(value) or url_contains_credentials(value)
    if value is None or isinstance(value, (bool, int)):
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    return True


def _require_safe_proposal_data(*values: Any) -> None:
    if any(_proposal_data_contains_sensitive_content(value) for value in values):
        raise ValueError("proposal data contains prohibited sensitive content")


def _parse_proposal_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("proposal timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("proposal timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _authoritative_proposal_time() -> datetime:
    current = _proposal_utc_now()
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise RuntimeError("proposal clock must return a timezone-aware datetime")
    return current.astimezone(timezone.utc)


def _bool(value: Any) -> bool:
    return bool(int(value or 0))


def _validate_subscription_priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("priority must be an integer between 0 and 100")
    return value


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
        self._local = threading.local()
        self._request_connection_active: ContextVar[bool] = ContextVar(
            f"service_store_request_active_{id(self)}",
            default=False,
        )
        self._request_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"service_store_request_connection_{id(self)}",
            default=None,
        )
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        request_scoped = self._request_connection_active.get()
        connection = (
            self._request_connection.get()
            if request_scoped
            else getattr(self._local, "connection", None)
        )
        if connection is None:
            journal_mode = os.getenv("HORIZON_SQLITE_JOURNAL_MODE", "WAL").strip().upper()
            if journal_mode not in SQLITE_JOURNAL_MODES:
                raise ValueError("HORIZON_SQLITE_JOURNAL_MODE must be WAL or DELETE")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            for attempt in range(20):
                try:
                    current_mode = str(
                        connection.execute("PRAGMA journal_mode").fetchone()[0]
                    ).upper()
                    if current_mode != journal_mode:
                        applied_mode = str(
                            connection.execute(
                                f"PRAGMA journal_mode = {journal_mode}"
                            ).fetchone()[0]
                        ).upper()
                        if applied_mode != journal_mode:
                            raise sqlite3.OperationalError(
                                f"failed to enable SQLite {journal_mode} journal mode"
                            )
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == 19:
                        connection.close()
                        raise
                    time.sleep(0.05)
            if request_scoped:
                self._request_connection.set(connection)
            else:
                self._local.connection = connection
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    def authoritative_agent_proposal_time(self) -> datetime:
        """Return the store-owned UTC clock for proposal state transitions."""

        return _authoritative_proposal_time()

    @contextmanager
    def request_connection_scope(self) -> Iterator[None]:
        """Give one async request an isolated connection lifecycle."""
        active_token = self._request_connection_active.set(True)
        connection_token = self._request_connection.set(None)
        try:
            yield
        finally:
            self.close_current()
            self._request_connection.reset(connection_token)
            self._request_connection_active.reset(active_token)

    def close(self) -> None:
        with self._connections_lock:
            connections = self._connections
            self._connections = []
        for connection in connections:
            connection.close()
        self._local.connection = None

    def close_current(self) -> None:
        """Close only the connection owned by the calling request or thread."""
        request_scoped = self._request_connection_active.get()
        connection = (
            self._request_connection.get()
            if request_scoped
            else getattr(self._local, "connection", None)
        )
        if connection is None:
            return
        try:
            if connection.in_transaction:
                connection.rollback()
        finally:
            connection.close()
            if request_scoped:
                self._request_connection.set(None)
            else:
                self._local.connection = None
            with self._connections_lock:
                self._connections = [
                    current
                    for current in self._connections
                    if current is not connection
                ]

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

            CREATE TABLE IF NOT EXISTS agent_delegations (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                client_type TEXT NOT NULL DEFAULT 'openclaw'
                    CHECK(client_type = 'openclaw'),
                token_hash TEXT NOT NULL UNIQUE,
                token_prefix TEXT NOT NULL,
                scopes_json TEXT NOT NULL DEFAULT '["inteliscope:read"]',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT,
                revocation_reason TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_delegations_user_created
                ON agent_delegations(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_delegations_workspace_user_status
                ON agent_delegations(workspace_id, user_id, revoked_at, expires_at);

            CREATE TABLE IF NOT EXISTS agent_change_proposals (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                delegation_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('create', 'update', 'delete')),
                source_id TEXT,
                subscription_id TEXT,
                payload_json TEXT NOT NULL,
                preview_json TEXT NOT NULL,
                fingerprints_json TEXT NOT NULL,
                confirmation_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'applied', 'expired')),
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                applied_at TEXT,
                result_summary_json TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(delegation_id) REFERENCES agent_delegations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_change_proposals_delegation_status_expires
                ON agent_change_proposals(delegation_id, status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_agent_change_proposals_status_updated
                ON agent_change_proposals(status, updated_at);

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
                enforce_public_network INTEGER NOT NULL DEFAULT 0
                    CHECK(enforce_public_network IN (0, 1)),
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
                claim_token TEXT,
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

            CREATE TABLE IF NOT EXISTS user_source_health (
                subscription_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('healthy', 'degraded', 'failing')),
                last_attempt_at TEXT NOT NULL,
                last_success_at TEXT,
                last_failure_at TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
                last_fetched_count INTEGER NOT NULL DEFAULT 0 CHECK(last_fetched_count >= 0),
                last_issue_stage TEXT,
                last_issue_code TEXT,
                last_issue_message TEXT,
                last_issue_retryable INTEGER CHECK(last_issue_retryable IN (0, 1)),
                last_job_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(last_job_id) REFERENCES fetch_jobs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_source_health_user_status
                ON user_source_health(workspace_id, user_id, status);
            CREATE INDEX IF NOT EXISTS idx_user_source_health_source
                ON user_source_health(workspace_id, source_id);

            CREATE TABLE IF NOT EXISTS user_source_health_applications (
                subscription_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                PRIMARY KEY(subscription_id, job_id),
                FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE CASCADE,
                FOREIGN KEY(job_id) REFERENCES fetch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_feed_schedules (
                user_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                interval_minutes INTEGER NOT NULL DEFAULT 360
                    CHECK(interval_minutes IN (60, 180, 360, 720, 1440)),
                next_run_at TEXT,
                last_evaluated_at TEXT,
                last_enqueued_at TEXT,
                last_job_id TEXT,
                last_skip_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(last_job_id) REFERENCES fetch_jobs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_feed_schedules_due
                ON user_feed_schedules(enabled, next_run_at);

            CREATE TABLE IF NOT EXISTS user_source_schedules (
                subscription_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                interval_minutes INTEGER NOT NULL DEFAULT 60
                    CHECK(interval_minutes IN (30, 60, 180, 360, 720, 1440)),
                next_run_at TEXT,
                last_evaluated_at TEXT,
                last_enqueued_at TEXT,
                last_job_id TEXT,
                last_skip_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(last_job_id) REFERENCES fetch_jobs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_source_schedules_due
                ON user_source_schedules(enabled, next_run_at);

            CREATE TABLE IF NOT EXISTS user_feed_snapshots (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                job_id TEXT,
                schema_version INTEGER NOT NULL DEFAULT 2,
                storage_version INTEGER NOT NULL DEFAULT 1,
                content_hash TEXT,
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
                source_id TEXT,
                subscription_id TEXT,
                position INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                topics_json TEXT NOT NULL DEFAULT '[]',
                score REAL,
                published_at TEXT,
                item_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(snapshot_id) REFERENCES user_feed_snapshots(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_feed_items_user_article
                ON user_feed_items(user_id, article_id);
            CREATE INDEX IF NOT EXISTS idx_user_feed_items_snapshot
                ON user_feed_items(snapshot_id);

            CREATE TABLE IF NOT EXISTS user_content_items (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                source_id TEXT,
                subscription_id TEXT,
                item_json TEXT NOT NULL DEFAULT '{}',
                body_text TEXT NOT NULL DEFAULT '',
                body_truncated INTEGER NOT NULL DEFAULT 0 CHECK(body_truncated IN (0, 1)),
                body_completeness TEXT NOT NULL DEFAULT 'excerpt_only'
                    CHECK(body_completeness IN ('captured', 'excerpt_only')),
                analysis_input_hash TEXT NOT NULL DEFAULT '',
                unresolved_reason TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, user_id, article_id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE SET NULL,
                FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_content_items_user_seen
                ON user_content_items(workspace_id, user_id, last_seen_at DESC);

            CREATE TABLE IF NOT EXISTS media_assets (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT,
                source_id TEXT,
                subscription_id TEXT,
                article_id TEXT,
                asset_kind TEXT NOT NULL,
                remote_url TEXT NOT NULL DEFAULT '',
                local_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL DEFAULT 0 CHECK(byte_size >= 0),
                checksum TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                alt TEXT NOT NULL DEFAULT '',
                visibility_scope TEXT NOT NULL DEFAULT 'private',
                status TEXT NOT NULL DEFAULT 'ready',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_media_assets_article
                ON media_assets(workspace_id, user_id, article_id, asset_kind, status);
            CREATE INDEX IF NOT EXISTS idx_media_assets_source
                ON media_assets(workspace_id, source_id, asset_kind, status);

            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS worker_heartbeats (
                worker_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                started_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                current_job_id TEXT,
                last_job_id TEXT,
                last_error_code TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(current_job_id) REFERENCES fetch_jobs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_heartbeat_at
                ON worker_heartbeats(heartbeat_at);

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

            CREATE TABLE IF NOT EXISTS user_analysis_cache (
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, article_id, input_hash, model, prompt_version),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_user_analysis_cache_updated
                ON user_analysis_cache(user_id, updated_at);

            CREATE TABLE IF NOT EXISTS secret_refs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                owner_user_id TEXT,
                name TEXT NOT NULL,
                env_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'ai',
                provider TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS source_acquisition_states (
                acquisition_key TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                isolation_scope TEXT NOT NULL,
                config_fingerprint TEXT NOT NULL,
                owner_job_id TEXT,
                claim_token TEXT,
                locked_until TEXT,
                retry_after TEXT,
                last_error_code TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_source_acquisition_states_lease
                ON source_acquisition_states(locked_until, retry_after);

            CREATE TABLE IF NOT EXISTS source_content_snapshots (
                id TEXT PRIMARY KEY,
                acquisition_key TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                config_fingerprint TEXT NOT NULL,
                isolation_scope TEXT NOT NULL,
                window_hours INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                fresh_until TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                producer_job_id TEXT,
                diagnostics_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_source_content_snapshots_key_time
                ON source_content_snapshots(acquisition_key, generated_at DESC, created_at DESC);

            CREATE TABLE IF NOT EXISTS source_content_items (
                id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                source_item_id TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                item_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(snapshot_id, source_item_id),
                FOREIGN KEY(snapshot_id) REFERENCES source_content_snapshots(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_source_content_items_snapshot_position
                ON source_content_items(snapshot_id, position);

            CREATE TABLE IF NOT EXISTS maintenance_state (
                key TEXT PRIMARY KEY,
                last_run_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
        self._ensure_column(
            "source_catalog",
            "enforce_public_network",
            "INTEGER NOT NULL DEFAULT 0",
        )
        self._ensure_column("fetch_jobs", "claim_token", "TEXT")
        self._ensure_column("fetch_jobs", "next_run_at", "TEXT")
        self._ensure_column("fetch_jobs", "locked_until", "TEXT")
        self._ensure_column("fetch_jobs", "cancelled_at", "TEXT")
        self._ensure_column("secret_refs", "kind", "TEXT NOT NULL DEFAULT 'ai'")
        self._ensure_column("secret_refs", "provider", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(
            "source_acquisition_states",
            "failure_count",
            "INTEGER NOT NULL DEFAULT 0",
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_secret_refs_workspace_env_name
                ON secret_refs(workspace_id, env_name)
            """
        )
        self._ensure_column("fetch_jobs", "expires_at", "TEXT")
        self._ensure_column("user_feed_snapshots", "schema_version", "INTEGER NOT NULL DEFAULT 2")
        self._ensure_column("user_feed_snapshots", "storage_version", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("user_feed_snapshots", "content_hash", "TEXT")
        self._ensure_column("user_feed_items", "source_id", "TEXT")
        self._ensure_column("user_feed_items", "subscription_id", "TEXT")
        self._ensure_column("user_feed_items", "position", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("user_feed_items", "item_json", "TEXT")
        self._ensure_column(
            "user_content_items", "analysis_input_hash", "TEXT NOT NULL DEFAULT ''"
        )
        self._ensure_column(
            "user_content_items", "unresolved_reason", "TEXT"
        )
        has_feed_rows = bool(
            conn.execute("SELECT 1 FROM user_feed_snapshots LIMIT 1").fetchone()
        )
        has_feed_artifacts = self._has_unmigrated_feed_artifacts()
        migrated = bool(
            conn.execute("SELECT 1 FROM schema_migrations WHERE version = 2").fetchone()
        )
        has_feed_storage_v3_artifacts = (
            self._has_unmigrated_feed_storage_v3_artifacts()
        )
        feed_storage_v3_migrated = bool(
            conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 3"
            ).fetchone()
        )
        has_content_index_v4_artifacts = self._has_unmigrated_content_index_v4_artifacts()
        content_index_v4_migrated = bool(
            conn.execute("SELECT 1 FROM schema_migrations WHERE version = 4").fetchone()
        )
        if has_feed_rows and not migrated:
            conn.execute("UPDATE user_feed_snapshots SET schema_version = 1")
        snapshot_duplicates = conn.execute(
            """
            SELECT 1 FROM user_feed_snapshots
            WHERE job_id IS NOT NULL
            GROUP BY job_id HAVING COUNT(*) > 1 LIMIT 1
            """
        ).fetchone()
        item_duplicates = conn.execute(
            """
            SELECT 1 FROM user_feed_items
            GROUP BY snapshot_id, article_id HAVING COUNT(*) > 1 LIMIT 1
            """
        ).fetchone()
        if not snapshot_duplicates and not item_duplicates:
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_feed_snapshots_job_id
                    ON user_feed_snapshots(job_id)
                    WHERE job_id IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_feed_items_snapshot_article
                    ON user_feed_items(snapshot_id, article_id)
                """
            )
        if not has_feed_artifacts and not migrated:
            self.mark_feed_v2_migrated(commit=False)
        if not has_feed_storage_v3_artifacts and not feed_storage_v3_migrated:
            self.mark_feed_storage_v3_migrated(commit=False)
        if not has_content_index_v4_artifacts and not content_index_v4_migrated:
            self.mark_content_index_v4_migrated(commit=False)
        self.mark_agent_delegations_v6_migrated(commit=False)
        self.mark_agent_change_proposals_v7_migrated(commit=False)
        self._bootstrap_default_workspace()
        self._bootstrap_admin_user()
        conn.commit()

    def mark_feed_v2_migrated(self, *, commit: bool = True) -> None:
        self.connect().execute(
            """
            INSERT OR REPLACE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (2, 'user_feed_v2', 'user-feed-v2-reset-20260710', ?)
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def feed_v2_migration_required(self) -> bool:
        migrated = self.connect().execute(
            "SELECT 1 FROM schema_migrations WHERE version = 2"
        ).fetchone()
        if migrated:
            return False
        return self._has_unmigrated_feed_artifacts()

    def mark_feed_storage_v3_migrated(self, *, commit: bool = True) -> None:
        self.connect().execute(
            """
            INSERT OR REPLACE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (3, 'feed_storage_v3', 'feed-storage-v3-hash-retention', ?)
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def feed_storage_v3_migration_required(self) -> bool:
        migrated = self.connect().execute(
            "SELECT 1 FROM schema_migrations WHERE version = 3"
        ).fetchone()
        if migrated:
            return False
        return self._has_unmigrated_feed_storage_v3_artifacts()

    def mark_content_index_v4_migrated(self, *, commit: bool = True) -> None:
        self.connect().execute(
            """
            INSERT OR REPLACE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (4, 'user_content_v4', 'user-content-v4-index-media', ?)
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def content_index_v4_migration_required(self) -> bool:
        migrated = self.connect().execute(
            "SELECT 1 FROM schema_migrations WHERE version = 4"
        ).fetchone()
        if migrated:
            return False
        return self._has_unmigrated_content_index_v4_artifacts()

    def mark_user_content_v5_migrated(self, *, commit: bool = True) -> None:
        self.connect().execute(
            """
            INSERT OR REPLACE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (5, 'user_content_v5', 'user-content-v5-repair-hash-media', ?)
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def mark_agent_delegations_v6_migrated(self, *, commit: bool = True) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (6, 'agent_delegations_v6', 'agent-delegations-v6-remote-mcp', ?)
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def mark_agent_change_proposals_v7_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (7, 'agent_change_proposals_v7', 'agent-change-proposals-v7', ?)
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def _has_unmigrated_content_index_v4_artifacts(self) -> bool:
        return bool(
            self.connect().execute(
                """
                SELECT 1
                FROM user_feed_items AS feed_item
                JOIN user_feed_snapshots AS snapshot
                  ON snapshot.id = feed_item.snapshot_id
                LEFT JOIN user_content_items AS content
                  ON content.workspace_id = snapshot.workspace_id
                 AND content.user_id = snapshot.user_id
                 AND content.article_id = feed_item.article_id
                WHERE content.id IS NULL
                LIMIT 1
                """
            ).fetchone()
        )

    def _has_unmigrated_feed_artifacts(self) -> bool:
        """Return whether an unmarked database contains data the v2 reset owns."""
        return bool(
            self.connect().execute(
                """
                SELECT 1 FROM user_feed_snapshots
                UNION ALL SELECT 1 FROM user_feed_items
                UNION ALL SELECT 1 FROM user_item_state
                UNION ALL SELECT 1 FROM user_item_feedback
                UNION ALL
                    SELECT 1 FROM fetch_jobs
                    WHERE job_type IN ('source_fetch', 'user_feed_refresh')
                      AND status IN ('queued', 'running')
                LIMIT 1
                """
            ).fetchone()
        )

    def _has_unmigrated_feed_storage_v3_artifacts(self) -> bool:
        """Return whether retention/hash rollout owns existing service data."""

        return bool(
            self.connect().execute(
                """
                SELECT 1 FROM user_feed_snapshots
                UNION ALL SELECT 1 FROM source_content_snapshots
                UNION ALL SELECT 1 FROM user_analysis_cache
                UNION ALL SELECT 1 FROM usage_events
                UNION ALL SELECT 1 FROM fetch_jobs
                UNION ALL SELECT 1 FROM sessions
                LIMIT 1
                """
            ).fetchone()
        )

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
    def _agent_delegation(row: sqlite3.Row, *, now: str) -> dict[str, Any]:
        revoked_at = row["revoked_at"]
        if revoked_at is not None:
            status = "revoked"
        elif row["expires_at"] <= now:
            status = "expired"
        else:
            status = "active"
        scopes = _safe_agent_delegation_scopes(row["scopes_json"])
        return {
            "id": row["id"],
            "name": row["name"],
            "client_type": row["client_type"],
            "access": _access_for_scopes(scopes),
            "scopes": scopes,
            "token_prefix": row["token_prefix"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "last_used_at": row["last_used_at"],
            "revoked_at": revoked_at,
            "status": status,
        }

    @staticmethod
    def _agent_change_proposal(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["payload"] = _json_loads(data.pop("payload_json", None), {})
        data["preview"] = _json_loads(data.pop("preview_json", None), {})
        data["fingerprints"] = _json_loads(
            data.pop("fingerprints_json", None), {}
        )
        data["result_summary"] = _json_loads(
            data.pop("result_summary_json", None), None
        )
        return data

    @staticmethod
    def _source(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        data["enforce_public_network"] = _bool(
            data.get("enforce_public_network")
        )
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
    def _secret_ref(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _job(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["payload_json"] = _json_loads(data.get("payload_json"), {})
        data["result_json"] = _json_loads(data.get("result_json"), None)
        return data

    @staticmethod
    def _worker_heartbeat(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def upsert_worker_heartbeat(
        self,
        worker_id: str,
        state: str,
        *,
        current_job_id: str | None = None,
        last_job_id: str | None = None,
        last_error_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        worker_id = str(worker_id or "").strip()
        if not worker_id:
            raise ValueError("worker_id is required")
        if state not in WORKER_STATES:
            raise ValueError(f"state must be one of {', '.join(sorted(WORKER_STATES))}")
        heartbeat_at = (now or datetime.now(timezone.utc)).isoformat()
        self.connect().execute(
            """
            INSERT INTO worker_heartbeats (
                worker_id, state, started_at, heartbeat_at, current_job_id,
                last_job_id, last_error_code, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                state = excluded.state,
                started_at = CASE
                    WHEN excluded.state = 'starting' THEN excluded.started_at
                    ELSE worker_heartbeats.started_at
                END,
                heartbeat_at = excluded.heartbeat_at,
                current_job_id = excluded.current_job_id,
                last_job_id = COALESCE(excluded.last_job_id, worker_heartbeats.last_job_id),
                last_error_code = COALESCE(excluded.last_error_code, worker_heartbeats.last_error_code),
                updated_at = excluded.updated_at
            """,
            (
                worker_id,
                state,
                heartbeat_at,
                heartbeat_at,
                current_job_id,
                last_job_id,
                last_error_code,
                heartbeat_at,
            ),
        )
        self.connect().commit()
        heartbeat = self.get_worker_heartbeat(worker_id)
        if heartbeat is None:
            raise LookupError("worker heartbeat not found after upsert")
        return heartbeat

    def get_worker_heartbeat(self, worker_id: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM worker_heartbeats WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        return self._worker_heartbeat(row)

    def list_worker_heartbeats(self) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            "SELECT * FROM worker_heartbeats ORDER BY worker_id"
        ).fetchall()
        return [heartbeat for row in rows if (heartbeat := self._worker_heartbeat(row))]

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

    def has_enabled_user(self) -> bool:
        """Return whether the service has at least one usable login identity."""
        return bool(
            self.connect().execute(
                "SELECT 1 FROM users WHERE enabled = 1 LIMIT 1"
            ).fetchone()
        )

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
        password: str | None = None,
    ) -> dict[str, Any]:
        if role is not None and role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(sorted(ROLES))}")
        conn = self.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            current = self.get_user(user_id)
            if current is None:
                raise LookupError("user not found")
            target_role = role or current["role"]
            target_enabled = bool(
                current["enabled"] if enabled is None else enabled
            )
            password_hash = current["password_hash"]
            if password:
                password_hash = hash_password(password)
            now = _now_iso()
            conn.execute(
                """
                UPDATE users
                SET role = ?, enabled = ?, display_name = ?, password_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    target_role,
                    1 if target_enabled else 0,
                    display_name if display_name is not None else current["display_name"],
                    password_hash,
                    now,
                    user_id,
                ),
            )
            if target_role == "viewer" or not target_enabled:
                invalidation_reason = (
                    "user_read_only" if target_role == "viewer" else "user_disabled"
                )
                conn.execute(
                    """
                    UPDATE user_feed_schedules
                    SET enabled = 0,
                        next_run_at = NULL,
                        last_skip_reason = ?,
                        updated_at = ?
                    WHERE user_id = ? AND enabled = 1
                    """,
                    (invalidation_reason, now, user_id),
                )
                conn.execute(
                    """
                    UPDATE user_source_schedules
                    SET enabled = 0,
                        next_run_at = NULL,
                        last_skip_reason = ?,
                        updated_at = ?
                    WHERE user_id = ? AND enabled = 1
                    """,
                    (invalidation_reason, now, user_id),
                )
                conn.execute(
                    """
                    UPDATE fetch_jobs
                    SET status = 'cancelled',
                        result_json = ?,
                        error_code = 'job_invalidated',
                        error_message = NULL,
                        worker_id = NULL,
                        claim_token = NULL,
                        locked_until = NULL,
                        cancelled_at = ?,
                        finished_at = ?,
                        updated_at = ?
                    WHERE user_id = ?
                      AND status = 'queued'
                    """,
                    (
                        _json_dumps({"invalidation_reason": invalidation_reason}),
                        now,
                        now,
                        now,
                        user_id,
                    ),
                )
            if not target_enabled:
                conn.execute(
                    """
                    UPDATE agent_delegations
                    SET revoked_at = ?,
                        revocation_reason = 'user_disabled',
                        updated_at = ?
                    WHERE user_id = ? AND revoked_at IS NULL
                    """,
                    (now, now, user_id),
                )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
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

    def create_agent_delegation(
        self,
        *,
        workspace_id: str,
        user_id: str,
        name: str,
        access: str = "read",
    ) -> tuple[dict[str, Any], str]:
        scopes = _scopes_for_access(access)
        delegation_name = str(name or "").strip()
        if not delegation_name:
            raise ValueError("name is required")
        if len(delegation_name) > 80:
            raise ValueError("name must not exceed 80 characters")
        now = _now_iso()
        expires_at = (
            datetime.fromisoformat(now) + timedelta(days=AGENT_DELEGATION_TTL_DAYS)
        ).isoformat()
        token = f"ih_mcp_v1_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        delegation_id = _new_id("agd")
        conn = self.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            user = self.get_user(user_id)
            if (
                user is None
                or not user["enabled"]
                or user["workspace_id"] != workspace_id
            ):
                raise LookupError("enabled user not found")
            active_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM agent_delegations
                WHERE user_id = ?
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (user_id, now),
            ).fetchone()[0]
            if active_count >= AGENT_DELEGATION_MAX_ACTIVE:
                raise AgentDelegationLimitError(
                    "agent delegation active limit reached"
                )
            conn.execute(
                """
                INSERT INTO agent_delegations (
                    id, workspace_id, user_id, name, client_type,
                    token_hash, token_prefix, scopes_json, created_at,
                    expires_at, last_used_at, revoked_at, revocation_reason,
                    updated_at
                ) VALUES (?, ?, ?, ?, 'openclaw', ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    delegation_id,
                    workspace_id,
                    user_id,
                    delegation_name,
                    token_hash,
                    token[:18],
                    _json_dumps(scopes),
                    now,
                    expires_at,
                    now,
                ),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        row = conn.execute(
            "SELECT * FROM agent_delegations WHERE id = ?", (delegation_id,)
        ).fetchone()
        if row is None:
            raise LookupError("created agent delegation not found")
        return self._agent_delegation(row, now=now), token

    def list_agent_delegations(self, user_id: str) -> list[dict[str, Any]]:
        now = _now_iso()
        rows = self.connect().execute(
            """
            SELECT * FROM agent_delegations
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
        return [self._agent_delegation(row, now=now) for row in rows]

    def rename_agent_delegation(
        self,
        user_id: str,
        delegation_id: str,
        name: str,
    ) -> dict[str, Any] | None:
        delegation_name = str(name or "").strip()
        if not delegation_name:
            raise ValueError("name is required")
        if len(delegation_name) > 80:
            raise ValueError("name must not exceed 80 characters")
        now = _now_iso()
        cursor = self.connect().execute(
            """
            UPDATE agent_delegations
            SET name = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (delegation_name, now, delegation_id, user_id),
        )
        self.connect().commit()
        if cursor.rowcount == 0:
            return None
        row = self.connect().execute(
            "SELECT * FROM agent_delegations WHERE id = ? AND user_id = ?",
            (delegation_id, user_id),
        ).fetchone()
        return self._agent_delegation(row, now=now) if row else None

    def revoke_agent_delegation(
        self,
        user_id: str,
        delegation_id: str,
        *,
        reason: str = "user_revoked",
    ) -> bool:
        now = _now_iso()
        row = self.connect().execute(
            "SELECT 1 FROM agent_delegations WHERE id = ? AND user_id = ?",
            (delegation_id, user_id),
        ).fetchone()
        if row is None:
            return False
        self.connect().execute(
            """
            UPDATE agent_delegations
            SET revoked_at = COALESCE(revoked_at, ?),
                revocation_reason = COALESCE(revocation_reason, ?),
                updated_at = CASE WHEN revoked_at IS NULL THEN ? ELSE updated_at END
            WHERE id = ? AND user_id = ?
            """,
            (now, reason, now, delegation_id, user_id),
        )
        self.connect().commit()
        return True

    def authenticate_agent_delegation(
        self,
        token: str,
    ) -> dict[str, Any] | None:
        candidate = str(token or "")
        if not candidate.startswith("ih_mcp_v1_"):
            return None
        token_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        now = _now_iso()
        row = self.connect().execute(
            """
            SELECT delegation.*, users.role, users.enabled
            FROM agent_delegations AS delegation
            JOIN users ON users.id = delegation.user_id
            WHERE delegation.token_hash = ?
              AND delegation.revoked_at IS NULL
              AND delegation.expires_at > ?
              AND users.enabled = 1
            """,
            (token_hash, now),
        ).fetchone()
        if row is None:
            return None
        last_used_at = row["last_used_at"]
        touch_before = (
            datetime.fromisoformat(now)
            - timedelta(minutes=AGENT_DELEGATION_USAGE_TOUCH_MINUTES)
        ).isoformat()
        if last_used_at is None or last_used_at <= touch_before:
            self.connect().execute(
                """
                UPDATE agent_delegations
                SET last_used_at = ?, updated_at = ?
                WHERE id = ?
                  AND (last_used_at IS NULL OR last_used_at <= ?)
                """,
                (now, now, row["id"], touch_before),
            )
            self.connect().commit()
        return {
            "delegation_id": row["id"],
            "workspace_id": row["workspace_id"],
            "user_id": row["user_id"],
            "role": row["role"],
            "scopes": _safe_agent_delegation_scopes(row["scopes_json"]),
            "expires_at": row["expires_at"],
        }

    def get_active_agent_delegation_principal(
        self,
        delegation_id: str,
    ) -> dict[str, Any] | None:
        """Re-read one delegation's live authorization state without its token.

        Proposal services use this after bearer-token verification so role,
        user status, revocation, expiry, and persisted scopes cannot be frozen
        into an earlier request claim or replaced by caller-provided fields.
        This read intentionally does not touch ``last_used_at``.
        """

        now = _now_iso()
        row = self.connect().execute(
            """
            SELECT delegation.*, users.role
            FROM agent_delegations AS delegation
            JOIN users ON users.id = delegation.user_id
            WHERE delegation.id = ?
              AND delegation.revoked_at IS NULL
              AND delegation.expires_at > ?
              AND users.enabled = 1
              AND users.workspace_id = delegation.workspace_id
            """,
            (str(delegation_id), now),
        ).fetchone()
        if row is None:
            return None
        return {
            "delegation_id": row["id"],
            "workspace_id": row["workspace_id"],
            "user_id": row["user_id"],
            "role": row["role"],
            "scopes": _safe_agent_delegation_scopes(row["scopes_json"]),
            "expires_at": row["expires_at"],
        }

    def create_agent_change_proposal(
        self,
        *,
        proposal_id: str,
        workspace_id: str,
        user_id: str,
        delegation_id: str,
        kind: str,
        source_id: str | None,
        subscription_id: str | None,
        payload: dict[str, Any],
        preview: dict[str, Any],
        fingerprints: dict[str, Any],
        confirmation_hash: str,
        created_at: str,
        expires_at: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        if kind not in {"create", "update", "delete"}:
            raise ValueError("proposal kind must be create, update, or delete")
        created = _parse_proposal_time(created_at)
        expires = _parse_proposal_time(expires_at)
        if expires - created != timedelta(minutes=AGENT_PROPOSAL_TTL_MINUTES):
            raise ValueError("proposal expiry must be exactly ten minutes")
        _require_safe_proposal_data(payload, preview, fingerprints)

        conn = self.connect()
        started_transaction = not conn.in_transaction
        try:
            if started_transaction:
                conn.execute("BEGIN IMMEDIATE")
            authoritative_now = _authoritative_proposal_time()
            created_iso = authoritative_now.isoformat()
            expires_iso = (
                authoritative_now
                + timedelta(minutes=AGENT_PROPOSAL_TTL_MINUTES)
            ).isoformat()
            principal = conn.execute(
                """
                SELECT delegation.scopes_json, users.role
                FROM agent_delegations AS delegation
                JOIN users ON users.id = delegation.user_id
                WHERE delegation.id = ?
                  AND delegation.workspace_id = ?
                  AND delegation.user_id = ?
                  AND delegation.revoked_at IS NULL
                  AND delegation.expires_at > ?
                  AND users.enabled = 1
                  AND users.workspace_id = delegation.workspace_id
                """,
                (delegation_id, workspace_id, user_id, created_iso),
            ).fetchone()
            if (
                principal is None
                or principal["role"] not in {"owner", "admin", "member"}
                or AGENT_DELEGATION_WRITE_SCOPE
                not in _safe_agent_delegation_scopes(principal["scopes_json"])
            ):
                raise AgentProposalAuthorizationError(
                    "agent proposal delegation is not authorized"
                )
            self._cleanup_agent_change_proposals_locked(
                now=authoritative_now,
                delegation_id=delegation_id,
                maintenance=False,
            )
            pending_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM agent_change_proposals
                    WHERE delegation_id = ?
                      AND status = 'pending'
                      AND expires_at > ?
                    """,
                    (delegation_id, created_iso),
                ).fetchone()[0]
            )
            if pending_count >= AGENT_PROPOSAL_MAX_PENDING:
                raise AgentProposalLimitError(
                    "agent proposal pending limit reached"
                )
            conn.execute(
                """
                INSERT INTO agent_change_proposals (
                    id, workspace_id, user_id, delegation_id, kind, source_id,
                    subscription_id, payload_json, preview_json,
                    fingerprints_json, confirmation_hash, status, created_at,
                    expires_at, applied_at, result_summary_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL, ?)
                """,
                (
                    proposal_id,
                    workspace_id,
                    user_id,
                    delegation_id,
                    kind,
                    source_id,
                    subscription_id,
                    _json_dumps(payload),
                    _json_dumps(preview),
                    _json_dumps(fingerprints),
                    confirmation_hash,
                    created_iso,
                    expires_iso,
                    created_iso,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_change_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if started_transaction and commit:
                conn.commit()
        except Exception:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            raise
        proposal = self._agent_change_proposal(row)
        if proposal is None:
            raise LookupError("created proposal not found")
        return proposal

    def get_agent_change_proposal(
        self, proposal_id: str
    ) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM agent_change_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        return self._agent_change_proposal(row)

    def expire_agent_change_proposal(
        self,
        proposal_id: str,
        *,
        now: str,
        commit: bool = True,
    ) -> dict[str, Any] | None:
        # Retain the argument for the existing store interface, but never use a
        # caller-selected timestamp to decide proposal eligibility.
        _parse_proposal_time(now)
        conn = self.connect()
        started_transaction = bool(commit and not conn.in_transaction)
        try:
            if started_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now_iso = self.authoritative_agent_proposal_time().isoformat()
            conn.execute(
                """
                UPDATE agent_change_proposals
                SET status = 'expired', updated_at = ?
                WHERE id = ? AND status = 'pending' AND expires_at <= ?
                """,
                (now_iso, proposal_id, now_iso),
            )
            row = conn.execute(
                "SELECT * FROM agent_change_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if started_transaction:
                conn.commit()
        except Exception:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return self._agent_change_proposal(row)

    def apply_agent_change_proposal(
        self,
        proposal_id: str,
        *,
        applied_at: str,
        result_summary: dict[str, Any],
        commit: bool = True,
    ) -> dict[str, Any]:
        _require_safe_proposal_data(result_summary)
        _parse_proposal_time(applied_at)
        conn = self.connect()
        started_transaction = bool(commit and not conn.in_transaction)
        try:
            if started_transaction:
                conn.execute("BEGIN IMMEDIATE")
            applied_iso = _authoritative_proposal_time().isoformat()
            cursor = conn.execute(
                """
                UPDATE agent_change_proposals
                SET status = 'applied', applied_at = ?, result_summary_json = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'pending' AND expires_at > ?
                """,
                (
                    applied_iso,
                    _json_dumps(result_summary),
                    applied_iso,
                    proposal_id,
                    applied_iso,
                ),
            )
            if cursor.rowcount != 1:
                existing = conn.execute(
                    "SELECT status, expires_at FROM agent_change_proposals WHERE id = ?",
                    (proposal_id,),
                ).fetchone()
                if existing is None:
                    raise LookupError("proposal not found")
                if (
                    existing["status"] == "pending"
                    and existing["expires_at"] <= applied_iso
                ):
                    raise AgentProposalExpiredTransitionError("proposal expired")
                raise ValueError("proposal is not pending")
            row = conn.execute(
                "SELECT * FROM agent_change_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if started_transaction:
                conn.commit()
        except Exception:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            raise
        proposal = self._agent_change_proposal(row)
        if proposal is None:
            raise LookupError("applied proposal not found")
        return proposal

    def cleanup_agent_change_proposals(
        self,
        *,
        now: str,
        delegation_id: str | None = None,
        maintenance: bool = False,
        commit: bool = True,
    ) -> dict[str, int]:
        current = _parse_proposal_time(now)
        conn = self.connect()
        started_transaction = bool(commit and not conn.in_transaction)
        try:
            if started_transaction:
                conn.execute("BEGIN IMMEDIATE")
            result = self._cleanup_agent_change_proposals_locked(
                now=current,
                delegation_id=delegation_id,
                maintenance=maintenance,
            )
            if started_transaction:
                conn.commit()
        except Exception:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return result

    def _cleanup_agent_change_proposals_locked(
        self,
        *,
        now: datetime,
        delegation_id: str | None,
        maintenance: bool,
    ) -> dict[str, int]:
        conn = self.connect()
        now_iso = now.astimezone(timezone.utc).isoformat()
        delegation_clause = ""
        parameters: list[Any] = [now_iso, now_iso]
        if delegation_id is not None:
            delegation_clause = " AND delegation_id = ?"
            parameters.append(delegation_id)
        expired = conn.execute(
            """
            UPDATE agent_change_proposals
            SET status = 'expired', updated_at = ?
            WHERE status = 'pending' AND expires_at <= ?
            """
            + delegation_clause,
            parameters,
        ).rowcount

        if maintenance:
            cutoff = (
                now - timedelta(days=AGENT_PROPOSAL_MAINTENANCE_RETENTION_DAYS)
            ).isoformat()
            delete_sql = """
                DELETE FROM agent_change_proposals
                WHERE status IN ('applied', 'expired') AND updated_at < ?
            """
        else:
            cutoff = (
                now
                - timedelta(hours=AGENT_PROPOSAL_PREPARE_EXPIRED_RETENTION_HOURS)
            ).isoformat()
            delete_sql = """
                DELETE FROM agent_change_proposals
                WHERE status = 'expired' AND expires_at < ?
            """
        delete_parameters: list[Any] = [cutoff]
        if delegation_id is not None:
            delete_sql += " AND delegation_id = ?"
            delete_parameters.append(delegation_id)
        deleted = conn.execute(delete_sql, delete_parameters).rowcount
        return {
            "expired": max(int(expired), 0),
            "deleted": max(int(deleted), 0),
        }

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

    def create_secret_ref(
        self,
        *,
        workspace_id: str,
        owner_user_id: str | None,
        name: str,
        env_name: str,
        kind: str,
        provider: str,
        scope: str = "workspace",
    ) -> dict[str, Any]:
        now = _now_iso()
        secret_id = _new_id("secret")
        try:
            self.connect().execute(
                """
                INSERT INTO secret_refs (
                    id, workspace_id, owner_user_id, name, env_name, scope,
                    kind, provider, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    secret_id,
                    workspace_id,
                    owner_user_id,
                    name,
                    env_name,
                    scope,
                    kind,
                    provider,
                    now,
                    now,
                ),
            )
            self.connect().commit()
        except sqlite3.IntegrityError as exc:
            if self.connect().in_transaction:
                self.connect().rollback()
            raise SecretEnvConflictError(env_name) from exc
        secret = self.get_secret_ref(secret_id)
        if secret is None:
            raise LookupError("created secret ref not found")
        return secret

    def get_secret_ref(self, secret_id: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM secret_refs WHERE id = ?",
            (secret_id,),
        ).fetchone()
        return self._secret_ref(row)

    def get_secret_ref_by_env(
        self,
        *,
        workspace_id: str,
        env_name: str,
    ) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM secret_refs WHERE workspace_id = ? AND env_name = ?",
            (workspace_id, env_name),
        ).fetchone()
        return self._secret_ref(row)

    def list_secret_refs(self, *, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT * FROM secret_refs
            WHERE workspace_id = ?
            ORDER BY created_at, name
            """,
            (workspace_id,),
        ).fetchall()
        return [secret for row in rows if (secret := self._secret_ref(row))]

    def touch_secret_ref(self, secret_id: str) -> dict[str, Any]:
        self.connect().execute(
            "UPDATE secret_refs SET updated_at = ? WHERE id = ?",
            (_now_iso(), secret_id),
        )
        self.connect().commit()
        secret = self.get_secret_ref(secret_id)
        if secret is None:
            raise LookupError("secret ref not found")
        return secret

    def delete_secret_ref(self, secret_id: str) -> bool:
        cursor = self.connect().execute("DELETE FROM secret_refs WHERE id = ?", (secret_id,))
        self.connect().commit()
        return cursor.rowcount == 1

    def list_sources_using_secret(
        self,
        *,
        workspace_id: str,
        env_name: str,
    ) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT * FROM source_catalog
            WHERE workspace_id = ? AND secret_env = ?
            ORDER BY created_at
            """,
            (workspace_id, env_name),
        ).fetchall()
        return [source for row in rows if (source := self._source(row))]

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
        enforce_public_network: bool = False,
        enabled: bool = True,
        commit: bool = True,
    ) -> str:
        if scope not in SOURCE_SCOPES:
            raise ValueError("scope must be public, workspace, or private")
        if not source_type:
            raise ValueError("source type is required")
        if not display_name:
            raise ValueError("display_name is required")
        now = _now_iso()
        source_id = _new_id("src")
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO source_catalog (
                    id, workspace_id, scope, owner_user_id, type, display_name,
                    description, default_channel, default_topics_json, config_json,
                    source_key, secret_env, enforce_public_network, enabled,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if enforce_public_network else 0,
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
            if owns_transaction:
                conn.commit()
        except sqlite3.IntegrityError as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            conflict_columns = "source_catalog.workspace_id, source_catalog.source_key"
            if source_key and conflict_columns in str(exc):
                raise SourceKeyConflictError(source_key) from exc
            raise
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return source_id

    def upsert_source(
        self,
        *,
        workspace_id: str,
        scope: str,
        owner_user_id: str | None,
        source_type: str,
        display_name: str,
        config: dict[str, Any],
        source_key: str,
        description: str = "",
        default_channel: str | None = None,
        default_topics: list[str] | None = None,
        secret_env: str | None = None,
        enforce_public_network: bool | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Atomically create or update one compatible workspace source key."""
        if scope not in SOURCE_SCOPES:
            raise ValueError("scope must be public, workspace, or private")
        if not source_type:
            raise ValueError("source type is required")
        if not display_name:
            raise ValueError("display_name is required")
        source_key = str(source_key or "").strip()
        if not source_key:
            raise ValueError("source_key is required")

        conn = self.connect()
        started_transaction = not conn.in_transaction
        now = _now_iso()
        try:
            if started_transaction:
                conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM source_catalog WHERE workspace_id = ? AND source_key = ?",
                (workspace_id, source_key),
            ).fetchone()
            existing = self._source(row)
            if existing is not None:
                compatible = (
                    existing["scope"] == scope
                    and existing["type"] == source_type
                    and (scope != "private" or existing["owner_user_id"] == owner_user_id)
                )
                if not compatible:
                    raise SourceKeyConflictError(source_key)
                source_id = str(existing["id"])
                self.update_source(
                    source_id,
                    display_name=display_name,
                    description=description,
                    default_channel=default_channel,
                    default_topics=default_topics or [],
                    config=config,
                    source_key=source_key,
                    secret_env=secret_env,
                    enforce_public_network=(
                        _UNSET
                        if enforce_public_network is None
                        else enforce_public_network
                    ),
                    enabled=enabled,
                    commit=False,
                )
            else:
                source_id = _new_id("src")
                conn.execute(
                    """
                    INSERT INTO source_catalog (
                        id, workspace_id, scope, owner_user_id, type, display_name,
                        description, default_channel, default_topics_json, config_json,
                        source_key, secret_env, enforce_public_network, enabled,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        1 if enforce_public_network else 0,
                        1 if enabled else 0,
                        now,
                        now,
                    ),
                )
            if started_transaction:
                conn.commit()
        except Exception:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            raise

        source = self.get_source(source_id)
        if source is None:
            raise LookupError("upserted source not found")
        return source

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

    def list_visible_sources(
        self,
        user: dict[str, Any],
        *,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT *
            FROM source_catalog
            WHERE workspace_id = ?
              AND (? = 1 OR enabled = 1)
              AND (
                scope IN ('public', 'workspace')
                OR (scope = 'private' AND owner_user_id = ?)
              )
            ORDER BY scope, display_name, id
            """,
            (user["workspace_id"], 1 if include_disabled else 0, user["id"]),
        ).fetchall()
        return [source for row in rows if (source := self._source(row))]

    def update_source(
        self,
        source_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        default_channel: Any = _UNSET,
        default_topics: Any = _UNSET,
        config: Any = _UNSET,
        source_key: Any = _UNSET,
        secret_env: Any = _UNSET,
        enforce_public_network: Any = _UNSET,
        enabled: Any = _UNSET,
        commit: bool = True,
    ) -> dict[str, Any]:
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        next_source_key: Any = None
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            current = self._source(
                conn.execute(
                    "SELECT * FROM source_catalog WHERE id = ?",
                    (source_id,),
                ).fetchone()
            )
            if current is None:
                raise LookupError("source not found")
            next_source_key = (
                current.get("source_key") if source_key is _UNSET else source_key
            )
            target_enabled = bool(
                current["enabled"]
                if enabled is _UNSET or enabled is None
                else enabled
            )
            now = _now_iso()
            affected_user_ids = []
            if not target_enabled:
                affected_user_ids = [
                    str(row["user_id"])
                    for row in conn.execute(
                        "SELECT DISTINCT user_id FROM user_subscriptions WHERE source_id = ?",
                        (source_id,),
                    ).fetchall()
                ]
            conn.execute(
                """
                UPDATE source_catalog
                SET display_name = ?, description = ?, default_channel = ?,
                    default_topics_json = ?, config_json = ?, source_key = ?, secret_env = ?,
                    enforce_public_network = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    display_name if display_name is not None else current["display_name"],
                    description if description is not None else current["description"],
                    current["default_channel"] if default_channel is _UNSET else default_channel,
                    _json_dumps(
                        current["default_topics"]
                        if default_topics is _UNSET or default_topics is None
                        else default_topics
                    ),
                    _json_dumps(
                        current["config"] if config is _UNSET or config is None else config
                    ),
                    next_source_key,
                    current["secret_env"] if secret_env is _UNSET else secret_env,
                    (
                        (1 if current["enforce_public_network"] else 0)
                        if enforce_public_network is _UNSET
                        else 1 if enforce_public_network else 0
                    ),
                    1 if target_enabled else 0,
                    now,
                    source_id,
                ),
            )
            if not target_enabled:
                conn.execute(
                    """
                    UPDATE user_source_schedules
                    SET enabled = 0,
                        next_run_at = NULL,
                        last_skip_reason = 'source_disabled',
                        updated_at = ?
                    WHERE source_id = ? AND enabled = 1
                    """,
                    (now, source_id),
                )
                conn.execute(
                    """
                    UPDATE fetch_jobs
                    SET status = 'cancelled',
                        result_json = ?,
                        error_code = 'job_invalidated',
                        error_message = NULL,
                        worker_id = NULL,
                        claim_token = NULL,
                        locked_until = NULL,
                        cancelled_at = ?,
                        finished_at = ?,
                        updated_at = ?
                    WHERE source_id = ?
                      AND job_type = 'source_fetch'
                      AND status = 'queued'
                    """,
                    (
                        _json_dumps({"invalidation_reason": "source_disabled"}),
                        now,
                        now,
                        now,
                        source_id,
                    ),
                )
                for affected_user_id in affected_user_ids:
                    self._reconcile_user_feed_locked(affected_user_id)
            updated = self._source(
                conn.execute(
                    "SELECT * FROM source_catalog WHERE id = ?",
                    (source_id,),
                ).fetchone()
            )
            if owns_transaction:
                conn.commit()
        except sqlite3.IntegrityError as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            if next_source_key:
                raise SourceKeyConflictError(str(next_source_key)) from exc
            raise
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
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
        commit: bool = True,
    ) -> dict[str, Any]:
        if analysis_mode not in {"full", "personal_only"}:
            raise ValueError("analysis_mode must be full or personal_only")
        priority = _validate_subscription_priority(priority)
        now = _now_iso()
        sub_id = _new_id("sub")
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            existing = self._subscription(
                conn.execute(
                    """
                    SELECT * FROM user_subscriptions
                    WHERE user_id = ? AND source_id = ?
                    """,
                    (user_id, source_id),
                ).fetchone()
            )
            if existing is not None:
                subscription = self.update_subscription(
                    existing["id"],
                    enabled=enabled,
                    override_channel=override_channel,
                    override_topics=override_topics or [],
                    personal_tags=personal_tags or [],
                    analysis_mode=analysis_mode,
                    priority=priority,
                    commit=False,
                )
                if owns_transaction:
                    conn.commit()
                return subscription
            conn.execute(
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
                    priority,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM user_subscriptions WHERE user_id = ? AND source_id = ?",
                (user_id, source_id),
            ).fetchone()
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
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
                sc.enforce_public_network,
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
                sc.enforce_public_network,
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

    def get_source_schedule(self, subscription_id: str) -> dict[str, Any] | None:
        row = self.connect().execute(
            "SELECT * FROM user_source_schedules WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        if row is None:
            return None
        schedule = dict(row)
        schedule["enabled"] = _bool(schedule["enabled"])
        schedule["interval_minutes"] = int(schedule["interval_minutes"])
        return schedule

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
        enabled: Any = _UNSET,
        override_channel: Any = _UNSET,
        override_topics: Any = _UNSET,
        personal_tags: Any = _UNSET,
        analysis_mode: Any = _UNSET,
        priority: Any = _UNSET,
        commit: bool = True,
    ) -> dict[str, Any]:
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            current = self._subscription(
                conn.execute(
                    "SELECT * FROM user_subscriptions WHERE id = ?",
                    (subscription_id,),
                ).fetchone()
            )
            if current is None:
                raise LookupError("subscription not found")
            mode = (
                current["analysis_mode"]
                if analysis_mode is _UNSET or analysis_mode is None
                else analysis_mode
            )
            if mode not in {"full", "personal_only"}:
                raise ValueError("analysis_mode must be full or personal_only")
            next_priority = (
                current["priority"]
                if priority is _UNSET
                else _validate_subscription_priority(priority)
            )
            target_enabled = bool(
                current["enabled"]
                if enabled is _UNSET or enabled is None
                else enabled
            )
            now = _now_iso()
            conn.execute(
                """
                UPDATE user_subscriptions
                SET enabled = ?, override_channel = ?, override_topics_json = ?,
                    personal_tags_json = ?, analysis_mode = ?, priority = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if target_enabled else 0,
                    current["override_channel"]
                    if override_channel is _UNSET
                    else override_channel,
                    _json_dumps(
                        current["override_topics"]
                        if override_topics is _UNSET or override_topics is None
                        else override_topics
                    ),
                    _json_dumps(
                        current["personal_tags"]
                        if personal_tags is _UNSET or personal_tags is None
                        else personal_tags
                    ),
                    mode,
                    next_priority,
                    now,
                    subscription_id,
                ),
            )
            if not target_enabled:
                conn.execute(
                    """
                    UPDATE user_source_schedules
                    SET enabled = 0,
                        next_run_at = NULL,
                        last_skip_reason = 'subscription_disabled',
                        updated_at = ?
                    WHERE subscription_id = ? AND enabled = 1
                    """,
                    (now, subscription_id),
                )
                conn.execute(
                    """
                    UPDATE fetch_jobs
                    SET status = 'cancelled',
                        result_json = ?,
                        error_code = 'job_invalidated',
                        error_message = NULL,
                        worker_id = NULL,
                        claim_token = NULL,
                        locked_until = NULL,
                        cancelled_at = ?,
                        finished_at = ?,
                        updated_at = ?
                    WHERE subscription_id = ?
                      AND job_type = 'source_fetch'
                      AND status = 'queued'
                    """,
                    (
                        _json_dumps(
                            {"invalidation_reason": "subscription_disabled"}
                        ),
                        now,
                        now,
                        now,
                        subscription_id,
                    ),
                )
                self._reconcile_user_feed_locked(str(current["user_id"]))
            updated = self._subscription(
                conn.execute(
                    "SELECT * FROM user_subscriptions WHERE id = ?",
                    (subscription_id,),
                ).fetchone()
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated is None:
            raise LookupError("updated subscription not found")
        return updated

    def delete_subscription(self, subscription_id: str, *, user_id: str) -> bool:
        conn = self.connect()
        owns_transaction = not conn.in_transaction
        now = _now_iso()
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT 1 FROM user_subscriptions WHERE id = ? AND user_id = ?",
                (subscription_id, user_id),
            ).fetchone()
            if existing is None:
                if owns_transaction:
                    conn.commit()
                return False
            conn.execute(
                """
                UPDATE fetch_jobs
                SET status = 'cancelled',
                    result_json = ?,
                    error_code = 'job_invalidated',
                    error_message = NULL,
                    worker_id = NULL,
                    claim_token = NULL,
                    locked_until = NULL,
                    cancelled_at = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE subscription_id = ?
                  AND status = 'queued'
                """,
                (
                    _json_dumps({"invalidation_reason": "subscription_deleted"}),
                    now,
                    now,
                    now,
                    subscription_id,
                ),
            )
            cur = conn.execute(
                "DELETE FROM user_subscriptions WHERE id = ? AND user_id = ?",
                (subscription_id, user_id),
            )
            self._reconcile_user_feed_locked(user_id)
            if owns_transaction:
                conn.commit()
            return cur.rowcount > 0
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def _reconcile_user_feed_locked(self, user_id: str) -> dict[str, Any] | None:
        user = self.get_user(user_id)
        if user is None:
            return None
        from ..services.user_feed_store import UserFeedStore

        return UserFeedStore(self).reconcile_active_subscriptions(
            workspace_id=str(user["workspace_id"]),
            user_id=user_id,
            commit=False,
        )

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
        commit: bool = True,
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
        if commit:
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
