"""Global 39: independent machine credentials and durable semantic claims."""
from datetime import datetime, timezone
from .information_automation_schema import ready as prerequisite_ready

MIGRATION_VERSION = 39
MIGRATION_NAME = 'information_connector'
MIGRATION_CHECKSUM = 'information-connector-v1'
TABLES = {
    'information_connectors': '''CREATE TABLE information_connectors (
        binding_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation > 0),
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), verified_at TEXT, last_seen TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
    'information_previews': '''CREATE TABLE information_previews (
        id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES information_rules(id),
        user_id TEXT NOT NULL REFERENCES users(id), version INTEGER NOT NULL,
        binding_id TEXT NOT NULL, input_json TEXT NOT NULL, requirement TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','judging','completed','failed','quota_wait')),
        results_json TEXT NOT NULL DEFAULT '[]', reason TEXT, claim_hash TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, ready_at TEXT NOT NULL, created_at TEXT NOT NULL)''',
    'information_claims': '''CREATE TABLE information_claims (
        id TEXT PRIMARY KEY, run_id TEXT REFERENCES information_runs(id),
        preview_id TEXT REFERENCES information_previews(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id), binding_id TEXT NOT NULL,
        connector_generation INTEGER NOT NULL, token_hash TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK(status IN ('claimed','completed','expired','rejected')),
        result_hash TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
        completed_at TEXT, CHECK((run_id IS NULL) <> (preview_id IS NULL)))''',
}
INDEXES = {'information_claims_quota': 'CREATE INDEX information_claims_quota ON information_claims(user_id,created_at)'}


def migration_marker_exists(connection):
    return bool(connection.execute('SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?',
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM)).fetchone())


def schema_shapes_valid(connection):
    normalize = lambda sql: ' '.join((sql or '').lower().split())
    for name, expected in {**TABLES, **INDEXES}.items():
        row = connection.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(expected):
            return False
    return prerequisite_ready(connection)


def ready(connection):
    return migration_marker_exists(connection) and schema_shapes_valid(connection)


def apply_migration(connection):
    if connection.in_transaction:
        raise RuntimeError('connector migration requires a committed connection')
    if connection.execute('SELECT 1 FROM schema_migrations WHERE version=39').fetchone():
        if not ready(connection):
            raise RuntimeError('global 39 schema conflict')
        return {'connectors_created': 0}
    if not prerequisite_ready(connection):
        raise RuntimeError('valid global 38 is required')
    try:
        connection.execute('BEGIN IMMEDIATE')
        for statement in (*TABLES.values(), *INDEXES.values()):
            connection.execute(statement)
        connection.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)',
            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, datetime.now(timezone.utc).isoformat()))
        if not schema_shapes_valid(connection):
            raise RuntimeError('connector schema invalid')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {'connectors_created': 0}
