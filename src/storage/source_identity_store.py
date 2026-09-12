"""Parameterized identity and visibility queries for source catalog records."""
from __future__ import annotations


def validate_identity(scope, owner_user_id):
    if scope not in {"private", "public", "workspace"}:
        raise ValueError("source scope is invalid")
    if scope == "private" and (not isinstance(owner_user_id, str) or not owner_user_id.strip()):
        raise ValueError("private source owner is required")


def find_identity(conn, *, workspace_id, source_key, scope, owner_user_id=None):
    validate_identity(scope, owner_user_id)
    if scope == "private":
        return conn.execute("""SELECT * FROM source_catalog WHERE workspace_id=?
            AND source_key=? AND scope='private' AND owner_user_id=?""",
            (workspace_id, source_key, owner_user_id)).fetchone()
    return conn.execute("""SELECT * FROM source_catalog WHERE workspace_id=?
        AND source_key=? AND scope IN ('public','workspace')""",
        (workspace_id, source_key)).fetchone()


def visible_identities(conn, user, source_key):
    return conn.execute("""SELECT * FROM source_catalog WHERE workspace_id=?
        AND source_key=? AND (scope IN ('public','workspace')
            OR (scope='private' AND owner_user_id=?)) ORDER BY scope, id""",
        (user["workspace_id"], source_key, user["id"])).fetchall()


def is_identity_conflict(error):
    message = str(error)
    return ("UNIQUE constraint failed: source_catalog.workspace_id" in message
            and "source_catalog.source_key" in message)
