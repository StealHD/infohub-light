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
AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE = "inteliscope:diagnostics:read"
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
AGENT_SOURCE_RESOLUTION_TTL_MINUTES = 10
AGENT_SOURCE_RESOLUTION_MAX_ACTIVE = 20
AGENT_SOURCE_RESOLUTION_RETENTION_HOURS = 24
AGENT_SOURCE_RESOLUTION_ENVELOPE_MAX_BYTES = 16_384
_UNSET = object()
WEBHOOK_PROVIDERS = {
    "legacy_auto",
    "generic_event",
    "generic_text",
    "feishu_lark_v2",
    "wecom",
    "dingtalk",
    "slack",
    "discord",
}
NOTIFICATION_CHANNELS = ("email", "webhook", "telegram")
NOTIFICATION_CHANNEL_SET = frozenset(NOTIFICATION_CHANNELS)
WEBHOOK_PROVIDER_TRIGGER_NAMES = {
    f"trg_{table}_webhook_v14_{operation}"
    for table in (
        "user_notification_settings",
        "apify_actor_alert_settings",
    )
    for operation in ("insert", "update")
}

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


class AgentSourceResolutionLimitError(ValueError):
    """A delegation already owns the maximum number of active resolutions."""


class AgentSourceResolutionAuthorizationError(ValueError):
    """A source resolution no longer has an active readable principal."""


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


def _scopes_for_access(
    access: str,
    *,
    diagnostics_scope: str = "self",
) -> list[str]:
    if access == "read":
        scopes = [AGENT_DELEGATION_READ_SCOPE]
    elif access == "subscriptions_write":
        scopes = [AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE]
    else:
        raise ValueError("access must be read or subscriptions_write")
    if diagnostics_scope == "workspace":
        scopes.append(AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE)
    elif diagnostics_scope != "self":
        raise ValueError("diagnostics_scope must be self or workspace")
    return scopes


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
    allowed = {
        AGENT_DELEGATION_READ_SCOPE,
        AGENT_DELEGATION_WRITE_SCOPE,
        AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE,
    }
    if (
        AGENT_DELEGATION_READ_SCOPE not in scopes
        or not scopes.issubset(allowed)
    ):
        return []
    return [
        scope
        for scope in (
            AGENT_DELEGATION_READ_SCOPE,
            AGENT_DELEGATION_WRITE_SCOPE,
            AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE,
        )
        if scope in scopes
    ]


def _access_for_scopes(scopes: list[str]) -> str:
    if AGENT_DELEGATION_WRITE_SCOPE in scopes:
        return "subscriptions_write"
    return "read"


