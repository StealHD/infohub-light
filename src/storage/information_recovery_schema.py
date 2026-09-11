"""Explicit global 45; legacy previews are deliberately not confirmed."""
from datetime import datetime, timezone
from .agent_analysis_schema import ready as prerequisite_ready

TABLES = {
    'information_execution_state': '''binding_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
        mode TEXT NOT NULL, updated_at TEXT NOT NULL, filtered_json TEXT NOT NULL DEFAULT '[]', runtime_block TEXT ''',
    'information_refresh_requests': '''id TEXT PRIMARY KEY, binding_id TEXT NOT NULL,
        generation INTEGER NOT NULL, status TEXT NOT NULL, requested_at TEXT NOT NULL,
        completed_at TEXT, reason TEXT, changed INTEGER''',
    'information_preview_confirmations': '''preview_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
        confirmed_at TEXT NOT NULL, superseded_by TEXT''',
    'information_preview_requests': '''user_id TEXT NOT NULL, request_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, preview_id TEXT NOT NULL, PRIMARY KEY(user_id,request_id)''',
}


COLUMNS = {
    'information_execution_state': {'binding_id','generation','mode','updated_at','filtered_json','runtime_block'},
    'information_refresh_requests': {'id','binding_id','generation','status','requested_at','completed_at','reason','changed'},
    'information_preview_confirmations': {'preview_id','fingerprint','confirmed_at','superseded_by'},
    'information_preview_requests': {'user_id','request_id','fingerprint','preview_id'},
}


def ready(conn):
    return bool(conn.execute("SELECT 1 FROM schema_migrations WHERE version=45 AND name='information_recovery' AND checksum='information-recovery-v1'").fetchone()) and all(
        {row[1] for row in conn.execute(f'PRAGMA table_info({name})')} == columns for name,columns in COLUMNS.items())


def apply_migration(conn):
    if ready(conn):
        return
    if not prerequisite_ready(conn):
        raise ValueError('global 44 required')
    try:
        conn.execute('BEGIN IMMEDIATE')
        for name, columns in TABLES.items():
            conn.execute(f'CREATE TABLE {name} ({columns})')
        conn.execute('CREATE INDEX information_refresh_binding ON information_refresh_requests(binding_id,requested_at)')
        conn.execute('CREATE INDEX information_preview_fingerprint ON information_preview_confirmations(fingerprint)')
        conn.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(45,?,?,?)',
                     ('information_recovery', 'information-recovery-v1', datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
