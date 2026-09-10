"""Explicit global 44: managed analysis installation state, without credentials."""
from datetime import datetime, timezone
from .agent_cleanup_schema import ready as prerequisite_ready


def ready(conn):
    marker = conn.execute("SELECT 1 FROM schema_migrations WHERE version=44 AND name='agent_analysis' AND checksum='agent-analysis-v1'").fetchone()
    columns = {row[1] for row in conn.execute('PRAGMA table_info(agent_analysis)')}
    return bool(marker and columns == {'binding_id', 'user_id', 'phase', 'objects_json', 'error', 'revision', 'updated_at'})


def apply_migration(conn):
    if ready(conn):
        return
    if not prerequisite_ready(conn):
        raise ValueError('global 43 required')
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''CREATE TABLE agent_analysis (
            binding_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL, phase TEXT NOT NULL, objects_json TEXT NOT NULL,
            error TEXT, revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)''')
        conn.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(44,?,?,?)',
                     ('agent_analysis', 'agent-analysis-v1', datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
