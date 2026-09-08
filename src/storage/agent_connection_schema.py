"""Global 37: personal Agent bindings; existing databases require offline migration."""
import sqlite3
from datetime import datetime, timezone

MIGRATION_VERSION = 37
MIGRATION_NAME = "personal_agent_connections"
MIGRATION_CHECKSUM = "personal-agent-connections-v1"
REQUIRED_TABLES = {"agent_connections"}
_COLUMNS = {"user_id", "workspace_id", "binding_id", "agent_id", "mcp_server", "secret_ref",
            "delegation_id", "manifest_json", "state", "verified_at", "created_at"}
_SQL = """CREATE TABLE agent_connections (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    binding_id TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL UNIQUE,
    mcp_server TEXT NOT NULL UNIQUE,
    secret_ref TEXT NOT NULL UNIQUE,
    delegation_id TEXT UNIQUE REFERENCES agent_delegations(id) ON DELETE SET NULL,
    manifest_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','active','revoked')),
    verified_at TEXT,
    created_at TEXT NOT NULL
)"""


def prerequisite_ready(connection):
    from .actorops_v2_verified_replacement_schema import migration_marker_exists, schema_shapes_valid
    return migration_marker_exists(connection) and schema_shapes_valid(connection)


def migration_marker_exists(connection):
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_connections)")}
    fks = {(r[3], r[2], r[4], r[6]) for r in connection.execute("PRAGMA foreign_key_list(agent_connections)")}
    unique_columns = set()
    for index in connection.execute("PRAGMA index_list(agent_connections)"):
        if index[2]:
            # Index names come from SQLite, not callers.
            escaped = str(index[1]).replace('"', '""')
            unique_columns.add(tuple(r[2] for r in connection.execute(f'PRAGMA index_info("{escaped}")')))
    return (_COLUMNS == columns and prerequisite_ready(connection)
            and {("user_id", "users", "id", "CASCADE"),
                 ("workspace_id", "workspaces", "id", "CASCADE"),
                 ("delegation_id", "agent_delegations", "id", "SET NULL")} <= fks
            and all((col,) in unique_columns for col in (
                "user_id", "binding_id", "agent_id", "mcp_server", "secret_ref", "delegation_id")))


def apply_migration(connection):
    if connection.in_transaction:
        raise RuntimeError("agent migration requires a committed connection")
    row = connection.execute("SELECT name,checksum FROM schema_migrations WHERE version=37").fetchone()
    if row:
        if tuple(row) != (MIGRATION_NAME, MIGRATION_CHECKSUM) or not schema_shapes_valid(connection):
            raise RuntimeError("global 37 marker or schema conflict")
        return {"bindings_created": 0}
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 36 is required")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='agent_connections'").fetchone():
        raise RuntimeError("partial agent schema must be restored")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_SQL)
        connection.execute("INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
                           (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM,
                            datetime.now(timezone.utc).isoformat()))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"bindings_created": 0}
