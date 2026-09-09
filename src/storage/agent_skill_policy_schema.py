"""Global 41: workspace Skill allowlists and per-binding synchronization state."""

from datetime import datetime, timezone

from .information_unified_schema import ready as prerequisite_ready

MIGRATION_VERSION = 41
MIGRATION_NAME = "workspace_agent_skill_policy"
MIGRATION_CHECKSUM = "workspace-agent-skill-policy-v1"

TABLES = {
    "workspace_agent_skill_policies": """CREATE TABLE workspace_agent_skill_policies (
        workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        allowed_skill_keys_json TEXT NOT NULL,
        sync_state TEXT NOT NULL CHECK(sync_state IN ('pending','synced','failed')),
        sync_error_code TEXT,
        sync_attempt_id TEXT,
        updated_at TEXT NOT NULL,
        synced_at TEXT)""",
    "agent_skill_policy_syncs": """CREATE TABLE agent_skill_policy_syncs (
        binding_id TEXT PRIMARY KEY REFERENCES agent_connections(binding_id) ON DELETE CASCADE,
        workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        policy_revision INTEGER NOT NULL CHECK(policy_revision >= 1),
        state TEXT NOT NULL CHECK(state IN ('pending','synced','failed')),
        updated_at TEXT NOT NULL)""",
}


def migration_marker_exists(connection):
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection):
    normalize = lambda value: " ".join((value or "").lower().split())
    for name, sql in TABLES.items():
        row = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if not row or normalize(row[0]) != normalize(sql):
            return False
    return prerequisite_ready(connection)


def ready(connection):
    return migration_marker_exists(connection) and schema_shapes_valid(connection)


def apply_migration(connection):
    if connection.in_transaction:
        raise RuntimeError("agent skill policy migration requires a committed connection")
    row = connection.execute(
        "SELECT name,checksum FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    if row:
        if tuple(row) != (MIGRATION_NAME, MIGRATION_CHECKSUM) or not schema_shapes_valid(connection):
            raise RuntimeError("global 41 marker or schema conflict")
        return {"workspaces_initialized": 0, "bindings_initialized": 0}
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global 40 is required")
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        for sql in TABLES.values():
            connection.execute(sql)
        workspaces = connection.execute(
            """INSERT INTO workspace_agent_skill_policies
               SELECT id,1,'[]','pending',NULL,NULL,?,NULL FROM workspaces""", (now,)
        ).rowcount
        bindings = connection.execute(
            """INSERT INTO agent_skill_policy_syncs
               SELECT binding_id,workspace_id,1,'pending',? FROM agent_connections
               WHERE state<>'revoked'""", (now,)
        ).rowcount
        connection.execute(
            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, now),
        )
        if not schema_shapes_valid(connection) or connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("agent skill policy migration validation failed")
        connection.commit()
        return {"workspaces_initialized": workspaces, "bindings_initialized": bindings}
    except Exception:
        connection.rollback()
        raise
