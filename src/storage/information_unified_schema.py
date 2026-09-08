"""Global 40 sidecars preserve the exact global 38/39 table contracts."""
import json
from datetime import datetime, timezone
from .information_connector_schema import ready as prerequisite_ready

MIGRATION_VERSION = 40
MIGRATION_NAME = 'information_unified'
MIGRATION_CHECKSUM = 'information-unified-v2'
TABLES = {
    'information_trigger_state': '''CREATE TABLE information_trigger_state (
        rule_id TEXT PRIMARY KEY REFERENCES information_rules(id) ON DELETE CASCADE,
        next_due TEXT)''',
    'information_model_catalog': '''CREATE TABLE information_model_catalog (
        binding_id TEXT PRIMARY KEY REFERENCES information_connectors(binding_id),
        generation INTEGER NOT NULL, models_json TEXT NOT NULL,
        updated_at TEXT NOT NULL, refresh_requested INTEGER NOT NULL DEFAULT 0, blocked_models_json TEXT NOT NULL DEFAULT '[]')''',
    'information_rule_carry': '''CREATE TABLE information_rule_carry (
        old_run_id TEXT PRIMARY KEY REFERENCES information_runs(id),
        rule_id TEXT NOT NULL REFERENCES information_rules(id))''',
    'information_event_carry': '''CREATE TABLE information_event_carry (
        rule_id TEXT NOT NULL REFERENCES information_rules(id),
        event_id INTEGER NOT NULL REFERENCES information_events(id),
        PRIMARY KEY(rule_id,event_id))''',
    'information_batches': '''CREATE TABLE information_batches (
        id TEXT PRIMARY KEY,
        run_id TEXT UNIQUE REFERENCES information_runs(id),
        preview_id TEXT UNIQUE REFERENCES information_previews(id),
        result_json TEXT, model_json TEXT NOT NULL, created_at TEXT NOT NULL,
        CHECK((run_id IS NULL) <> (preview_id IS NULL)))''',
    'information_batch_steps': '''CREATE TABLE information_batch_steps (
        id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES information_batches(id),
        level INTEGER NOT NULL, ordinal INTEGER NOT NULL, kind TEXT NOT NULL,
        input_json TEXT NOT NULL, result_json TEXT,
        status TEXT NOT NULL CHECK(status IN ('pending','judging','completed','failed')),
        attempts INTEGER NOT NULL DEFAULT 0,
        claim_id TEXT REFERENCES information_claims(id),
        UNIQUE(batch_id, level, ordinal))''',
}
INDEXES = {'information_steps_batch': 'CREATE INDEX information_steps_batch ON information_batch_steps(batch_id,level,ordinal)'}


def migration_marker_exists(conn):
    return bool(conn.execute('SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?',
                            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM)).fetchone())


def schema_shapes_valid(conn):
    normalize = lambda value: ' '.join((value or '').lower().split())
    for name, sql in {**TABLES, **INDEXES}.items():
        row = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(sql):
            return False
    return prerequisite_ready(conn)


def ready(conn):
    return migration_marker_exists(conn) and schema_shapes_valid(conn)


def convert_rules(conn, now):
    from ..services.information_automations.config import RuleConfig
    count = 0
    for row in conn.execute("SELECT * FROM information_rules WHERE state<>'archived'").fetchall():
        config = RuleConfig.model_validate_json(row['config_json']).model_dump_json()
        version = row['version'] + 1
        conn.execute('INSERT INTO information_rule_versions VALUES(?,?,?,?)', (row['id'], version, config, now))
        conn.execute('''UPDATE information_rules SET version=?,config_json=?,state=?,issue='configuration_upgraded',
            confirmed_at=NULL,confirmation_id=NULL,updated_at=? WHERE id=?''',
            (version, config, 'draft' if row['state'] == 'draft' else 'paused', now, row['id']))
        conn.execute("UPDATE information_runs SET status='cancelled',notification_status='cancelled',reason='configuration_upgraded' WHERE rule_id=? AND status IN ('pending','judging','quota_wait')", (row['id'],))
        conn.execute("UPDATE information_runs SET notification_status='cancelled',reason='configuration_upgraded' WHERE rule_id=? AND notification_status IN ('pending','quota_wait')", (row['id'],))
        count += 1
    conn.execute("UPDATE information_previews SET status='failed',reason='configuration_upgraded' WHERE status IN ('pending','judging','quota_wait')")
    return count


def apply_migration(conn):
    if conn.in_transaction:
        raise RuntimeError('unified migration requires a committed connection')
    if conn.execute('SELECT 1 FROM schema_migrations WHERE version=40').fetchone():
        if not ready(conn):
            raise RuntimeError('global 40 schema conflict')
        return {'rules_upgraded': 0}
    if not prerequisite_ready(conn):
        raise RuntimeError('valid global 39 is required')
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute('BEGIN IMMEDIATE')
        for sql in (*TABLES.values(), *INDEXES.values()):
            conn.execute(sql)
        count = convert_rules(conn, now)
        conn.execute('INSERT INTO schema_migrations VALUES(?,?,?,?)', (40, MIGRATION_NAME, MIGRATION_CHECKSUM, now))
        if not schema_shapes_valid(conn) or conn.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('unified migration validation failed')
        conn.commit()
        return {'rules_upgraded': count}
    except Exception:
        conn.rollback()
        raise
