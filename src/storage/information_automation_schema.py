"""Global 38: opt-in information rules and durable, user-scoped acquisition facts."""
import sqlite3
import json
from datetime import datetime, timezone

from . import agent_connection_schema as prerequisite
from ..content_identity import feed_item_fingerprint

MIGRATION_VERSION = 38
MIGRATION_NAME = 'information_automations'
MIGRATION_CHECKSUM = 'information-automations-v1'

TABLES = {
    'information_rules': '''CREATE TABLE information_rules (
        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        version INTEGER NOT NULL CHECK(version > 0),
        state TEXT NOT NULL CHECK(state IN ('draft','active','paused','archived')),
        config_json TEXT NOT NULL, issue TEXT, binding_id TEXT, target_generation INTEGER,
        target_activation INTEGER, transport_generation INTEGER, checked_at TEXT,
        confirmed_at TEXT, confirmation_id TEXT, cursor INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
    'information_rule_versions': '''CREATE TABLE information_rule_versions (
        rule_id TEXT NOT NULL REFERENCES information_rules(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, config_json TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(rule_id, version))''',
    'information_rule_approvals': '''CREATE TABLE information_rule_approvals (
        id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, version INTEGER NOT NULL,
        context_json TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(rule_id,version) REFERENCES information_rule_versions(rule_id,version))''',
    'information_source_baselines': '''CREATE TABLE information_source_baselines (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id, source_id))''',
    'information_seen_items': '''CREATE TABLE information_seen_items (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        article_id TEXT NOT NULL, PRIMARY KEY(user_id, article_id))''',
    'information_seen_identities': '''CREATE TABLE information_seen_identities (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64), PRIMARY KEY(user_id,fingerprint))''',
    'information_events': '''CREATE TABLE information_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        article_id TEXT NOT NULL, source_ids_json TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(user_id, article_id))''',
    'information_runs': '''CREATE TABLE information_runs (
        id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, version INTEGER NOT NULL,
        confirmation_id TEXT NOT NULL REFERENCES information_rule_approvals(id),
        status TEXT NOT NULL CHECK(status IN
            ('pending','judging','matched','not_matched','insufficient','failed','cancelled','quota_wait')),
        notification_status TEXT NOT NULL CHECK(notification_status IN
            ('not_required','pending','sending','sent','failed','unknown','cancelled','quota_wait')),
        reason TEXT, input_json TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '[]',
        event_ids_json TEXT NOT NULL, receipt_json TEXT, claim_hash TEXT, lease_until TEXT,
        delivery_started_at TEXT, result_hash TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        ready_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(rule_id, version) REFERENCES information_rule_versions(rule_id, version))''',
}
INDEXES = {
    'information_events_owner': 'CREATE INDEX information_events_owner ON information_events(user_id, id)',
    'information_runs_rule': 'CREATE INDEX information_runs_rule ON information_runs(rule_id, created_at, id)',
}


def prerequisite_ready(connection):
    return prerequisite.migration_marker_exists(connection) and prerequisite.schema_shapes_valid(connection)


def migration_marker_exists(connection):
    return bool(connection.execute(
        'SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?',
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection):
    # Compare the complete declarations, including constraints and unique indexes.
    normalize = lambda sql: ' '.join((sql or '').lower().split())
    for name, expected in {**TABLES, **INDEXES}.items():
        row = connection.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(expected):
            return False
    return prerequisite_ready(connection)


def ready(connection):
    return migration_marker_exists(connection) and schema_shapes_valid(connection)


def apply_migration(connection: sqlite3.Connection):
    if connection.in_transaction:
        raise RuntimeError('information migration requires a committed connection')
    if connection.execute('SELECT 1 FROM schema_migrations WHERE version=38').fetchone():
        if not ready(connection):
            raise RuntimeError('global 38 schema or marker conflict')
        return {'rules_created': 0}
    if not prerequisite_ready(connection):
        raise RuntimeError('valid global 37 is required')
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute('BEGIN IMMEDIATE')
        for statement in (*TABLES.values(), *INDEXES.values()):
            connection.execute(statement)
        # Historical facts only establish deduplication/baselines; no historical events or rules.
        connection.execute('''INSERT OR IGNORE INTO information_seen_items(user_id,article_id)
            SELECT user_id,article_id FROM user_content_items''')
        for user_id, article_id, raw in connection.execute('SELECT user_id,article_id,item_json FROM user_content_items'):
            try:
                item = json.loads(raw)
            except (TypeError, ValueError):
                item = {}
            item = {**(item if isinstance(item, dict) else {}), 'id': article_id}
            connection.execute('INSERT OR IGNORE INTO information_seen_identities VALUES(?,?)',
                               (user_id, feed_item_fingerprint(item)))
        connection.execute('''INSERT OR IGNORE INTO information_source_baselines(user_id,source_id,created_at)
            SELECT user_id,source_id,? FROM user_source_health WHERE last_success_at IS NOT NULL''', (now,))
        connection.execute('''INSERT OR IGNORE INTO information_source_baselines(user_id,source_id,created_at)
            SELECT user_id,source_id,? FROM user_content_items WHERE source_id IS NOT NULL AND source_id<>'' ''', (now,))
        connection.execute('''INSERT OR IGNORE INTO information_source_baselines(user_id,source_id,created_at)
            SELECT c.user_id,j.value,? FROM user_content_items c,
            json_each(CASE WHEN json_valid(c.item_json) THEN json_extract(c.item_json,'$.source_ids') ELSE '[]' END) j
            WHERE j.type='text' AND j.value<>'' ''', (now,))
        connection.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)',
                           (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, now))
        if not schema_shapes_valid(connection):
            raise RuntimeError('information schema validation failed')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {'rules_created': 0}