def _diagnostics_scope_for_scopes(scopes: list[str]) -> str:
    return (
        "workspace"
        if AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE in scopes
        else "self"
    )


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

    def initialize(
        self,
        *,
        prepare_apify_actor_routing_v13: bool = False,
        prepare_webhook_providers_v14: bool = False,
        prepare_multichannel_notifications_v15: bool = False,
    ) -> None:
        conn = self.connect()
        existing_schema = bool(
            conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('workspaces', 'users', 'schema_migrations')
                LIMIT 1
                """
            ).fetchone()
        )
        has_migration_table = bool(
            conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_migrations'
                """
            ).fetchone()
        )
        apify_actor_v13_migrated = bool(
            has_migration_table
            and conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 13"
            ).fetchone()
        )
        apify_actor_v13_upgrade_pending = bool(
            existing_schema and not apify_actor_v13_migrated
        )
        install_apify_actor_v13 = bool(
            not existing_schema
            or apify_actor_v13_migrated
            or prepare_apify_actor_routing_v13
        )
        webhook_providers_v14_migrated = bool(
            has_migration_table
            and conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 14"
            ).fetchone()
        )
        webhook_providers_v14_upgrade_pending = bool(
            existing_schema and not webhook_providers_v14_migrated
        )
        install_webhook_providers_v14 = bool(
            not existing_schema
            or (
                apify_actor_v13_migrated
                and (
                    webhook_providers_v14_migrated
                    or prepare_webhook_providers_v14
                )
            )
        )
        multichannel_notifications_v15_migrated = bool(
            has_migration_table
            and conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 15"
            ).fetchone()
        )
        multichannel_notifications_v15_upgrade_pending = bool(
            existing_schema and not multichannel_notifications_v15_migrated
        )
        install_multichannel_notifications_v15 = bool(
            not existing_schema
            or (
                webhook_providers_v14_migrated
                and (
                    multichannel_notifications_v15_migrated
                    or prepare_multichannel_notifications_v15
                )
            )
        )
        schema_sql = """
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

            CREATE TABLE IF NOT EXISTS agent_source_resolutions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                delegation_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                envelope_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(delegation_id) REFERENCES agent_delegations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_source_resolutions_delegation_expires
                ON agent_source_resolutions(delegation_id, expires_at);
            CREATE INDEX IF NOT EXISTS idx_agent_source_resolutions_actor_fingerprint
                ON agent_source_resolutions(
                    workspace_id, user_id, delegation_id,
                    source_fingerprint, expires_at
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
                notify_on_new_items INTEGER NOT NULL DEFAULT 0
                    CHECK(notify_on_new_items IN (0, 1)),
                notification_enabled_at TEXT,
                notification_generation INTEGER NOT NULL DEFAULT 0,
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
            CREATE INDEX IF NOT EXISTS idx_fetch_jobs_workspace_created
                ON fetch_jobs(workspace_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_fetch_jobs_workspace_user_created
                ON fetch_jobs(workspace_id, user_id, created_at DESC);

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

            CREATE TABLE IF NOT EXISTS user_notification_settings (
                user_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                channel TEXT NOT NULL DEFAULT 'webhook'
                    CHECK(channel IN ('email', 'webhook', 'telegram')),
                email_address TEXT,
                webhook_env_name TEXT,
                webhook_secret_digest TEXT,
                webhook_provider TEXT NOT NULL DEFAULT 'legacy_auto'
                    CHECK(webhook_provider IN (
                        'legacy_auto', 'generic_event', 'generic_text',
                        'feishu_lark_v2', 'wecom', 'dingtalk', 'slack',
                        'discord'
                    )),
                webhook_signing_env_name TEXT,
                webhook_signing_secret_digest TEXT,
                notification_enabled_at TEXT,
                notification_generation INTEGER NOT NULL DEFAULT 0,
                last_test_status TEXT
                    CHECK(last_test_status IS NULL OR last_test_status IN ('sent', 'failed')),
                last_test_attempted_at TEXT,
                last_tested_at TEXT,
                last_test_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                CHECK(
                    (
                        webhook_signing_env_name IS NULL
                        AND webhook_signing_secret_digest IS NULL
                    )
                    OR (
                        webhook_signing_env_name IS NOT NULL
                        AND webhook_signing_secret_digest IS NOT NULL
                    )
                )
            );
            CREATE INDEX IF NOT EXISTS idx_user_notification_settings_workspace
                ON user_notification_settings(workspace_id, user_id);

            CREATE TABLE IF NOT EXISTS workspace_email_transports (
                workspace_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL
                    CHECK(provider IN (
                        'qq', 'netease', 'gmail', 'resend', 'amazon_ses'
                    )),
                sender_email TEXT NOT NULL,
                sender_name TEXT NOT NULL DEFAULT 'Inteliscope',
                region TEXT,
                smtp_username TEXT,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                credential_env_name TEXT,
                credential_secret_digest TEXT,
                generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
                last_test_status TEXT
                    CHECK(last_test_status IS NULL OR last_test_status IN ('sent', 'failed')),
                last_test_generation INTEGER,
                last_test_attempted_at TEXT,
                last_tested_at TEXT,
                last_test_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(
                    (credential_env_name IS NULL AND credential_secret_digest IS NULL)
                    OR (
                        credential_env_name IS NOT NULL
                        AND credential_secret_digest IS NOT NULL
                    )
                ),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

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

            CREATE TABLE IF NOT EXISTS preferred_source_notification_deliveries (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                subscription_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                channel TEXT NOT NULL
                    CHECK(channel IN ('email', 'webhook', 'telegram')),
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'sending', 'succeeded', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                account_notification_generation INTEGER NOT NULL DEFAULT 0,
                channel_notification_generation INTEGER NOT NULL DEFAULT 0,
                subscription_notification_generation INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(subscription_id, article_id, channel),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(subscription_id) REFERENCES user_subscriptions(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES source_catalog(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_preferred_source_notifications_pending
                ON preferred_source_notification_deliveries(status, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_preferred_source_notifications_job
                ON preferred_source_notification_deliveries(job_id, status, created_at);

            CREATE TABLE IF NOT EXISTS user_content_items (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                source_id TEXT,
                subscription_id TEXT,
                source_native_title TEXT,
                item_json TEXT NOT NULL DEFAULT '{}',
                body_text TEXT NOT NULL DEFAULT '',
                body_truncated INTEGER NOT NULL DEFAULT 0 CHECK(body_truncated IN (0, 1)),
                body_completeness TEXT NOT NULL DEFAULT 'excerpt_only'
                    CHECK(body_completeness IN ('captured', 'excerpt_only')),
                analysis_input_hash TEXT NOT NULL DEFAULT '',
                unresolved_reason TEXT,
                effective_at TEXT NOT NULL DEFAULT '',
                search_text TEXT NOT NULL DEFAULT '',
                archive_batch_id TEXT,
                archived_at TEXT,
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

            CREATE TABLE IF NOT EXISTS workspace_feed_end_messages (
                workspace_id TEXT PRIMARY KEY,
                messages_json TEXT NOT NULL DEFAULT '{}',
                config_fingerprint TEXT NOT NULL DEFAULT '',
                generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
                status TEXT NOT NULL DEFAULT 'empty'
                    CHECK(status IN ('empty', 'pending', 'refreshing', 'ready', 'failed')),
                requested_by_user_id TEXT,
                force_refresh INTEGER NOT NULL DEFAULT 0
                    CHECK(force_refresh IN (0, 1)),
                claim_token TEXT,
                claimed_by TEXT,
                lease_expires_at TEXT,
                last_attempt_at TEXT,
                last_success_at TEXT,
                next_refresh_at TEXT,
                retry_at TEXT,
                last_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(requested_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workspace_feed_end_messages_due
                ON workspace_feed_end_messages(
                    status, force_refresh, retry_at, next_refresh_at, lease_expires_at
                );

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
                version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS apify_key_pool_state (
                workspace_id TEXT PRIMARY KEY,
                generation INTEGER NOT NULL DEFAULT 1
                    CHECK(generation >= 1),
                status TEXT NOT NULL DEFAULT 'empty'
                    CHECK(status IN ('empty', 'ready', 'draining', 'blocked', 'exhausted')),
                active_secret_id TEXT,
                draining_secret_id TEXT,
                drain_generation INTEGER,
                drain_target_status TEXT
                    CHECK(drain_target_status IS NULL OR drain_target_status IN (
                        'standby', 'depleted', 'invalid'
                    )),
                drain_reason TEXT,
                drain_started_at TEXT,
                blocked_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS apify_key_pool_members (
                workspace_id TEXT NOT NULL,
                secret_id TEXT NOT NULL,
                position INTEGER NOT NULL CHECK(position >= 0),
                status TEXT NOT NULL
                    CHECK(status IN ('active', 'standby', 'draining', 'depleted', 'invalid')),
                blocked_until TEXT,
                cycle_start_at TEXT,
                cycle_end_at TEXT,
                last_checked_at TEXT,
                last_error_code TEXT,
                monthly_included_credits_usd REAL
                    CHECK(monthly_included_credits_usd IS NULL OR monthly_included_credits_usd >= 0),
                monthly_usage_usd REAL
                    CHECK(monthly_usage_usd IS NULL OR monthly_usage_usd >= 0),
                remaining_included_credits_usd REAL
                    CHECK(remaining_included_credits_usd IS NULL OR remaining_included_credits_usd >= 0),
                max_monthly_usage_usd REAL
                    CHECK(max_monthly_usage_usd IS NULL OR max_monthly_usage_usd >= 0),
                remaining_hard_limit_usd REAL
                    CHECK(remaining_hard_limit_usd IS NULL OR remaining_hard_limit_usd >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, secret_id),
                UNIQUE(workspace_id, position),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(secret_id) REFERENCES secret_refs(id) ON DELETE RESTRICT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_apify_key_pool_one_active
                ON apify_key_pool_members(workspace_id)
                WHERE status = 'active';
            CREATE INDEX IF NOT EXISTS idx_apify_key_pool_members_status
                ON apify_key_pool_members(workspace_id, status, position);

            CREATE TABLE IF NOT EXISTS apify_actor_runs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                logical_run_id TEXT,
                secret_id TEXT NOT NULL,
                secret_version INTEGER NOT NULL CHECK(secret_version >= 1),
                pool_generation INTEGER NOT NULL CHECK(pool_generation >= 1),
                remote_run_id TEXT,
                dataset_id TEXT,
                status TEXT NOT NULL,
                last_error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                terminal_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_apify_actor_runs_remote
                ON apify_actor_runs(workspace_id, remote_run_id)
                WHERE remote_run_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_apify_actor_runs_barrier
                ON apify_actor_runs(workspace_id, pool_generation, status);
            CREATE INDEX IF NOT EXISTS idx_apify_actor_runs_secret_status
                ON apify_actor_runs(workspace_id, secret_id, status);

            -- APIFY_ACTOR_ROUTING_V13_BEGIN
            CREATE TABLE IF NOT EXISTS apify_actor_routes (
                workspace_id TEXT NOT NULL,
                route_key TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 1
                    CHECK(generation >= 1),
                status TEXT NOT NULL DEFAULT 'ready'
                    CHECK(status IN (
                        'ready', 'degraded', 'exhausted',
                        'budget_blocked', 'blocked'
                    )),
                active_candidate_id TEXT,
                last_switch_reason TEXT,
                last_switch_at TEXT,
                budget_blocked_until TEXT,
                blocked_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, route_key),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS apify_actor_candidates (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                route_key TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                adapter_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                position INTEGER NOT NULL CHECK(position >= 0),
                state TEXT NOT NULL
                    CHECK(state IN (
                        'closed', 'open', 'half_open',
                        'disabled', 'probationary'
                    )),
                failure_level INTEGER NOT NULL DEFAULT 0
                    CHECK(failure_level >= 0),
                recovery_successes INTEGER NOT NULL DEFAULT 0
                    CHECK(recovery_successes >= 0),
                probe_claimed_at TEXT,
                opened_at TEXT,
                retry_at TEXT,
                probation_started_at TEXT,
                success_count INTEGER NOT NULL DEFAULT 0
                    CHECK(success_count >= 0),
                failure_count INTEGER NOT NULL DEFAULT 0
                    CHECK(failure_count >= 0),
                last_attempt_at TEXT,
                last_success_at TEXT,
                last_failure_at TEXT,
                last_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, route_key, position),
                UNIQUE(workspace_id, route_key, actor_id),
                FOREIGN KEY(workspace_id, route_key)
                    REFERENCES apify_actor_routes(workspace_id, route_key)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_apify_actor_candidates_route_state
                ON apify_actor_candidates(workspace_id, route_key, state, position);
            CREATE INDEX IF NOT EXISTS idx_apify_actor_candidates_recovery
                ON apify_actor_candidates(workspace_id, route_key, retry_at);

            CREATE TABLE IF NOT EXISTS apify_actor_attempts (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                route_key TEXT NOT NULL,
                route_generation INTEGER NOT NULL CHECK(route_generation >= 1),
                candidate_id TEXT NOT NULL,
                source_id TEXT,
                job_id TEXT,
                attempt_group_id TEXT NOT NULL,
                attempt_index INTEGER NOT NULL CHECK(attempt_index BETWEEN 1 AND 3),
                status TEXT NOT NULL
                    CHECK(status IN (
                        'reserved', 'running', 'succeeded', 'valid_empty',
                        'actor_failed', 'target_failed',
                        'start_outcome_unknown', 'cancelled'
                    )),
                semantic_outcome TEXT,
                reserved_usd REAL NOT NULL DEFAULT 0.02
                    CHECK(reserved_usd >= 0 AND reserved_usd <= 0.02),
                actual_cost_usd REAL
                    CHECK(actual_cost_usd IS NULL OR actual_cost_usd >= 0),
                cost_final INTEGER NOT NULL DEFAULT 0 CHECK(cost_final IN (0, 1)),
                last_error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                terminal_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id, route_key)
                    REFERENCES apify_actor_routes(workspace_id, route_key)
                    ON DELETE CASCADE,
                FOREIGN KEY(candidate_id)
                    REFERENCES apify_actor_candidates(id) ON DELETE RESTRICT,
                FOREIGN KEY(source_id)
                    REFERENCES source_catalog(id) ON DELETE SET NULL,
                FOREIGN KEY(job_id)
                    REFERENCES fetch_jobs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_apify_actor_attempts_group
                ON apify_actor_attempts(
                    workspace_id, route_key, attempt_group_id, attempt_index
                );
            CREATE INDEX IF NOT EXISTS idx_apify_actor_attempts_candidate_time
                ON apify_actor_attempts(candidate_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_apify_actor_attempts_failed_cost
                ON apify_actor_attempts(workspace_id, route_key, terminal_at)
                WHERE status IN (
                    'actor_failed', 'target_failed', 'start_outcome_unknown'
                );

            CREATE TABLE IF NOT EXISTS apify_actor_target_health (
                workspace_id TEXT NOT NULL,
                route_key TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                had_valid_nonempty INTEGER NOT NULL DEFAULT 0
                    CHECK(had_valid_nonempty IN (0, 1)),
                consecutive_failures INTEGER NOT NULL DEFAULT 0
                    CHECK(consecutive_failures >= 0),
                last_semantic_outcome TEXT,
                last_valid_at TEXT,
                last_failure_at TEXT,
                paused_until TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, route_key, candidate_id, source_id),
                FOREIGN KEY(workspace_id, route_key)
                    REFERENCES apify_actor_routes(workspace_id, route_key)
                    ON DELETE CASCADE,
                FOREIGN KEY(candidate_id)
                    REFERENCES apify_actor_candidates(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id)
                    REFERENCES source_catalog(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_apify_actor_target_health_paused
                ON apify_actor_target_health(
                    workspace_id, route_key, source_id, paused_until
                );

            CREATE TABLE IF NOT EXISTS apify_actor_alert_settings (
                workspace_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                channel TEXT NOT NULL DEFAULT 'webhook'
                    CHECK(channel IN ('email', 'webhook', 'telegram')),
                events_json TEXT NOT NULL DEFAULT '[]',
                email_address TEXT,
                webhook_env_name TEXT,
                webhook_secret_digest TEXT,
                webhook_provider TEXT NOT NULL DEFAULT 'legacy_auto'
                    CHECK(webhook_provider IN (
                        'legacy_auto', 'generic_event', 'generic_text',
                        'feishu_lark_v2', 'wecom', 'dingtalk', 'slack',
                        'discord'
                    )),
                webhook_signing_env_name TEXT,
                webhook_signing_secret_digest TEXT,
                generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
                notification_enabled_at TEXT,
                last_test_status TEXT
                    CHECK(last_test_status IS NULL OR last_test_status IN ('sent', 'failed')),
                last_test_generation INTEGER,
                last_test_attempted_at TEXT,
                last_tested_at TEXT,
                last_test_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                CHECK(
                    (
                        webhook_signing_env_name IS NULL
                        AND webhook_signing_secret_digest IS NULL
                    )
                    OR (
                        webhook_signing_env_name IS NOT NULL
                        AND webhook_signing_secret_digest IS NOT NULL
                    )
                )
            );

            CREATE TABLE IF NOT EXISTS apify_actor_alert_incidents (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                route_key TEXT NOT NULL,
                incident_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL
                    CHECK(severity IN ('info', 'warning', 'critical')),
                status TEXT NOT NULL CHECK(status IN ('open', 'resolved')),
                payload_json TEXT NOT NULL DEFAULT '{}',
                opened_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                resolved_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_apify_actor_alert_open_incident
                ON apify_actor_alert_incidents(workspace_id, route_key, incident_key)
                WHERE status = 'open';
            CREATE INDEX IF NOT EXISTS idx_apify_actor_alert_incidents_recent
                ON apify_actor_alert_incidents(workspace_id, opened_at DESC);

            CREATE TABLE IF NOT EXISTS apify_actor_alert_deliveries (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                incident_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                channel TEXT NOT NULL
                    CHECK(channel IN ('email', 'webhook', 'telegram')),
                settings_generation INTEGER NOT NULL CHECK(settings_generation >= 1),
                channel_generation INTEGER NOT NULL DEFAULT 1
                    CHECK(channel_generation >= 1),
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK(status IN ('pending', 'sending', 'succeeded', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0
                    CHECK(attempts BETWEEN 0 AND 3),
                retry_at TEXT,
                error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(incident_id, event_type, channel),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(incident_id)
                    REFERENCES apify_actor_alert_incidents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_apify_actor_alert_delivery_due
                ON apify_actor_alert_deliveries(status, retry_at, created_at);
            -- APIFY_ACTOR_ROUTING_V13_END

            -- MULTICHANNEL_NOTIFICATIONS_V15_BEGIN
            CREATE TABLE IF NOT EXISTS user_notification_channels (
                user_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                channel TEXT NOT NULL
                    CHECK(channel IN ('email', 'webhook', 'telegram')),
                position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                enabled_at TEXT,
                generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
                destination_env_name TEXT,
                destination_secret_digest TEXT,
                last_test_status TEXT
                    CHECK(last_test_status IS NULL OR last_test_status IN (
                        'sent', 'failed'
                    )),
                last_test_generation INTEGER,
                last_test_attempted_at TEXT,
                last_tested_at TEXT,
                last_test_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, channel),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id)
                    REFERENCES workspaces(id) ON DELETE CASCADE,
                CHECK(
                    (destination_env_name IS NULL)
                    = (destination_secret_digest IS NULL)
                )
            );
            CREATE INDEX IF NOT EXISTS idx_user_notification_channels_workspace
                ON user_notification_channels(
                    workspace_id, user_id, enabled, position
                );

            CREATE TABLE IF NOT EXISTS workspace_telegram_transports (
                workspace_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                token_env_name TEXT,
                token_secret_digest TEXT,
                generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
                last_test_status TEXT
                    CHECK(last_test_status IS NULL OR last_test_status IN (
                        'sent', 'failed'
                    )),
                last_test_generation INTEGER,
                last_test_attempted_at TEXT,
                last_tested_at TEXT,
                last_test_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(
                    (token_env_name IS NULL) = (token_secret_digest IS NULL)
                ),
                FOREIGN KEY(workspace_id)
                    REFERENCES workspaces(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS apify_actor_alert_channels (
                workspace_id TEXT NOT NULL,
                channel TEXT NOT NULL
                    CHECK(channel IN ('email', 'webhook', 'telegram')),
                position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                enabled_at TEXT,
                generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
                destination_env_name TEXT,
                destination_secret_digest TEXT,
                last_test_status TEXT
                    CHECK(last_test_status IS NULL OR last_test_status IN (
                        'sent', 'failed'
                    )),
                last_test_generation INTEGER,
                last_test_attempted_at TEXT,
                last_tested_at TEXT,
                last_test_error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, channel),
                FOREIGN KEY(workspace_id)
                    REFERENCES workspaces(id) ON DELETE CASCADE,
                CHECK(
                    (destination_env_name IS NULL)
                    = (destination_secret_digest IS NULL)
                )
            );
            CREATE INDEX IF NOT EXISTS idx_apify_actor_alert_channels_enabled
                ON apify_actor_alert_channels(
                    workspace_id, enabled, position
                );
            -- MULTICHANNEL_NOTIFICATIONS_V15_END

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

            CREATE TABLE IF NOT EXISTS storage_maintenance_plans (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                actor_user_id TEXT NOT NULL,
                operation TEXT NOT NULL
                    CHECK(operation IN ('cleanup', 'archive', 'restore', 'delete_archive')),
                status TEXT NOT NULL DEFAULT 'previewed'
                    CHECK(status IN ('previewed', 'applied', 'expired', 'failed')),
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                fingerprint TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                applied_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_storage_plans_workspace_created
                ON storage_maintenance_plans(workspace_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS storage_archive_batches (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                created_by_user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'committed'
                    CHECK(status IN ('committed', 'restored', 'failed', 'deleted')),
                cutoff_at TEXT NOT NULL,
                archive_path TEXT NOT NULL,
                checksum TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0 CHECK(item_count >= 0),
                media_count INTEGER NOT NULL DEFAULT 0 CHECK(media_count >= 0),
                byte_size INTEGER NOT NULL DEFAULT 0 CHECK(byte_size >= 0),
                manifest_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                restored_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_storage_archives_workspace_created
                ON storage_archive_batches(workspace_id, created_at DESC);
            """
        if not install_apify_actor_v13:
            before_v13, after_marker = schema_sql.split(
                "-- APIFY_ACTOR_ROUTING_V13_BEGIN",
                1,
            )
            _v13_sql, after_v13 = after_marker.split(
                "-- APIFY_ACTOR_ROUTING_V13_END",
                1,
            )
            schema_sql = before_v13 + after_v13
        if not install_multichannel_notifications_v15:
            before_v15, after_marker = schema_sql.split(
                "-- MULTICHANNEL_NOTIFICATIONS_V15_BEGIN",
                1,
            )
            _v15_sql, after_v15 = after_marker.split(
                "-- MULTICHANNEL_NOTIFICATIONS_V15_END",
                1,
            )
            schema_sql = before_v15 + after_v15
        conn.executescript(schema_sql)
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
        self._ensure_column("secret_refs", "version", "INTEGER NOT NULL DEFAULT 1")
        if install_apify_actor_v13:
            self._ensure_column(
                "apify_actor_runs",
                "charge_reserved_usd",
                "REAL NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                "apify_actor_runs",
                "charge_actual_usd",
                "REAL",
            )
            self._ensure_column(
                "apify_actor_runs",
                "charge_final",
                "INTEGER NOT NULL DEFAULT 0",
            )
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
        self._ensure_column(
            "user_subscriptions",
            "notify_on_new_items",
            "INTEGER NOT NULL DEFAULT 0",
        )
        self._ensure_column(
            "user_subscriptions",
            "notification_enabled_at",
            "TEXT",
        )
        self._ensure_column(
            "user_subscriptions",
            "notification_generation",
            "INTEGER NOT NULL DEFAULT 0",
        )
        self._ensure_column(
            "user_notification_settings",
            "notification_enabled_at",
            "TEXT",
        )
        self._ensure_column(
            "user_notification_settings",
            "notification_generation",
            "INTEGER NOT NULL DEFAULT 0",
        )
        self._ensure_column(
            "user_notification_settings",
            "webhook_secret_digest",
            "TEXT",
        )
        self._ensure_column(
            "user_notification_settings",
            "last_test_attempted_at",
            "TEXT",
        )
        if install_webhook_providers_v14:
            for table in (
                "user_notification_settings",
                "apify_actor_alert_settings",
            ):
                self._ensure_column(
                    table,
                    "webhook_provider",
                    "TEXT NOT NULL DEFAULT 'legacy_auto'",
                )
                self._ensure_column(
                    table,
                    "webhook_signing_env_name",
                    "TEXT",
                )
                self._ensure_column(
                    table,
                    "webhook_signing_secret_digest",
                    "TEXT",
                )
            self._ensure_webhook_provider_triggers()
        self._ensure_column(
            "preferred_source_notification_deliveries",
            "account_notification_generation",
            "INTEGER NOT NULL DEFAULT 0",
        )
        if install_multichannel_notifications_v15:
            self._ensure_column(
                "preferred_source_notification_deliveries",
                "channel_notification_generation",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                "apify_actor_alert_settings",
                "notification_enabled_at",
                "TEXT",
            )
            self._ensure_column(
                "apify_actor_alert_deliveries",
                "channel_generation",
                "INTEGER NOT NULL DEFAULT 1",
            )
        self._ensure_column(
            "preferred_source_notification_deliveries",
            "subscription_notification_generation",
            "INTEGER NOT NULL DEFAULT 0",
        )
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
            "user_content_items", "source_native_title", "TEXT"
        )
        self._ensure_column(
            "user_content_items", "unresolved_reason", "TEXT"
        )
        self._ensure_column(
            "user_content_items", "effective_at", "TEXT NOT NULL DEFAULT ''"
        )
        self._ensure_column(
            "user_content_items", "search_text", "TEXT NOT NULL DEFAULT ''"
        )
        self._ensure_column("user_content_items", "archive_batch_id", "TEXT")
        self._ensure_column("user_content_items", "archived_at", "TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_content_items_user_effective
            ON user_content_items(
                workspace_id, user_id, effective_at DESC, article_id ASC
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS user_content_search USING fts5(
                content_id UNINDEXED,
                workspace_id UNINDEXED,
                user_id UNINDEXED,
                article_id UNINDEXED,
                effective_at UNINDEXED,
                search_text,
                tokenize='trigram'
            )
            """
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
        self._seed_apify_key_pools(commit=False)
        self.mark_apify_key_pool_v8_migrated(commit=False)
        self.mark_preferred_source_notifications_v9_migrated(commit=False)
        self.mark_workspace_email_transports_v10_migrated(commit=False)
        timeline_v11_migrated = bool(
            conn.execute("SELECT 1 FROM schema_migrations WHERE version = 11").fetchone()
        )
        has_unmigrated_timeline_rows = bool(
            conn.execute(
                """
                SELECT 1 FROM user_content_items
                WHERE effective_at = '' OR search_text = ''
                LIMIT 1
                """
            ).fetchone()
        )
        if not has_unmigrated_timeline_rows and not timeline_v11_migrated:
            self.mark_content_timeline_v11_migrated(commit=False)
        self.mark_agent_source_resolutions_v12_migrated(commit=False)
        if install_apify_actor_v13:
            self._seed_apify_actor_routes(commit=False)
            if not apify_actor_v13_upgrade_pending:
                self.mark_apify_actor_routing_v13_migrated(commit=False)
        if (
            install_webhook_providers_v14
            and not webhook_providers_v14_upgrade_pending
        ):
            self.mark_webhook_providers_v14_migrated(commit=False)
        if (
            install_multichannel_notifications_v15
            and not multichannel_notifications_v15_upgrade_pending
        ):
            self.mark_multichannel_notifications_v15_migrated(commit=False)
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

    def mark_agent_source_resolutions_v12_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (
                version, name, checksum, applied_at
            ) VALUES (
                12,
                'agent_source_resolutions_v12',
                'agent-source-resolutions-v12',
                ?
            )
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def mark_apify_actor_routing_v13_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (
                version, name, checksum, applied_at
            ) VALUES (
                13,
                'apify_actor_routing_v13',
                'apify-actor-routing-alerts-v13',
                ?
            )
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def apify_actor_routing_v13_migration_required(self) -> bool:
        return not bool(
            self.connect().execute(
                "SELECT 1 FROM schema_migrations WHERE version = 13"
            ).fetchone()
        )

    def mark_webhook_providers_v14_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (
                version, name, checksum, applied_at
            ) VALUES (
                14,
                'webhook_providers_v14',
                'webhook-provider-presets-v14',
                ?
            )
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def webhook_providers_v14_migration_required(self) -> bool:
        conn = self.connect()
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 14"
        ).fetchone():
            return True
        required_columns = {
            "webhook_provider",
            "webhook_signing_env_name",
            "webhook_signing_secret_digest",
        }
        providers = ",".join("?" for _value in WEBHOOK_PROVIDERS)
        for table in (
            "user_notification_settings",
            "apify_actor_alert_settings",
        ):
            columns = {
                str(row["name"])
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            if not required_columns <= columns:
                return True
            invalid = conn.execute(
                f"""
                SELECT 1 FROM {table}
                WHERE webhook_provider NOT IN ({providers})
                   OR (
                        (webhook_signing_env_name IS NULL)
                        != (webhook_signing_secret_digest IS NULL)
                   )
                   OR (
                        webhook_signing_env_name IS NOT NULL
                        AND webhook_provider NOT IN (
                            'feishu_lark_v2', 'dingtalk'
                        )
                   )
                   OR (
                        webhook_signing_secret_digest IS NOT NULL
                        AND (
                            length(webhook_signing_secret_digest) != 64
                            OR webhook_signing_secret_digest
                                GLOB '*[^0-9a-f]*'
                        )
                   )
                LIMIT 1
                """,
                tuple(sorted(WEBHOOK_PROVIDERS)),
            ).fetchone()
            if invalid:
                return True
        installed_triggers = {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'trigger'
                """
            ).fetchall()
        }
        return not WEBHOOK_PROVIDER_TRIGGER_NAMES <= installed_triggers

    def mark_apify_key_pool_v8_migrated(self, *, commit: bool = True) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (8, 'apify_key_pool_v8', 'apify-key-pool-v8-safe-failover', ?)
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def mark_preferred_source_notifications_v9_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (
                9,
                'preferred_source_notifications_v9',
                'preferred-source-notifications-v9-outbox',
                ?
            )
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def mark_workspace_email_transports_v10_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (
                10,
                'workspace_email_transports_v10',
                'workspace-email-transports-v10-provider-registry',
                ?
            )
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def mark_content_timeline_v11_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR REPLACE INTO schema_migrations (
                version, name, checksum, applied_at
            ) VALUES (
                11,
                'content_timeline_v11',
                'content-timeline-v11-effective-search-archive',
                ?
            )
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def content_timeline_v11_migration_required(self) -> bool:
        migrated = self.connect().execute(
            "SELECT 1 FROM schema_migrations WHERE version = 11"
        ).fetchone()
        if migrated:
            return False
        return bool(
            self.connect().execute(
                """
                SELECT 1 FROM user_content_items
                WHERE effective_at = '' OR search_text = ''
                LIMIT 1
                """
            ).fetchone()
        )

    def mark_multichannel_notifications_v15_migrated(
        self, *, commit: bool = True
    ) -> None:
        self.connect().execute(
            """
            INSERT OR REPLACE INTO schema_migrations (
                version, name, checksum, applied_at
            ) VALUES (
                15,
                'multichannel_notifications_v15',
                'telegram-multichannel-notifications-v15',
                ?
            )
            """,
            (_now_iso(),),
        )
        if commit:
            self.connect().commit()

    def multichannel_notifications_v15_migration_required(self) -> bool:
        conn = self.connect()
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 15"
        ).fetchone():
            return True
        required_tables = {
            "user_notification_channels",
            "workspace_telegram_transports",
            "apify_actor_alert_channels",
        }
        installed_tables = {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
        if not required_tables <= installed_tables:
            return True
        required_delivery_columns = {
            "preferred_source_notification_deliveries": {
                "channel_notification_generation"
            },
            "apify_actor_alert_deliveries": {"channel_generation"},
            "apify_actor_alert_settings": {"notification_enabled_at"},
        }
        for table, required_columns in required_delivery_columns.items():
            columns = {
                str(row["name"])
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            if not required_columns <= columns:
                return True

        def unique_constraints(table: str) -> set[tuple[str, ...]]:
            constraints: set[tuple[str, ...]] = set()
            for index in conn.execute(
                f"PRAGMA index_list({table})"
            ).fetchall():
                if not bool(index["unique"]) or str(
                    index["origin"]
                ) == "pk":
                    continue
                columns = tuple(
                    str(column["name"])
                    for column in sorted(
                        conn.execute(
                            f"PRAGMA index_info({index['name']})"
                        ).fetchall(),
                        key=lambda column: int(column["seqno"]),
                    )
                )
                constraints.add(columns)
            return constraints

        required_unique_constraints = {
            "preferred_source_notification_deliveries": {
                ("subscription_id", "article_id", "channel")
            },
            "apify_actor_alert_deliveries": {
                ("incident_id", "event_type", "channel")
            },
        }
        for table, expected in required_unique_constraints.items():
            if unique_constraints(table) != expected:
                return True

        expected_primary_keys = {
            "user_notification_channels": ("user_id", "channel"),
            "workspace_telegram_transports": ("workspace_id",),
            "apify_actor_alert_channels": ("workspace_id", "channel"),
        }
        for table, expected in expected_primary_keys.items():
            primary_key = tuple(
                str(row["name"])
                for row in sorted(
                    (
                        row
                        for row in conn.execute(
                            f"PRAGMA table_info({table})"
                        ).fetchall()
                        if int(row["pk"]) > 0
                    ),
                    key=lambda row: int(row["pk"]),
                )
            )
            if primary_key != expected:
                return True

        required_table_checks = {
            "preferred_source_notification_deliveries": (
                "check(channelin('email','webhook','telegram'))",
            ),
            "user_notification_settings": (
                "check(channelin('email','webhook','telegram'))",
            ),
            "user_notification_channels": (
                "check(channelin('email','webhook','telegram'))",
                "check(enabledin(0,1))",
                "check(position>=0)",
                "check(generation>=0)",
                "check((destination_env_nameisnull)=(destination_secret_digestisnull))",
            ),
            "workspace_telegram_transports": (
                "check(enabledin(0,1))",
                "check(generation>=0)",
                "check((token_env_nameisnull)=(token_secret_digestisnull))",
            ),
            "apify_actor_alert_channels": (
                "check(channelin('email','webhook','telegram'))",
                "check(enabledin(0,1))",
                "check(position>=0)",
                "check(generation>=1)",
                "check((destination_env_nameisnull)=(destination_secret_digestisnull))",
            ),
            "apify_actor_alert_settings": (
                "check(channelin('email','webhook','telegram'))",
            ),
            "apify_actor_alert_deliveries": (
                "check(channelin('email','webhook','telegram'))",
            ),
        }
        for table, required_checks in required_table_checks.items():
            definition = conn.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (table,),
            ).fetchone()
            normalized_sql = re.sub(
                r"\s+",
                "",
                str(definition["sql"] if definition else "").lower(),
            )
            if any(
                required not in normalized_sql
                for required in required_checks
            ):
                return True

        placeholders = ",".join("?" for _value in NOTIFICATION_CHANNELS)
        for table in (
            "user_notification_channels",
            "apify_actor_alert_channels",
        ):
            invalid = conn.execute(
                f"""
                SELECT 1 FROM {table}
                WHERE channel NOT IN ({placeholders})
                   OR enabled NOT IN (0, 1)
                   OR position < 0
                   OR (
                        (destination_env_name IS NULL)
                        != (destination_secret_digest IS NULL)
                   )
                   OR (
                        destination_secret_digest IS NOT NULL
                        AND (
                            length(destination_secret_digest) != 64
                            OR destination_secret_digest GLOB '*[^0-9a-f]*'
                        )
                   )
                LIMIT 1
                """,
                NOTIFICATION_CHANNELS,
            ).fetchone()
            if invalid:
                return True
        for table in (
            "preferred_source_notification_deliveries",
            "apify_actor_alert_deliveries",
        ):
            if conn.execute(
                f"""
                SELECT 1 FROM {table}
                WHERE channel NOT IN ({placeholders})
                LIMIT 1
                """,
                NOTIFICATION_CHANNELS,
            ).fetchone():
                return True
        return False

    def _seed_apify_key_pools(self, *, commit: bool = True) -> None:
        """Idempotently seed workspace pools from existing Apify secret refs."""

        conn = self.connect()
        now = _now_iso()
        workspace_rows = conn.execute(
            "SELECT id FROM workspaces ORDER BY created_at, id"
        ).fetchall()
        for workspace_row in workspace_rows:
            workspace_id = str(workspace_row["id"])
            discovered_refs = conn.execute(
                """
                SELECT
                    secret.id,
                    secret.created_at,
                    COUNT(source.id) AS enabled_reference_count
                FROM secret_refs AS secret
                LEFT JOIN source_catalog AS source
                  ON source.workspace_id = secret.workspace_id
                 AND source.secret_env = secret.env_name
                 AND source.type = 'apify_social'
                 AND source.enabled = 1
                WHERE secret.workspace_id = ?
                  AND (
                    lower(secret.provider) = 'apify'
                    OR lower(secret.kind) = 'apify'
                )
                GROUP BY secret.id, secret.created_at
                """,
                (workspace_id,),
            ).fetchall()
            refs: list[sqlite3.Row] = []
            if discovered_refs:
                primary = min(
                    discovered_refs,
                    key=lambda row: (
                        -int(row["enabled_reference_count"]),
                        str(row["created_at"]),
                        str(row["id"]),
                    ),
                )
                refs = [
                    primary,
                    *sorted(
                        (
                            row
                            for row in discovered_refs
                            if str(row["id"]) != str(primary["id"])
                        ),
                        key=lambda row: (
                            str(row["created_at"]),
                            str(row["id"]),
                        ),
                    ),
                ]
            state = conn.execute(
                "SELECT * FROM apify_key_pool_state WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            if state is None:
                primary_id = str(refs[0]["id"]) if refs else None
                conn.execute(
                    """
                    INSERT INTO apify_key_pool_state (
                        workspace_id, generation, status, active_secret_id,
                        created_at, updated_at
                    ) VALUES (?, 1, ?, ?, ?, ?)
                    """,
                    (
                        workspace_id,
                        "ready" if primary_id else "empty",
                        primary_id,
                        now,
                        now,
                    ),
                )
                state = conn.execute(
                    "SELECT * FROM apify_key_pool_state WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()

            existing_rows = conn.execute(
                """
                SELECT secret_id, position, status
                FROM apify_key_pool_members
                WHERE workspace_id = ?
                ORDER BY position
                """,
                (workspace_id,),
            ).fetchall()
            existing_ids = {str(row["secret_id"]) for row in existing_rows}
            next_position = (
                max(int(row["position"]) for row in existing_rows) + 1
                if existing_rows
                else 0
            )
            active_secret_id = (
                str(state["active_secret_id"])
                if state is not None and state["active_secret_id"]
                else None
            )
            seed_primary_id = (
                str(refs[0]["id"])
                if refs
                and not existing_rows
                and state is not None
                and state["status"] in {"empty", "exhausted"}
                and active_secret_id is None
                else None
            )
            for ref in refs:
                secret_id = str(ref["id"])
                if secret_id in existing_ids:
                    continue
                status = (
                    "active"
                    if not existing_rows
                    and (active_secret_id == secret_id or seed_primary_id == secret_id)
                    and state is not None
                    and state["status"] in {"ready", "empty", "exhausted"}
                    else "standby"
                )
                conn.execute(
                    """
                    INSERT INTO apify_key_pool_members (
                        workspace_id, secret_id, position, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (workspace_id, secret_id, next_position, status, now, now),
                )
                existing_ids.add(secret_id)
                existing_rows = [*existing_rows, {"position": next_position}]
                next_position += 1

            if state is None or state["status"] in {"draining", "blocked"}:
                continue
            active = conn.execute(
                """
                SELECT secret_id
                FROM apify_key_pool_members
                WHERE workspace_id = ? AND status = 'active'
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            if active is not None:
                conn.execute(
                    """
                    UPDATE apify_key_pool_state
                    SET status = 'ready', active_secret_id = ?,
                        blocked_reason = NULL, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (active["secret_id"], now, workspace_id),
                )
                continue
            candidate = conn.execute(
                """
                SELECT secret_id
                FROM apify_key_pool_members
                WHERE workspace_id = ? AND status = 'standby'
                ORDER BY position
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            if candidate is not None:
                conn.execute(
                    """
                    UPDATE apify_key_pool_members
                    SET status = 'active', updated_at = ?
                    WHERE workspace_id = ? AND secret_id = ?
                    """,
                    (now, workspace_id, candidate["secret_id"]),
                )
                conn.execute(
                    """
                    UPDATE apify_key_pool_state
                    SET status = 'ready', active_secret_id = ?,
                        generation = generation + 1,
                        blocked_reason = NULL, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (candidate["secret_id"], now, workspace_id),
                )
            else:
                member_exists = conn.execute(
                    """
                    SELECT 1 FROM apify_key_pool_members
                    WHERE workspace_id = ? LIMIT 1
                    """,
                    (workspace_id,),
                ).fetchone()
                conn.execute(
                    """
                    UPDATE apify_key_pool_state
                    SET status = ?, active_secret_id = NULL, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    ("exhausted" if member_exists else "empty", now, workspace_id),
                )
        if commit:
            conn.commit()

    def _seed_apify_actor_routes(self, *, commit: bool = True) -> None:
        """Idempotently seed the Apify-only X profile route for each workspace."""

        conn = self.connect()
        now = _now_iso()
        retry_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        seeds = (
            (
                "scrape_badger",
                "scrape.badger/twitter-tweets-scraper",
                "ScrapeBadger",
                0,
                "closed",
            ),
            (
                "dami",
                "dami_studio/tweet-scraper",
                "Dami",
                1,
                "disabled",
            ),
            (
                "xquik",
                "xquik/x-tweet-scraper",
                "Xquik",
                2,
                "open",
            ),
        )
        for workspace_row in conn.execute(
            "SELECT id FROM workspaces ORDER BY created_at, id"
        ).fetchall():
            workspace_id = str(workspace_row["id"])
            candidate_ids = {
                adapter_key: "apify-candidate-"
                + hashlib.sha256(
                    f"{workspace_id}:x/profile:{adapter_key}".encode("utf-8")
                ).hexdigest()[:24]
                for adapter_key, *_rest in seeds
            }
            conn.execute(
                """
                INSERT OR IGNORE INTO apify_actor_routes (
                    workspace_id, route_key, generation, status,
                    active_candidate_id, last_switch_reason, last_switch_at,
                    created_at, updated_at
                ) VALUES (?, 'x/profile', 1, 'degraded', ?, 'initial_policy', ?, ?, ?)
                """,
                (
                    workspace_id,
                    candidate_ids["scrape_badger"],
                    now,
                    now,
                    now,
                ),
            )
            for (
                adapter_key,
                actor_id,
                display_name,
                position,
                state,
            ) in seeds:
                is_xquik = adapter_key == "xquik"
                is_dami = adapter_key == "dami"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO apify_actor_candidates (
                        id, workspace_id, route_key, actor_id, adapter_key,
                        display_name, position, state, failure_level,
                        opened_at, retry_at, probation_started_at,
                        last_failure_at, last_error_code, created_at, updated_at
                    ) VALUES (
                        ?, ?, 'x/profile', ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        candidate_ids[adapter_key],
                        workspace_id,
                        actor_id,
                        adapter_key,
                        display_name,
                        position,
                        state,
                        1 if is_xquik else 0,
                        now if is_xquik else None,
                        retry_at if is_xquik else None,
                        None,
                        now if is_xquik else None,
                        (
                            "placeholder_record"
                            if is_xquik
                            else "canary_required" if is_dami else None
                        ),
                        now,
                        now,
                    ),
                )
        if commit:
            conn.commit()

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

    def _ensure_webhook_provider_triggers(self) -> None:
        """Keep migrated and newly-created settings tables equally strict."""

        conn = self.connect()
        providers = ", ".join(
            f"'{provider}'" for provider in sorted(WEBHOOK_PROVIDERS)
        )
        for table in (
            "user_notification_settings",
            "apify_actor_alert_settings",
        ):
            for operation in ("INSERT", "UPDATE"):
                trigger_name = (
                    f"trg_{table}_webhook_v14_{operation.lower()}"
                )
                conn.execute(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS {trigger_name}
                    BEFORE {operation} ON {table}
                    FOR EACH ROW
                    WHEN
                        NEW.webhook_provider NOT IN ({providers})
                        OR (
                            (NEW.webhook_signing_env_name IS NULL)
                            != (
                                NEW.webhook_signing_secret_digest IS NULL
                            )
                        )
                        OR (
                            NEW.webhook_signing_env_name IS NOT NULL
                            AND NEW.webhook_provider NOT IN (
                                'feishu_lark_v2', 'dingtalk'
                            )
                        )
                        OR (
                            NEW.webhook_signing_secret_digest IS NOT NULL
                            AND (
                                length(
                                    NEW.webhook_signing_secret_digest
                                ) != 64
                                OR NEW.webhook_signing_secret_digest
                                    GLOB '*[^0-9a-f]*'
                            )
                        )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'invalid webhook provider settings'
                        );
                    END
                    """
                )

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
            "diagnostics_scope": _diagnostics_scope_for_scopes(scopes),
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
    def _agent_source_resolution(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["envelope"] = _json_loads(data.pop("envelope_json", None), {})
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
        data["notify_on_new_items"] = _bool(data.get("notify_on_new_items"))
        data.pop("notification_generation", None)
        data["override_topics"] = _json_loads(data.pop("override_topics_json", None), [])
        data["personal_tags"] = _json_loads(data.pop("personal_tags_json", None), [])
        return data

    @staticmethod
    def _notification_settings(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        data["notification_generation"] = int(
            data.get("notification_generation") or 0
        )
        return data

    @staticmethod
    def _notification_channel(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        data["position"] = max(0, int(data.get("position") or 0))
        data["generation"] = max(0, int(data.get("generation") or 0))
        if data.get("last_test_generation") is not None:
            data["last_test_generation"] = int(
                data["last_test_generation"]
            )
        return data

    @staticmethod
    def _workspace_email_transport(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        data["generation"] = int(data.get("generation") or 0)
        if data.get("last_test_generation") is not None:
            data["last_test_generation"] = int(
                data["last_test_generation"]
            )
        return data

    @staticmethod
    def _workspace_telegram_transport(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = _bool(data.get("enabled"))
        data["generation"] = max(0, int(data.get("generation") or 0))
        if data.get("last_test_generation") is not None:
            data["last_test_generation"] = int(
                data["last_test_generation"]
            )
        return data

    @staticmethod
    def _preferred_source_notification_delivery(
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["attempts"] = int(data.get("attempts") or 0)
        data["account_notification_generation"] = int(
            data.get("account_notification_generation") or 0
        )
        data["channel_notification_generation"] = int(
            data.get("channel_notification_generation") or 0
        )
        data["subscription_notification_generation"] = int(
            data.get("subscription_notification_generation") or 0
        )
        data["payload"] = _json_loads(data.pop("payload_json", None), {})
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
                    UPDATE user_notification_settings
                    SET enabled = 0,
                        notification_enabled_at = NULL,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (now, user_id),
                )
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
        diagnostics_scope: str = "self",
    ) -> tuple[dict[str, Any], str]:
        scopes = _scopes_for_access(
            access,
            diagnostics_scope=diagnostics_scope,
        )
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
            if (
                diagnostics_scope == "workspace"
                and user["role"] not in {"owner", "admin"}
            ):
                raise PermissionError(
                    "workspace diagnostics require owner or admin role"
                )
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

    def delete_revoked_agent_delegation(
        self,
        user_id: str,
        delegation_id: str,
    ) -> bool | None:
        conn = self.connect()
        owned = conn.execute(
            """
            SELECT revoked_at
            FROM agent_delegations
            WHERE id = ? AND user_id = ?
            """,
            (delegation_id, user_id),
        ).fetchone()
        if owned is None:
            return None
        if owned["revoked_at"] is None:
            return False
        cursor = conn.execute(
            """
            DELETE FROM agent_delegations
            WHERE id = ? AND user_id = ? AND revoked_at IS NOT NULL
            """,
            (delegation_id, user_id),
        )
        conn.commit()
        return True if cursor.rowcount else None

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

    def create_or_reuse_agent_source_resolution(
        self,
        *,
        workspace_id: str,
        user_id: str,
        delegation_id: str,
        source_type: str,
        source_fingerprint: str,
        envelope: dict[str, Any],
        commit: bool = True,
    ) -> dict[str, Any]:
        """Persist one short-lived, actor-bound source envelope idempotently."""

        normalized_type = str(source_type or "").strip()
        normalized_fingerprint = str(source_fingerprint or "").strip().lower()
        if not normalized_type or len(normalized_type) > 64:
            raise ValueError("source resolution type is invalid")
        if re.fullmatch(r"[0-9a-f]{64}", normalized_fingerprint) is None:
            raise ValueError("source resolution fingerprint is invalid")
        if not isinstance(envelope, dict):
            raise ValueError("source resolution envelope must be an object")
        _require_safe_proposal_data(envelope)
        serialized_envelope = _json_dumps(envelope)
        if (
            len(serialized_envelope.encode("utf-8"))
            > AGENT_SOURCE_RESOLUTION_ENVELOPE_MAX_BYTES
        ):
            raise ValueError("source resolution envelope is too large")

        conn = self.connect()
        started_transaction = bool(commit and not conn.in_transaction)
        try:
            if started_transaction:
                conn.execute("BEGIN IMMEDIATE")
            authoritative_now = _authoritative_proposal_time()
            now_iso = authoritative_now.isoformat()
            principal = conn.execute(
                """
                SELECT delegation.scopes_json
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
                (delegation_id, workspace_id, user_id, now_iso),
            ).fetchone()
            if (
                principal is None
                or AGENT_DELEGATION_READ_SCOPE
                not in _safe_agent_delegation_scopes(principal["scopes_json"])
            ):
                raise AgentSourceResolutionAuthorizationError(
                    "agent source resolution delegation is not authorized"
                )

            existing_row = conn.execute(
                """
                SELECT * FROM agent_source_resolutions
                WHERE workspace_id = ?
                  AND user_id = ?
                  AND delegation_id = ?
                  AND source_fingerprint = ?
                  AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    workspace_id,
                    user_id,
                    delegation_id,
                    normalized_fingerprint,
                    now_iso,
                ),
            ).fetchone()
            existing = self._agent_source_resolution(existing_row)
            if existing is not None:
                if existing.get("source_type") != normalized_type:
                    raise ValueError("source resolution fingerprint collision")
                if existing.get("envelope") != envelope:
                    conn.execute(
                        """
                        UPDATE agent_source_resolutions
                        SET envelope_json = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (serialized_envelope, now_iso, existing["id"]),
                    )
                    existing_row = conn.execute(
                        """
                        SELECT * FROM agent_source_resolutions
                        WHERE id = ?
                        """,
                        (existing["id"],),
                    ).fetchone()
                    existing = self._agent_source_resolution(existing_row)
                if started_transaction:
                    conn.commit()
                if existing is None:
                    raise LookupError("source resolution not found")
                return existing

            active_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM agent_source_resolutions
                    WHERE delegation_id = ? AND expires_at > ?
                    """,
                    (delegation_id, now_iso),
                ).fetchone()[0]
            )
            if active_count >= AGENT_SOURCE_RESOLUTION_MAX_ACTIVE:
                raise AgentSourceResolutionLimitError(
                    "agent source resolution active limit reached"
                )

            resolution_id = _new_id("asr")
            expires_iso = (
                authoritative_now
                + timedelta(minutes=AGENT_SOURCE_RESOLUTION_TTL_MINUTES)
            ).isoformat()
            conn.execute(
                """
                INSERT INTO agent_source_resolutions (
                    id, workspace_id, user_id, delegation_id, source_type,
                    source_fingerprint, envelope_json, created_at, expires_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution_id,
                    workspace_id,
                    user_id,
                    delegation_id,
                    normalized_type,
                    normalized_fingerprint,
                    serialized_envelope,
                    now_iso,
                    expires_iso,
                    now_iso,
                ),
            )
            created_row = conn.execute(
                "SELECT * FROM agent_source_resolutions WHERE id = ?",
                (resolution_id,),
            ).fetchone()
            if started_transaction:
                conn.commit()
        except Exception:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            raise
        created = self._agent_source_resolution(created_row)
        if created is None:
            raise LookupError("created source resolution not found")
        return created

    def get_agent_source_resolution_for_actor(
        self,
        resolution_id: str,
        *,
        workspace_id: str,
        user_id: str,
        delegation_id: str,
    ) -> dict[str, Any] | None:
        """Return a resolution only when all persisted actor bindings match."""

        row = self.connect().execute(
            """
            SELECT * FROM agent_source_resolutions
            WHERE id = ?
              AND workspace_id = ?
              AND user_id = ?
              AND delegation_id = ?
            """,
            (resolution_id, workspace_id, user_id, delegation_id),
        ).fetchone()
        return self._agent_source_resolution(row)

    def cleanup_agent_source_resolutions(
        self,
        *,
        now: str,
        delegation_id: str | None = None,
        commit: bool = True,
    ) -> dict[str, int]:
        current = _parse_proposal_time(now)
        cutoff = (
            current - timedelta(hours=AGENT_SOURCE_RESOLUTION_RETENTION_HOURS)
        ).isoformat()
        conn = self.connect()
        started_transaction = bool(commit and not conn.in_transaction)
        try:
            if started_transaction:
                conn.execute("BEGIN IMMEDIATE")
            sql = "DELETE FROM agent_source_resolutions WHERE expires_at < ?"
            parameters: list[Any] = [cutoff]
            if delegation_id is not None:
                sql += " AND delegation_id = ?"
                parameters.append(delegation_id)
            deleted = conn.execute(sql, parameters).rowcount
            if started_transaction:
                conn.commit()
        except Exception:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return {"deleted": max(int(deleted), 0)}

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

    def get_workspace_email_transport(
        self,
        *,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        row = self.connect().execute(
            """
            SELECT *
            FROM workspace_email_transports
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        return self._workspace_email_transport(row)

    def upsert_workspace_email_transport(
        self,
        *,
        workspace_id: str,
        provider: str,
        sender_email: str,
        sender_name: str,
        region: str | None,
        smtp_username: str | None,
        enabled: bool,
        credential_env_name: str | None,
        credential_secret_digest: str | None,
        generation: int,
        last_test_status: str | None,
        last_test_generation: int | None,
        last_test_attempted_at: str | None,
        last_tested_at: str | None,
        last_test_error_code: str | None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if provider not in {
            "qq",
            "netease",
            "gmail",
            "resend",
            "amazon_ses",
        }:
            raise ValueError("unsupported email provider")
        if last_test_status not in {None, "sent", "failed"}:
            raise ValueError("email transport test status is invalid")
        if bool(credential_env_name) != bool(credential_secret_digest):
            raise ValueError(
                "email transport credential environment and digest must be configured together"
            )
        if credential_secret_digest and not re.fullmatch(
            r"[0-9a-f]{64}",
            credential_secret_digest,
        ):
            raise ValueError(
                "email transport credential digest must be a SHA-256 value"
            )
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO workspace_email_transports (
                    workspace_id, provider, sender_email, sender_name, region,
                    smtp_username, enabled, credential_env_name,
                    credential_secret_digest, generation, last_test_status,
                    last_test_generation, last_test_attempted_at,
                    last_tested_at, last_test_error_code, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(workspace_id) DO UPDATE SET
                    provider = excluded.provider,
                    sender_email = excluded.sender_email,
                    sender_name = excluded.sender_name,
                    region = excluded.region,
                    smtp_username = excluded.smtp_username,
                    enabled = excluded.enabled,
                    credential_env_name = excluded.credential_env_name,
                    credential_secret_digest = excluded.credential_secret_digest,
                    generation = excluded.generation,
                    last_test_status = excluded.last_test_status,
                    last_test_generation = excluded.last_test_generation,
                    last_test_attempted_at = excluded.last_test_attempted_at,
                    last_tested_at = excluded.last_tested_at,
                    last_test_error_code = excluded.last_test_error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    workspace_id,
                    provider,
                    sender_email,
                    sender_name,
                    region,
                    smtp_username,
                    1 if enabled else 0,
                    credential_env_name,
                    credential_secret_digest,
                    max(0, int(generation)),
                    last_test_status,
                    last_test_generation,
                    last_test_attempted_at,
                    last_tested_at,
                    last_test_error_code,
                    now,
                    now,
                ),
            )
            updated = self.get_workspace_email_transport(
                workspace_id=workspace_id
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated is None:
            raise LookupError(
                "workspace email transport not found after update"
            )
        return updated

    def delete_workspace_email_transport(
        self,
        *,
        workspace_id: str,
        commit: bool = True,
    ) -> bool:
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            deleted = conn.execute(
                """
                DELETE FROM workspace_email_transports
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return deleted.rowcount == 1

    def invalidate_pending_email_deliveries(
        self,
        *,
        workspace_id: str,
        error_code: str = "notification_transport_changed",
        commit: bool = True,
    ) -> int:
        if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", error_code):
            raise ValueError("notification delivery error code is invalid")
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = _now_iso()
            updated = conn.execute(
                """
                UPDATE preferred_source_notification_deliveries
                SET status = 'failed',
                    error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ?
                  AND channel = 'email'
                  AND status = 'pending'
                """,
                (error_code, now, workspace_id),
            )
            actor_alerts_updated = conn.execute(
                """
                UPDATE apify_actor_alert_deliveries
                SET status = 'failed',
                    error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ?
                  AND channel = 'email'
                  AND status = 'pending'
                """,
                (error_code, now, workspace_id),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return max(int(updated.rowcount), 0) + max(
            int(actor_alerts_updated.rowcount),
            0,
        )

    def claim_workspace_email_transport_test_attempt(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        cooldown_seconds: int = 60,
        attempted_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically authorize and reserve a workspace SMTP test window."""

        conn = self.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "email transport test attempt requires no active transaction"
            )
        cooldown = max(1, int(cooldown_seconds))
        try:
            now = (
                datetime.fromisoformat(
                    str(attempted_at).replace("Z", "+00:00")
                )
                if attempted_at
                else datetime.now(timezone.utc)
            )
        except ValueError as exc:
            raise ValueError(
                "email transport test attempt timestamp must be ISO 8601"
            ) from exc
        if now.tzinfo is None:
            raise ValueError(
                "email transport test attempt timestamp must include a timezone"
            )
        now = now.astimezone(timezone.utc)
        try:
            conn.execute("BEGIN IMMEDIATE")
            actor = self.get_user(actor_user_id)
            if (
                actor is None
                or not bool(actor.get("enabled"))
                or str(actor.get("workspace_id")) != str(workspace_id)
                or str(actor.get("role") or "") not in {"owner", "admin"}
            ):
                conn.commit()
                return {
                    "claimed": False,
                    "reason": "forbidden",
                    "retry_after_seconds": 0,
                    "transport": None,
                }
            current = self.get_workspace_email_transport(
                workspace_id=workspace_id
            )
            if current is None:
                conn.commit()
                return {
                    "claimed": False,
                    "reason": "not_configured",
                    "retry_after_seconds": 0,
                    "transport": None,
                }
            previous_value = current.get("last_test_attempted_at")
            elapsed: float | None = None
            if previous_value:
                try:
                    previous = datetime.fromisoformat(
                        str(previous_value).replace("Z", "+00:00")
                    )
                except ValueError:
                    previous = None
                if previous is not None and previous.tzinfo is not None:
                    elapsed = (
                        now - previous.astimezone(timezone.utc)
                    ).total_seconds()
            if elapsed is not None and elapsed < cooldown:
                conn.commit()
                return {
                    "claimed": False,
                    "reason": "rate_limited",
                    "retry_after_seconds": max(
                        1,
                        int(math.ceil(cooldown - elapsed)),
                    ),
                    "transport": current,
                }
            attempted_at_iso = now.isoformat()
            conn.execute(
                """
                UPDATE workspace_email_transports
                SET last_test_attempted_at = ?,
                    updated_at = ?
                WHERE workspace_id = ?
                """,
                (attempted_at_iso, attempted_at_iso, workspace_id),
            )
            claimed = self.get_workspace_email_transport(
                workspace_id=workspace_id
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        if claimed is None:
            raise LookupError(
                "workspace email transport not found after test claim"
            )
        return {
            "claimed": True,
            "reason": None,
            "retry_after_seconds": 0,
            "transport": claimed,
        }

    def record_workspace_email_transport_test(
        self,
        *,
        workspace_id: str,
        generation: int,
        status: str,
        error_code: str | None = None,
        tested_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Record a test only if it still targets the current generation."""

        if status not in {"sent", "failed"}:
            raise ValueError("email transport test status is invalid")
        conn = self.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = tested_at or _now_iso()
            conn.execute(
                """
                UPDATE workspace_email_transports
                SET last_test_status = ?,
                    last_test_generation = ?,
                    last_tested_at = ?,
                    last_test_error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND generation = ?
                """,
                (
                    status,
                    int(generation),
                    now,
                    error_code if status == "failed" else None,
                    now,
                    workspace_id,
                    int(generation),
                ),
            )
            updated = self.get_workspace_email_transport(
                workspace_id=workspace_id
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if (
            updated is None
            or int(updated.get("generation") or 0) != int(generation)
        ):
            return None
        return updated

    def get_workspace_telegram_transport(
        self,
        *,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        row = self.connect().execute(
            """
            SELECT * FROM workspace_telegram_transports
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        return self._workspace_telegram_transport(row)

    def upsert_workspace_telegram_transport(
        self,
        *,
        workspace_id: str,
        enabled: bool,
        token_env_name: str | None,
        token_secret_digest: str | None,
        generation: int,
        last_test_status: str | None,
        last_test_generation: int | None,
        last_test_attempted_at: str | None,
        last_tested_at: str | None,
        last_test_error_code: str | None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if bool(token_env_name) != bool(token_secret_digest):
            raise ValueError(
                "Telegram token environment and digest must be configured together"
            )
        if token_secret_digest and not re.fullmatch(
            r"[0-9a-f]{64}", token_secret_digest
        ):
            raise ValueError("Telegram token digest must be a SHA-256 value")
        if last_test_status not in {None, "sent", "failed"}:
            raise ValueError("Telegram transport test status is invalid")
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO workspace_telegram_transports (
                    workspace_id, enabled, token_env_name,
                    token_secret_digest, generation, last_test_status,
                    last_test_generation, last_test_attempted_at,
                    last_tested_at, last_test_error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    token_env_name = excluded.token_env_name,
                    token_secret_digest = excluded.token_secret_digest,
                    generation = excluded.generation,
                    last_test_status = excluded.last_test_status,
                    last_test_generation = excluded.last_test_generation,
                    last_test_attempted_at =
                        excluded.last_test_attempted_at,
                    last_tested_at = excluded.last_tested_at,
                    last_test_error_code = excluded.last_test_error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    workspace_id,
                    1 if enabled else 0,
                    token_env_name,
                    token_secret_digest,
                    max(0, int(generation)),
                    last_test_status,
                    last_test_generation,
                    last_test_attempted_at,
                    last_tested_at,
                    last_test_error_code,
                    now,
                    now,
                ),
            )
            updated = self.get_workspace_telegram_transport(
                workspace_id=workspace_id
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated is None:
            raise LookupError(
                "workspace Telegram transport not found after update"
            )
        return updated

    def delete_workspace_telegram_transport(
        self,
        *,
        workspace_id: str,
        commit: bool = True,
    ) -> bool:
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            deleted = conn.execute(
                """
                DELETE FROM workspace_telegram_transports
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return deleted.rowcount == 1

    def invalidate_notification_channel_deliveries(
        self,
        *,
        workspace_id: str,
        channel: str,
        error_code: str = "notification_transport_changed",
        commit: bool = True,
    ) -> int:
        if channel not in NOTIFICATION_CHANNEL_SET:
            raise ValueError("notification channel is invalid")
        if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", error_code):
            raise ValueError("notification delivery error code is invalid")
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = _now_iso()
            updated = conn.execute(
                """
                UPDATE preferred_source_notification_deliveries
                SET status = 'failed', error_code = ?, updated_at = ?
                WHERE workspace_id = ? AND channel = ?
                  AND status = 'pending'
                """,
                (error_code, now, workspace_id, channel),
            )
            alerts = conn.execute(
                """
                UPDATE apify_actor_alert_deliveries
                SET status = 'failed', error_code = ?, retry_at = NULL,
                    updated_at = ?
                WHERE workspace_id = ? AND channel = ?
                  AND status = 'pending'
                """,
                (error_code, now, workspace_id, channel),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return max(0, int(updated.rowcount)) + max(
            0, int(alerts.rowcount)
        )

    def advance_notification_channel_watermarks(
        self,
        *,
        workspace_id: str,
        channel: str,
        enabled_at: str | None = None,
        commit: bool = True,
    ) -> int:
        """Prevent transport restoration from staging historical content."""

        if channel not in NOTIFICATION_CHANNEL_SET:
            raise ValueError("notification channel is invalid")
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = enabled_at or _now_iso()
            users = conn.execute(
                """
                UPDATE user_notification_channels
                SET enabled_at = ?, updated_at = ?
                WHERE workspace_id = ? AND channel = ? AND enabled = 1
                """,
                (now, now, workspace_id, channel),
            )
            alerts = conn.execute(
                """
                UPDATE apify_actor_alert_channels
                SET enabled_at = ?, updated_at = ?
                WHERE workspace_id = ? AND channel = ? AND enabled = 1
                """,
                (now, now, workspace_id, channel),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return max(0, int(users.rowcount)) + max(
            0, int(alerts.rowcount)
        )

    def claim_workspace_telegram_transport_test_attempt(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        cooldown_seconds: int = 60,
        attempted_at: str | None = None,
    ) -> dict[str, Any]:
        conn = self.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "Telegram transport test attempt requires no active transaction"
            )
        now = (
            datetime.fromisoformat(
                str(attempted_at).replace("Z", "+00:00")
            )
            if attempted_at
            else datetime.now(timezone.utc)
        )
        if now.tzinfo is None:
            raise ValueError(
                "Telegram transport test timestamp must include a timezone"
            )
        now = now.astimezone(timezone.utc)
        try:
            conn.execute("BEGIN IMMEDIATE")
            actor = self.get_user(actor_user_id)
            if (
                actor is None
                or not bool(actor.get("enabled"))
                or str(actor.get("workspace_id")) != str(workspace_id)
                or str(actor.get("role") or "") not in {"owner", "admin"}
            ):
                conn.commit()
                return {
                    "claimed": False,
                    "reason": "forbidden",
                    "retry_after_seconds": 0,
                    "transport": None,
                }
            current = self.get_workspace_telegram_transport(
                workspace_id=workspace_id
            )
            if current is None:
                conn.commit()
                return {
                    "claimed": False,
                    "reason": "not_configured",
                    "retry_after_seconds": 0,
                    "transport": None,
                }
            previous = None
            if current.get("last_test_attempted_at"):
                try:
                    previous = datetime.fromisoformat(
                        str(current["last_test_attempted_at"]).replace(
                            "Z", "+00:00"
                        )
                    )
                except ValueError:
                    previous = None
            if previous is not None and previous.tzinfo is not None:
                elapsed = (
                    now - previous.astimezone(timezone.utc)
                ).total_seconds()
                if elapsed < max(1, int(cooldown_seconds)):
                    conn.commit()
                    return {
                        "claimed": False,
                        "reason": "rate_limited",
                        "retry_after_seconds": max(
                            1,
                            int(
                                math.ceil(
                                    max(1, int(cooldown_seconds)) - elapsed
                                )
                            ),
                        ),
                        "transport": current,
                    }
            attempted = now.isoformat()
            conn.execute(
                """
                UPDATE workspace_telegram_transports
                SET last_test_attempted_at = ?, updated_at = ?
                WHERE workspace_id = ?
                """,
                (attempted, attempted, workspace_id),
            )
            claimed = self.get_workspace_telegram_transport(
                workspace_id=workspace_id
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return {
            "claimed": True,
            "reason": None,
            "retry_after_seconds": 0,
            "transport": claimed,
        }

    def record_workspace_telegram_transport_test(
        self,
        *,
        workspace_id: str,
        generation: int,
        status: str,
        error_code: str | None = None,
        tested_at: str | None = None,
    ) -> dict[str, Any] | None:
        if status not in {"sent", "failed"}:
            raise ValueError("Telegram transport test status is invalid")
        conn = self.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = tested_at or _now_iso()
            updated = conn.execute(
                """
                UPDATE workspace_telegram_transports
                SET last_test_status = ?, last_test_generation = ?,
                    last_tested_at = ?, last_test_error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND generation = ?
                """,
                (
                    status,
                    int(generation),
                    now,
                    error_code if status == "failed" else None,
                    now,
                    workspace_id,
                    int(generation),
                ),
            )
            transport = self.get_workspace_telegram_transport(
                workspace_id=workspace_id
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated.rowcount != 1:
            return None
        return transport

    def list_user_notification_channels(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT * FROM user_notification_channels
            WHERE workspace_id = ? AND user_id = ?
            ORDER BY position, channel
            """,
            (workspace_id, user_id),
        ).fetchall()
        return [
            channel
            for row in rows
            if (channel := self._notification_channel(row)) is not None
        ]

    def get_user_notification_channel(
        self,
        *,
        workspace_id: str,
        user_id: str,
        channel: str,
    ) -> dict[str, Any] | None:
        if channel not in NOTIFICATION_CHANNEL_SET:
            return None
        row = self.connect().execute(
            """
            SELECT * FROM user_notification_channels
            WHERE workspace_id = ? AND user_id = ? AND channel = ?
            """,
            (workspace_id, user_id, channel),
        ).fetchone()
        return self._notification_channel(row)

    def upsert_user_notification_channel(
        self,
        *,
        workspace_id: str,
        user_id: str,
        channel: str,
        position: int,
        enabled: bool,
        enabled_at: str | None,
        generation: int,
        destination_env_name: str | None = None,
        destination_secret_digest: str | None = None,
        last_test_status: str | None = None,
        last_test_generation: int | None = None,
        last_test_attempted_at: str | None = None,
        last_tested_at: str | None = None,
        last_test_error_code: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if channel not in NOTIFICATION_CHANNEL_SET:
            raise ValueError("notification channel is invalid")
        if bool(destination_env_name) != bool(destination_secret_digest):
            raise ValueError(
                "notification destination environment and digest must be configured together"
            )
        if destination_secret_digest and not re.fullmatch(
            r"[0-9a-f]{64}", destination_secret_digest
        ):
            raise ValueError(
                "notification destination digest must be a SHA-256 value"
            )
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO user_notification_channels (
                    user_id, workspace_id, channel, position, enabled,
                    enabled_at, generation, destination_env_name,
                    destination_secret_digest, last_test_status,
                    last_test_generation, last_test_attempted_at,
                    last_tested_at, last_test_error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, channel) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    position = excluded.position,
                    enabled = excluded.enabled,
                    enabled_at = excluded.enabled_at,
                    generation = excluded.generation,
                    destination_env_name = excluded.destination_env_name,
                    destination_secret_digest =
                        excluded.destination_secret_digest,
                    last_test_status = excluded.last_test_status,
                    last_test_generation = excluded.last_test_generation,
                    last_test_attempted_at =
                        excluded.last_test_attempted_at,
                    last_tested_at = excluded.last_tested_at,
                    last_test_error_code = excluded.last_test_error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    workspace_id,
                    channel,
                    max(0, int(position)),
                    1 if enabled else 0,
                    enabled_at,
                    max(0, int(generation)),
                    destination_env_name,
                    destination_secret_digest,
                    last_test_status,
                    last_test_generation,
                    last_test_attempted_at,
                    last_tested_at,
                    last_test_error_code,
                    now,
                    now,
                ),
            )
            updated = self.get_user_notification_channel(
                workspace_id=workspace_id,
                user_id=user_id,
                channel=channel,
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated is None:
            raise LookupError("notification channel not found after update")
        return updated

    def list_apify_actor_alert_channels(
        self,
        *,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT * FROM apify_actor_alert_channels
            WHERE workspace_id = ?
            ORDER BY position, channel
            """,
            (workspace_id,),
        ).fetchall()
        return [
            channel
            for row in rows
            if (channel := self._notification_channel(row)) is not None
        ]

    def get_apify_actor_alert_channel(
        self,
        *,
        workspace_id: str,
        channel: str,
    ) -> dict[str, Any] | None:
        if channel not in NOTIFICATION_CHANNEL_SET:
            return None
        row = self.connect().execute(
            """
            SELECT * FROM apify_actor_alert_channels
            WHERE workspace_id = ? AND channel = ?
            """,
            (workspace_id, channel),
        ).fetchone()
        return self._notification_channel(row)

    def upsert_apify_actor_alert_channel(
        self,
        *,
        workspace_id: str,
        channel: str,
        position: int,
        enabled: bool,
        enabled_at: str | None,
        generation: int,
        destination_env_name: str | None = None,
        destination_secret_digest: str | None = None,
        last_test_status: str | None = None,
        last_test_generation: int | None = None,
        last_test_attempted_at: str | None = None,
        last_tested_at: str | None = None,
        last_test_error_code: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if channel not in NOTIFICATION_CHANNEL_SET:
            raise ValueError("notification channel is invalid")
        if bool(destination_env_name) != bool(destination_secret_digest):
            raise ValueError(
                "alert destination environment and digest must be configured together"
            )
        if destination_secret_digest and not re.fullmatch(
            r"[0-9a-f]{64}", destination_secret_digest
        ):
            raise ValueError(
                "alert destination digest must be a SHA-256 value"
            )
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO apify_actor_alert_channels (
                    workspace_id, channel, position, enabled, enabled_at,
                    generation, destination_env_name,
                    destination_secret_digest, last_test_status,
                    last_test_generation, last_test_attempted_at,
                    last_tested_at, last_test_error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, channel) DO UPDATE SET
                    position = excluded.position,
                    enabled = excluded.enabled,
                    enabled_at = excluded.enabled_at,
                    generation = excluded.generation,
                    destination_env_name = excluded.destination_env_name,
                    destination_secret_digest =
                        excluded.destination_secret_digest,
                    last_test_status = excluded.last_test_status,
                    last_test_generation = excluded.last_test_generation,
                    last_test_attempted_at =
                        excluded.last_test_attempted_at,
                    last_tested_at = excluded.last_tested_at,
                    last_test_error_code = excluded.last_test_error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    workspace_id,
                    channel,
                    max(0, int(position)),
                    1 if enabled else 0,
                    enabled_at,
                    max(1, int(generation)),
                    destination_env_name,
                    destination_secret_digest,
                    last_test_status,
                    last_test_generation,
                    last_test_attempted_at,
                    last_tested_at,
                    last_test_error_code,
                    now,
                    now,
                ),
            )
            updated = self.get_apify_actor_alert_channel(
                workspace_id=workspace_id,
                channel=channel,
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated is None:
            raise LookupError("alert channel not found after update")
        return updated

    def get_user_notification_settings(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        row = self.connect().execute(
            """
            SELECT *
            FROM user_notification_settings
            WHERE workspace_id = ? AND user_id = ?
            """,
            (workspace_id, user_id),
        ).fetchone()
        return self._notification_settings(row)

    def upsert_user_notification_settings(
        self,
        *,
        workspace_id: str,
        user_id: str,
        enabled: Any = _UNSET,
        channel: Any = _UNSET,
        email_address: Any = _UNSET,
        webhook_env_name: Any = _UNSET,
        webhook_secret_digest: Any = _UNSET,
        webhook_provider: Any = _UNSET,
        webhook_signing_env_name: Any = _UNSET,
        webhook_signing_secret_digest: Any = _UNSET,
        commit: bool = True,
    ) -> dict[str, Any]:
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            user = self.get_user(user_id)
            if (
                user is None
                or str(user["workspace_id"]) != str(workspace_id)
                or not bool(user.get("enabled"))
            ):
                raise LookupError("user not found")
            if str(user.get("role") or "") not in {"owner", "admin", "member"}:
                raise PermissionError(
                    "user cannot modify notification settings"
                )
            current = self.get_user_notification_settings(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            target_enabled = bool(
                (current or {}).get("enabled", False)
                if enabled is _UNSET or enabled is None
                else enabled
            )
            target_channel = str(
                (current or {}).get("channel") or "webhook"
                if channel is _UNSET or channel is None
                else channel
            ).strip().lower()
            if target_channel not in NOTIFICATION_CHANNEL_SET:
                raise ValueError(
                    "notification channel must be email, webhook, or telegram"
                )
            target_email = (
                (current or {}).get("email_address")
                if email_address is _UNSET
                else email_address
            )
            target_webhook_env = (
                (current or {}).get("webhook_env_name")
                if webhook_env_name is _UNSET
                else webhook_env_name
            )
            target_webhook_digest = (
                (current or {}).get("webhook_secret_digest")
                if webhook_secret_digest is _UNSET
                else webhook_secret_digest
            )
            target_webhook_provider = str(
                (current or {}).get("webhook_provider") or "legacy_auto"
                if webhook_provider is _UNSET
                else webhook_provider
            ).strip().lower()
            if target_webhook_provider not in WEBHOOK_PROVIDERS:
                raise ValueError("webhook provider is not supported")
            target_signing_env = (
                (current or {}).get("webhook_signing_env_name")
                if webhook_signing_env_name is _UNSET
                else webhook_signing_env_name
            )
            target_signing_digest = (
                (current or {}).get("webhook_signing_secret_digest")
                if webhook_signing_secret_digest is _UNSET
                else webhook_signing_secret_digest
            )
            if bool(str(target_webhook_env or "").strip()) != bool(
                str(target_webhook_digest or "").strip()
            ):
                raise ValueError(
                    "webhook destination environment and digest must be configured together"
                )
            if target_webhook_digest and not re.fullmatch(
                r"[0-9a-f]{64}",
                str(target_webhook_digest),
            ):
                raise ValueError(
                    "webhook destination digest must be a SHA-256 value"
                )
            if bool(str(target_signing_env or "").strip()) != bool(
                str(target_signing_digest or "").strip()
            ):
                raise ValueError(
                    "webhook signing environment and digest must be configured together"
                )
            if target_signing_digest and not re.fullmatch(
                r"[0-9a-f]{64}",
                str(target_signing_digest),
            ):
                raise ValueError(
                    "webhook signing digest must be a SHA-256 value"
                )
            if (
                target_signing_digest
                and target_webhook_provider
                not in {"feishu_lark_v2", "dingtalk"}
            ):
                raise ValueError(
                    "selected webhook provider does not support signing"
                )
            now = _now_iso()
            notification_enabled_at = (current or {}).get(
                "notification_enabled_at"
            )
            notification_generation = int(
                (current or {}).get("notification_generation") or 0
            )
            compatibility_projection_changed = current is not None and any(
                (
                    target_channel
                    != str((current or {}).get("channel") or "webhook"),
                    target_email != (current or {}).get("email_address"),
                    target_webhook_env
                    != (current or {}).get("webhook_env_name"),
                    target_webhook_digest
                    != (current or {}).get("webhook_secret_digest"),
                    target_webhook_provider
                    != str(
                        (current or {}).get("webhook_provider")
                        or "legacy_auto"
                    ),
                    target_signing_env
                    != (current or {}).get("webhook_signing_env_name"),
                    target_signing_digest
                    != (current or {}).get(
                        "webhook_signing_secret_digest"
                    ),
                )
            )
            generation_changed = bool(
                target_enabled != bool((current or {}).get("enabled"))
            )
            if generation_changed:
                notification_generation += 1
            if not target_enabled:
                notification_enabled_at = None
            elif not bool((current or {}).get("enabled")):
                notification_enabled_at = now
            last_test_status = (current or {}).get("last_test_status")
            last_tested_at = (current or {}).get("last_tested_at")
            last_test_error_code = (current or {}).get(
                "last_test_error_code"
            )
            if compatibility_projection_changed:
                last_test_status = None
                last_tested_at = None
                last_test_error_code = None
            conn.execute(
                """
                INSERT INTO user_notification_settings (
                    user_id, workspace_id, enabled, channel, email_address,
                    webhook_env_name, webhook_secret_digest,
                    webhook_provider, webhook_signing_env_name,
                    webhook_signing_secret_digest,
                    notification_enabled_at, notification_generation,
                    last_test_status, last_tested_at, last_test_error_code,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(user_id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    enabled = excluded.enabled,
                    channel = excluded.channel,
                    email_address = excluded.email_address,
                    webhook_env_name = excluded.webhook_env_name,
                    webhook_secret_digest = excluded.webhook_secret_digest,
                    webhook_provider = excluded.webhook_provider,
                    webhook_signing_env_name =
                        excluded.webhook_signing_env_name,
                    webhook_signing_secret_digest =
                        excluded.webhook_signing_secret_digest,
                    notification_enabled_at = excluded.notification_enabled_at,
                    notification_generation = excluded.notification_generation,
                    last_test_status = excluded.last_test_status,
                    last_tested_at = excluded.last_tested_at,
                    last_test_error_code = excluded.last_test_error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    workspace_id,
                    1 if target_enabled else 0,
                    target_channel,
                    target_email,
                    target_webhook_env,
                    target_webhook_digest,
                    target_webhook_provider,
                    target_signing_env,
                    target_signing_digest,
                    notification_enabled_at,
                    notification_generation,
                    last_test_status,
                    last_tested_at,
                    last_test_error_code,
                    now,
                    now,
                ),
            )
            has_channel_table = bool(
                conn.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'user_notification_channels'
                    """
                ).fetchone()
            )
            if has_channel_table and not conn.execute(
                """
                SELECT 1 FROM user_notification_channels
                WHERE user_id = ?
                LIMIT 1
                """,
                (user_id,),
            ).fetchone():
                conn.execute(
                    """
                    INSERT INTO user_notification_channels (
                        user_id, workspace_id, channel, position, enabled,
                        enabled_at, generation, created_at, updated_at
                    ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        workspace_id,
                        target_channel,
                        1 if target_enabled else 0,
                        notification_enabled_at,
                        max(1, notification_generation),
                        now,
                        now,
                    ),
                )
            updated = self.get_user_notification_settings(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated is None:
            raise LookupError("notification settings not found after update")
        return updated

    def record_user_notification_test(
        self,
        *,
        workspace_id: str,
        user_id: str,
        status: str,
        channel: str | None = None,
        generation: int | None = None,
        error_code: str | None = None,
        tested_at: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any] | None:
        if status not in {"sent", "failed"}:
            raise ValueError("notification test status must be sent or failed")
        conn = self.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            current = self.get_user_notification_settings(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            if current is None:
                raise LookupError("notification settings not found")
            target_channel = str(
                channel or current.get("channel") or "webhook"
            ).strip().lower()
            if target_channel not in NOTIFICATION_CHANNEL_SET:
                raise ValueError("notification test channel is invalid")
            now = tested_at or _now_iso()
            updated_row = conn.execute(
                """
                UPDATE user_notification_channels
                SET last_test_status = ?,
                    last_test_generation = generation,
                    last_tested_at = ?,
                    last_test_error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND user_id = ? AND channel = ?
                  AND (? IS NULL OR generation = ?)
                """,
                (
                    status,
                    now,
                    error_code if status == "failed" else None,
                    now,
                    workspace_id,
                    user_id,
                    target_channel,
                    generation,
                    generation,
                ),
            )
            if updated_row.rowcount != 1:
                if owns_transaction:
                    conn.commit()
                return None
            conn.execute(
                """
                UPDATE user_notification_settings
                SET last_test_status = ?, last_tested_at = ?,
                    last_test_error_code = ?, updated_at = ?
                WHERE workspace_id = ? AND user_id = ? AND channel = ?
                """,
                (
                    status,
                    now,
                    error_code if status == "failed" else None,
                    now,
                    workspace_id,
                    user_id,
                    target_channel,
                ),
            )
            updated = self.get_user_notification_channel(
                workspace_id=workspace_id,
                user_id=user_id,
                channel=target_channel,
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        if updated is None:
            raise LookupError("notification settings not found after test update")
        return updated

    def claim_user_notification_test_attempt(
        self,
        *,
        workspace_id: str,
        user_id: str,
        channel: str | None = None,
        cooldown_seconds: int = 60,
        attempted_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically reserve a per-user test-send cooldown window."""

        conn = self.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification test attempt requires no active transaction"
            )
        cooldown = max(1, int(cooldown_seconds))
        try:
            now = (
                datetime.fromisoformat(
                    str(attempted_at).replace("Z", "+00:00")
                )
                if attempted_at
                else datetime.now(timezone.utc)
            )
        except ValueError as exc:
            raise ValueError(
                "notification test attempt timestamp must be ISO 8601"
            ) from exc
        if now.tzinfo is None:
            raise ValueError(
                "notification test attempt timestamp must include a timezone"
            )
        now = now.astimezone(timezone.utc)
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = self.get_user(user_id)
            if (
                user is None
                or not bool(user.get("enabled"))
                or str(user.get("workspace_id")) != str(workspace_id)
                or str(user.get("role") or "")
                not in {"owner", "admin", "member"}
            ):
                conn.commit()
                return {
                    "claimed": False,
                    "reason": "user_disabled",
                    "retry_after_seconds": 0,
                    "settings": None,
                }
            current = self.get_user_notification_settings(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            if current is None:
                raise LookupError("notification settings not found")
            target_channel = str(
                channel or current.get("channel") or "webhook"
            ).strip().lower()
            if target_channel not in NOTIFICATION_CHANNEL_SET:
                raise ValueError("notification test channel is invalid")
            channel_state = self.get_user_notification_channel(
                workspace_id=workspace_id,
                user_id=user_id,
                channel=target_channel,
            )
            if channel_state is None:
                raise LookupError("notification channel not found")
            last_attempted_at = channel_state.get(
                "last_test_attempted_at"
            )
            elapsed: float | None = None
            if last_attempted_at:
                try:
                    previous = datetime.fromisoformat(
                        str(last_attempted_at).replace("Z", "+00:00")
                    )
                except ValueError:
                    previous = None
                if previous is not None and previous.tzinfo is not None:
                    elapsed = (
                        now - previous.astimezone(timezone.utc)
                    ).total_seconds()
            if elapsed is not None and elapsed < cooldown:
                conn.commit()
                return {
                    "claimed": False,
                    "reason": "rate_limited",
                    "retry_after_seconds": max(
                        1,
                        int(math.ceil(cooldown - elapsed)),
                    ),
                    "settings": {
                        **current,
                        "channel": target_channel,
                        "_channel_state": channel_state,
                    },
                }
            attempted_at_iso = now.isoformat()
            conn.execute(
                """
                UPDATE user_notification_channels
                SET last_test_attempted_at = ?
                WHERE workspace_id = ? AND user_id = ? AND channel = ?
                """,
                (
                    attempted_at_iso,
                    workspace_id,
                    user_id,
                    target_channel,
                ),
            )
            claimed_channel = self.get_user_notification_channel(
                workspace_id=workspace_id,
                user_id=user_id,
                channel=target_channel,
            )
            claimed = (
                {
                    **current,
                    "channel": target_channel,
                    "_channel_state": claimed_channel,
                }
                if claimed_channel is not None
                else None
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        if claimed is None:
            raise LookupError("notification settings not found after test claim")
        return {
            "claimed": True,
            "reason": None,
            "retry_after_seconds": 0,
            "settings": claimed,
        }

    def get_preferred_source_notification_delivery(
        self,
        delivery_id: str,
    ) -> dict[str, Any] | None:
        row = self.connect().execute(
            """
            SELECT *
            FROM preferred_source_notification_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        ).fetchone()
        return self._preferred_source_notification_delivery(row)

    def list_preferred_source_notification_deliveries(
        self,
        *,
        workspace_id: str,
        user_id: str | None = None,
        status: str | None = None,
        job_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses = ["workspace_id = ?"]
        parameters: list[Any] = [workspace_id]
        if user_id is not None:
            clauses.append("user_id = ?")
            parameters.append(user_id)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if job_id is not None:
            clauses.append("job_id = ?")
            parameters.append(job_id)
        parameters.append(max(1, min(int(limit), 200)))
        rows = self.connect().execute(
            f"""
            SELECT *
            FROM preferred_source_notification_deliveries
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [
            delivery
            for row in rows
            if (
                delivery := self._preferred_source_notification_delivery(row)
            )
        ]

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
            """
            UPDATE secret_refs
            SET version = version + 1, updated_at = ?
            WHERE id = ?
            """,
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

    def list_workspace_sources(
        self,
        *,
        workspace_id: str,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT *
            FROM source_catalog
            WHERE workspace_id = ?
              AND (? = 1 OR enabled = 1)
            ORDER BY display_name, id
            """,
            (workspace_id, 1 if include_disabled else 0),
        ).fetchall()
        return [source for row in rows if (source := self._source(row))]

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
        scope: Any = _UNSET,
        owner_user_id: Any = _UNSET,
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
            target_scope = current["scope"] if scope is _UNSET else str(scope)
            if target_scope not in SOURCE_SCOPES:
                raise ValueError("scope must be public, workspace, or private")
            target_owner_user_id = (
                current["owner_user_id"] if owner_user_id is _UNSET else owner_user_id
            )
            if target_scope != "private":
                target_owner_user_id = None
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
                SET scope = ?, owner_user_id = ?,
                    display_name = ?, description = ?, default_channel = ?,
                    default_topics_json = ?, config_json = ?, source_key = ?, secret_env = ?,
                    enforce_public_network = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    target_scope,
                    target_owner_user_id,
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
            if current["scope"] == "private" and target_scope in {"public", "workspace"}:
                conn.execute(
                    """
                    UPDATE media_assets
                    SET user_id = NULL,
                        visibility_scope = ?,
                        updated_at = ?
                    WHERE workspace_id = ? AND source_id = ?
                    """,
                    (target_scope, now, current["workspace_id"], source_id),
                )
            if not target_enabled:
                conn.execute(
                    """
                    UPDATE user_subscriptions
                    SET notify_on_new_items = 0,
                        notification_enabled_at = NULL,
                        updated_at = ?
                    WHERE source_id = ?
                      AND (
                        notify_on_new_items = 1
                        OR notification_enabled_at IS NOT NULL
                      )
                    """,
                    (now, source_id),
                )
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

    def source_subscription_usage(self, source_id: str) -> dict[str, int]:
        row = self.connect().execute(
            """
            SELECT
                COUNT(*) AS subscriber_count,
                COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0)
                    AS enabled_subscriber_count
            FROM user_subscriptions
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()
        return {
            "subscriber_count": int(row["subscriber_count"] or 0),
            "enabled_subscriber_count": int(row["enabled_subscriber_count"] or 0),
        }

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
        notify_on_new_items: Any = _UNSET,
        commit: bool = True,
    ) -> dict[str, Any]:
        requested_notifications = bool(
            False
            if notify_on_new_items is _UNSET or notify_on_new_items is None
            else notify_on_new_items
        )
        if analysis_mode not in {"full", "personal_only"}:
            raise ValueError("analysis_mode must be full or personal_only")
        if not enabled and requested_notifications:
            raise ValueError(
                "disabled subscriptions cannot enable new-item notifications"
            )
        if analysis_mode == "personal_only" and requested_notifications:
            raise ValueError(
                "personal_only subscriptions cannot enable new-item notifications"
            )
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
                    notify_on_new_items=notify_on_new_items,
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
                    priority, notify_on_new_items, notification_enabled_at,
                    notification_generation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, source_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    override_channel=excluded.override_channel,
                    override_topics_json=excluded.override_topics_json,
                    personal_tags_json=excluded.personal_tags_json,
                    analysis_mode=excluded.analysis_mode,
                    priority=excluded.priority,
                    notify_on_new_items=excluded.notify_on_new_items,
                    notification_enabled_at=excluded.notification_enabled_at,
                    notification_generation=excluded.notification_generation,
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
                    1 if requested_notifications else 0,
                    now if enabled and requested_notifications else None,
                    1 if enabled and requested_notifications else 0,
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
                us.notify_on_new_items,
                us.notification_enabled_at,
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
                sc.enabled AS source_enabled,
                COALESCE(uss.enabled, 0) AS source_schedule_enabled
            FROM user_subscriptions us
            JOIN source_catalog sc ON sc.id = us.source_id
            LEFT JOIN user_source_schedules uss ON uss.subscription_id = us.id
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
            data["notify_on_new_items"] = _bool(data["notify_on_new_items"])
            data["source_enabled"] = _bool(data["source_enabled"])
            data["source_schedule_enabled"] = _bool(
                data["source_schedule_enabled"]
            )
            data["override_topics"] = _json_loads(data.pop("override_topics_json"), [])
            data["personal_tags"] = _json_loads(data.pop("personal_tags_json"), [])
            data["default_topics"] = _json_loads(data.pop("default_topics_json"), [])
            data["config"] = _json_loads(data.pop("config_json"), {})
            records.append(data)
        return records

    def has_enabled_user_subscriptions(
        self,
        *,
        workspace_id: str,
        user_id: str,
        global_schedule_only: bool = False,
    ) -> bool:
        schedule_filter = (
            "AND COALESCE(uss.enabled, 0) = 0"
            if global_schedule_only
            else ""
        )
        return bool(
            self.connect().execute(
                f"""
                SELECT 1
                FROM user_subscriptions us
                JOIN source_catalog sc ON sc.id = us.source_id
                LEFT JOIN user_source_schedules uss ON uss.subscription_id = us.id
                WHERE us.user_id = ?
                  AND sc.workspace_id = ?
                  AND us.enabled = 1
                  AND sc.enabled = 1
                  {schedule_filter}
                LIMIT 1
                """,
                (user_id, workspace_id),
            ).fetchone()
        )

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
                us.notify_on_new_items,
                us.notification_enabled_at,
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
            data["notify_on_new_items"] = _bool(data["notify_on_new_items"])
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

    def get_subscription_notification_generation(
        self,
        subscription_id: str,
    ) -> int | None:
        row = self.connect().execute(
            """
            SELECT notification_generation
            FROM user_subscriptions
            WHERE id = ?
            """,
            (subscription_id,),
        ).fetchone()
        return (
            int(row["notification_generation"] or 0)
            if row is not None
            else None
        )

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
        notify_on_new_items: Any = _UNSET,
        disable_disposition: str = "remove",
        commit: bool = True,
    ) -> dict[str, Any]:
        if disable_disposition not in {"remove", "keep", "save", "dismiss"}:
            raise ValueError("disable_disposition must be remove, keep, save, or dismiss")
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
            target_notifications = bool(
                current["notify_on_new_items"]
                if notify_on_new_items is _UNSET or notify_on_new_items is None
                else notify_on_new_items
            )
            if (
                not target_enabled
                and notify_on_new_items is not _UNSET
                and notify_on_new_items is not None
                and bool(notify_on_new_items)
            ):
                raise ValueError(
                    "disabled subscriptions cannot enable new-item notifications"
                )
            if mode == "personal_only":
                if (
                    notify_on_new_items is not _UNSET
                    and notify_on_new_items is not None
                    and bool(notify_on_new_items)
                ):
                    raise ValueError(
                        "personal_only subscriptions cannot enable new-item notifications"
                    )
                target_notifications = False
            if not target_enabled:
                target_notifications = False
            notification_enabled_at = current.get("notification_enabled_at")
            notification_generation = int(
                self.get_subscription_notification_generation(
                    subscription_id
                )
                or 0
            )
            if not target_notifications or not target_enabled:
                notification_enabled_at = None
            elif (
                not current["notify_on_new_items"]
                or not current["enabled"]
                or not notification_enabled_at
            ):
                notification_enabled_at = now
                notification_generation += 1
            conn.execute(
                """
                UPDATE user_subscriptions
                SET enabled = ?, override_channel = ?, override_topics_json = ?,
                    personal_tags_json = ?, analysis_mode = ?, priority = ?,
                    notify_on_new_items = ?, notification_enabled_at = ?,
                    notification_generation = ?, updated_at = ?
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
                    1 if target_notifications else 0,
                    notification_enabled_at,
                    notification_generation,
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
                if disable_disposition in {"save", "dismiss"}:
                    self._apply_source_content_disposition_locked(
                        user_id=str(current["user_id"]),
                        source_id=str(current["source_id"]),
                        disposition=disable_disposition,
                        now=now,
                    )
                if disable_disposition != "keep":
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
                """
                SELECT us.source_id, sc.scope, sc.owner_user_id
                FROM user_subscriptions AS us
                JOIN source_catalog AS sc ON sc.id = us.source_id
                WHERE us.id = ? AND us.user_id = ?
                """,
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
            if (
                existing["scope"] == "private"
                and existing["owner_user_id"] == user_id
                and conn.execute(
                    "SELECT 1 FROM user_subscriptions WHERE source_id = ? LIMIT 1",
                    (existing["source_id"],),
                ).fetchone() is None
            ):
                conn.execute(
                    """
                    UPDATE source_catalog
                    SET enabled = 0, updated_at = ?
                    WHERE id = ? AND scope = 'private' AND owner_user_id = ?
                    """,
                    (now, existing["source_id"], user_id),
                )
            if owns_transaction:
                conn.commit()
            return cur.rowcount > 0
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def _apply_source_content_disposition_locked(
        self,
        *,
        user_id: str,
        source_id: str,
        disposition: str,
        now: str,
    ) -> int:
        user = self.get_user(user_id)
        if user is None:
            return 0
        rows = self.connect().execute(
            """
            SELECT article_id
            FROM user_content_items
            WHERE workspace_id = ? AND user_id = ? AND source_id = ?
            """,
            (user["workspace_id"], user_id, source_id),
        ).fetchall()
        for row in rows:
            article_id = str(row["article_id"])
            state_id = _new_id("uis")
            if disposition == "save":
                self.connect().execute(
                    """
                    INSERT INTO user_item_state (
                        id, workspace_id, user_id, article_id,
                        is_read, is_saved, is_later,
                        read_at, saved_at, later_at, dismissed_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 0, 1, 0, NULL, ?, NULL, NULL, ?, ?)
                    ON CONFLICT(workspace_id, user_id, article_id) DO UPDATE SET
                        is_saved = 1,
                        saved_at = excluded.saved_at,
                        updated_at = excluded.updated_at
                    """,
                    (state_id, user["workspace_id"], user_id, article_id, now, now, now),
                )
            else:
                self.connect().execute(
                    """
                    INSERT INTO user_item_state (
                        id, workspace_id, user_id, article_id,
                        is_read, is_saved, is_later,
                        read_at, saved_at, later_at, dismissed_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 0, 0, 0, NULL, NULL, NULL, ?, ?, ?)
                    ON CONFLICT(workspace_id, user_id, article_id) DO UPDATE SET
                        dismissed_at = excluded.dismissed_at,
                        updated_at = excluded.updated_at
                    """,
                    (state_id, user["workspace_id"], user_id, article_id, now, now, now),
                )
        return len(rows)

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
