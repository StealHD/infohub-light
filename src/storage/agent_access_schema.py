"""Explicit global 42 migration for personal Agent access requests."""
from datetime import datetime, timezone
from .agent_skill_policy_schema import migration_marker_exists as prerequisite_ready

VERSION, NAME, CHECKSUM = 42, 'agent_access_requests', 'agent-access-requests-v1'


def ready(conn):
    marker = conn.execute('SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?',
                          (VERSION, NAME, CHECKSUM)).fetchone()
    columns = {row[1] for row in conn.execute('PRAGMA table_info(agent_access_requests)')}
    return bool(marker and columns == {'id','workspace_id','user_id','state','revision','created_at',
                                      'reviewer_id','reviewed_at','reason','phase','error','binding_id'})


def apply_migration(conn):
    if ready(conn):
        return
    if not prerequisite_ready(conn):
        raise RuntimeError('global 41 required')
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''CREATE TABLE agent_access_requests (
          id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          state TEXT NOT NULL CHECK(state IN ('pending','approved','rejected','ready')),
          revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
          reviewer_id TEXT REFERENCES users(id) ON DELETE SET NULL, reviewed_at TEXT,
          reason TEXT, phase TEXT, error TEXT, binding_id TEXT)''')
        conn.execute("CREATE UNIQUE INDEX agent_access_open ON agent_access_requests(user_id) WHERE state IN ('pending','approved')")
        conn.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)',
                     (VERSION, NAME, CHECKSUM, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
