"""Explicit global 43: durable, secret-free Agent revocation journal."""
from datetime import datetime, timezone
from .agent_access_schema import ready as prerequisite_ready


def ready(conn):
    marker = conn.execute("SELECT 1 FROM schema_migrations WHERE version=43 AND name='agent_cleanup' AND checksum='agent-cleanup-v1'").fetchone()
    columns = {row[1] for row in conn.execute('PRAGMA table_info(agent_cleanup)')}
    return bool(marker and columns == {'binding_id', 'user_id', 'workspace_id', 'actor_id', 'request_id',
                                      'snapshot', 'phase', 'error', 'revision', 'created_at', 'updated_at'})


def apply_migration(conn):
    if ready(conn):
        return
    if not prerequisite_ready(conn):
        raise ValueError('global 42 required')
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''CREATE TABLE agent_cleanup (
            binding_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
            actor_id TEXT NOT NULL, request_id TEXT, snapshot TEXT NOT NULL,
            phase TEXT NOT NULL, error TEXT, revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        conn.execute("CREATE UNIQUE INDEX agent_cleanup_pending ON agent_cleanup(user_id) WHERE phase!='complete'")
        conn.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(43,?,?,?)',
                     ('agent_cleanup', 'agent-cleanup-v1', datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
