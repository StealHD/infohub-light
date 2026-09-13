"""Explicit global 47 notification destinations and preview delivery ledger."""

from datetime import datetime, timezone

from .source_identity_schema import ready as prerequisite_ready

VERSION = 47
NAME = "notification_destinations"
CHECKSUM = "notification-destinations-v1"
TABLES = {
    "notification_target_topics": """CREATE TABLE notification_target_topics (
        target_id TEXT PRIMARY KEY REFERENCES notification_targets(id) ON DELETE CASCADE,
        message_thread_id INTEGER NOT NULL CHECK(message_thread_id > 0))""",
    "openclaw_notification_services": """CREATE TABLE openclaw_notification_services (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        name TEXT NOT NULL, name_key TEXT NOT NULL,
        channel_id TEXT NOT NULL, account_id TEXT NOT NULL,
        destination_env_name TEXT NOT NULL, destination_digest TEXT NOT NULL,
        message_thread_id INTEGER CHECK(message_thread_id > 0),
        enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
        config_generation INTEGER NOT NULL DEFAULT 1,
        activation_generation INTEGER NOT NULL DEFAULT 0,
        last_test_status TEXT CHECK(last_test_status IN ('sent','failed','unknown')),
        last_test_generation INTEGER, last_tested_at TEXT,
        archived_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(workspace_id,name_key))""",
    "information_preview_notifications": """CREATE TABLE information_preview_notifications (
        preview_id TEXT PRIMARY KEY REFERENCES information_previews(id) ON DELETE CASCADE,
        target_id TEXT NOT NULL, target_generation INTEGER NOT NULL, target_activation INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN
            ('waiting_analysis','pending','sending','sent','failed','unknown','cancelled','quota_wait','not_required')),
        delivery_started_at TEXT, ready_at TEXT, receipt_json TEXT, reason TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
}

EXPECTED = {
    'notification_target_topics': {'target_id', 'message_thread_id'},
    'openclaw_notification_services': {'id', 'workspace_id', 'name', 'name_key', 'channel_id',
        'account_id', 'destination_env_name', 'destination_digest', 'message_thread_id',
        'enabled', 'config_generation', 'activation_generation', 'last_test_status',
        'last_test_generation', 'last_tested_at', 'archived_at', 'created_at', 'updated_at'},
    'information_preview_notifications': {'preview_id', 'target_id', 'target_generation',
        'target_activation', 'status', 'delivery_started_at', 'ready_at', 'receipt_json',
        'reason', 'created_at', 'updated_at'},
}


def ready(conn):
    try:
        marker = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
            (VERSION, NAME, CHECKSUM),
        ).fetchone()
        return bool(marker) and all(
            {row[1] for row in conn.execute(f"PRAGMA table_info({name})")} == EXPECTED[name]
            for name in TABLES
        )
    except Exception:
        return False


def apply_migration(conn):
    if ready(conn):
        return
    if not prerequisite_ready(conn):
        raise ValueError("global 46 required")
    if conn.in_transaction:
        raise RuntimeError("global 47 requires a committed connection")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (VERSION,)).fetchone():
            raise ValueError("global 47 marker conflict")
        for sql in TABLES.values():
            conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
            (VERSION, NAME, CHECKSUM, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def bootstrap(conn, *, existing_schema):
    if not existing_schema:
        apply_migration(conn)
