"""Explicit global 46 catalog identities; never adopt or rewrite legacy rows."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from .information_recovery_schema import ready as prerequisite_ready

MIGRATION_VERSION = 46
MIGRATION_NAME = "source_identity"
MIGRATION_CHECKSUM = "source-identity-v1"
LEGACY_INDEX = "idx_source_catalog_workspace_source_key"
REFERENCE_INDEX = "idx_source_catalog_workspace_id"
REFERENCE_SQL = f"CREATE UNIQUE INDEX {REFERENCE_INDEX} ON source_catalog(workspace_id, id)"
LEGACY_SQL = f"""CREATE UNIQUE INDEX {LEGACY_INDEX}
    ON source_catalog(workspace_id, source_key)
    WHERE source_key IS NOT NULL AND source_key != ''"""
INDEX_SQL = {
    "idx_source_catalog_private_identity": """CREATE UNIQUE INDEX idx_source_catalog_private_identity
        ON source_catalog(workspace_id, owner_user_id, source_key)
        WHERE scope = 'private' AND source_key IS NOT NULL AND source_key != ''""",
    "idx_source_catalog_shared_identity": """CREATE UNIQUE INDEX idx_source_catalog_shared_identity
        ON source_catalog(workspace_id, source_key)
        WHERE scope IN ('public', 'workspace') AND source_key IS NOT NULL AND source_key != ''""",
}
# Existing account deletion retains a fully sanitized disabled source tombstone.
INVALID_OWNER_SQL = """({row}owner_user_id IS NULL OR typeof({row}owner_user_id) != 'text'
    OR trim({row}owner_user_id) = '') AND NOT (
    {row}owner_user_id IS NULL AND {row}source_key IS NULL AND {row}enabled=0
    AND {row}config_json='{{}}' AND {row}secret_env IS NULL
    AND {row}display_name='Deleted account source' AND {row}description=''
    AND {row}default_channel IS NULL AND {row}default_topics_json='[]')"""
TRIGGER_SQL = {
    f"source_catalog_private_owner_{event.lower()}": f"""CREATE TRIGGER source_catalog_private_owner_{event.lower()}
        BEFORE {event} ON source_catalog
        WHEN NEW.scope = 'private' AND
            {INVALID_OWNER_SQL.format(row='NEW.')}
        BEGIN SELECT RAISE(ABORT, 'private source owner is required'); END"""
    for event in ("INSERT", "UPDATE")
}


class SourceIdentityMigrationRequiredError(RuntimeError):
    code = "source_identity_migration_required"

    def __init__(self):
        super().__init__("Source identity migration is required")


def _normalized(sql):
    tokens = re.split(r"('(?:''|[^'])*')", str(sql or ""))
    return "".join(token if index % 2 else re.sub(r"\s+", "", token.lower().replace("if not exists", ""))
                   for index, token in enumerate(tokens)).rstrip(";")


def _objects(conn):
    return {row[0]: (row[1], row[2]) for row in conn.execute(
        "SELECT name, type, sql FROM sqlite_master WHERE tbl_name='source_catalog'")}


def _unknown_unique_indexes(conn):
    known = {LEGACY_INDEX, *INDEX_SQL}
    reference = _objects(conn).get(REFERENCE_INDEX)
    if reference and reference[0] == "index" and _normalized(reference[1]) == _normalized(REFERENCE_SQL):
        known.add(REFERENCE_INDEX)
    return sum(1 for row in conn.execute("PRAGMA index_list(source_catalog)")
               if row[2] and row[1] not in known and row[3] != "pk")


def schema_shapes_valid(conn):
    objects = _objects(conn)
    expected = {**INDEX_SQL, **TRIGGER_SQL}
    return (LEGACY_INDEX not in objects and not _unknown_unique_indexes(conn)
        and all(name in objects and objects[name][0] == ("index" if name in INDEX_SQL else "trigger")
            and _normalized(objects[name][1]) == _normalized(sql) for name, sql in expected.items()))


def ready(conn) -> bool:
    try:
        marker = conn.execute("SELECT name, checksum FROM schema_migrations WHERE version=?",
                              (MIGRATION_VERSION,)).fetchone()
        return bool(marker and tuple(marker) == (MIGRATION_NAME, MIGRATION_CHECKSUM)
                    and schema_shapes_valid(conn))
    except sqlite3.DatabaseError:
        return False


def require_ready(conn):
    if not ready(conn):
        raise SourceIdentityMigrationRequiredError()


def invalid_row_counts(conn):
    invalid = conn.execute(f"""SELECT count(*) FROM source_catalog WHERE
        scope NOT IN ('private','public','workspace') OR scope IS NULL OR
        (scope='private' AND ({INVALID_OWNER_SQL.format(row='')}))""").fetchone()[0]
    duplicates = conn.execute("""SELECT count(*) FROM (
        SELECT 1 FROM source_catalog WHERE source_key IS NOT NULL AND source_key!=''
        GROUP BY workspace_id, CASE WHEN scope='private' THEN owner_user_id ELSE NULL END,
            CASE WHEN scope='private' THEN 'private' ELSE 'shared' END, source_key
        HAVING count(*)>1)""").fetchone()[0]
    return {"invalid_sources": invalid, "duplicate_identities": duplicates}


def preflight(conn, *, fresh=False):
    """Read-only shape/data validation; exceptions never include source identifiers."""
    marker = conn.execute("SELECT name, checksum FROM schema_migrations WHERE version=?",
                          (MIGRATION_VERSION,)).fetchone()
    if marker is not None:
        if not ready(conn):
            raise ValueError("source identity marker or schema is invalid")
        return {"status": "already_migrated", "blocker_counts": {}}
    if not prerequisite_ready(conn):
        raise ValueError("valid global 45 is required")
    objects = _objects(conn)
    if any(name in objects for name in (*INDEX_SQL, *TRIGGER_SQL)):
        raise ValueError("partial source identity schema requires operator review")
    if _unknown_unique_indexes(conn):
        raise ValueError("unknown source identity indexes require operator review")
    legacy = objects.get(LEGACY_INDEX)
    if not fresh and (not legacy or legacy[0] != "index" or _normalized(legacy[1]) != _normalized(LEGACY_SQL)):
        raise ValueError("legacy source identity index is missing or invalid")
    counts = invalid_row_counts(conn)
    return {"status": "blocked" if any(counts.values()) else "migration_required", "blocker_counts": counts}


def _integrity_check(conn):
    if (conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or conn.execute("PRAGMA foreign_key_check").fetchone()):
        raise ValueError("database integrity check failed")


def apply_migration(conn, *, fresh=False) -> None:
    """Install atomically, rechecking under the write lock; caller owns offline backup."""
    if conn.in_transaction:
        raise ValueError("source identity migration requires an independent transaction")
    try:
        conn.execute("BEGIN IMMEDIATE")
        state = preflight(conn, fresh=fresh)
        if state["status"] == "already_migrated":
            conn.rollback()
            return
        if state["status"] == "blocked":
            raise ValueError(f"source identity migration blocked: {state['blocker_counts']}")
        _integrity_check(conn)
        if not fresh:
            conn.execute(f"DROP INDEX {LEGACY_INDEX}")
        for sql in (*INDEX_SQL.values(), *TRIGGER_SQL.values()):
            conn.execute(sql)
        conn.execute("INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, datetime.now(timezone.utc).isoformat()))
        _integrity_check(conn)
        require_ready(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def bootstrap(conn, *, existing_schema):
    if not existing_schema:
        apply_migration(conn, fresh=True)
