"""Explicit global 49: private, disposable Feed translations."""

from datetime import datetime, timezone

from .actor_media_evidence_schema import ready as prerequisite_ready

VERSION = 49
NAME = "content_translations"
CHECKSUM = "content-translations-v1"
COLUMNS = {
    "content_translations": {"cache_key", "workspace_id", "user_id", "article_id", "job_id",
                             "translated_text", "scope", "source_truncated", "created_at", "expires_at"},
    "content_translation_requests": {"workspace_id", "user_id", "request_id", "cache_key", "job_id"},
}
SQL = (
    """CREATE TABLE content_translations (
        cache_key TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, article_id TEXT NOT NULL,
        job_id TEXT REFERENCES fetch_jobs(id) ON DELETE SET NULL,
        translated_text TEXT, scope TEXT NOT NULL CHECK(scope IN ('body','excerpt')),
        source_truncated INTEGER NOT NULL CHECK(source_truncated IN (0,1)),
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id,user_id,article_id)
            REFERENCES user_content_items(workspace_id,user_id,article_id) ON DELETE CASCADE)""",
    "CREATE INDEX content_translation_expiry ON content_translations(expires_at)",
    """CREATE TABLE content_translation_requests (
        workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, request_id TEXT NOT NULL,
        cache_key TEXT NOT NULL REFERENCES content_translations(cache_key) ON DELETE CASCADE,
        job_id TEXT REFERENCES fetch_jobs(id) ON DELETE SET NULL,
        PRIMARY KEY(workspace_id,user_id,request_id))""",
)


def ready(conn):
    marker = conn.execute(
        "SELECT name,checksum FROM schema_migrations WHERE version=?", (VERSION,)
    ).fetchone()
    return bool(marker and tuple(marker) == (NAME, CHECKSUM)) and all(
        expected == {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for table, expected in COLUMNS.items()
    ) and bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='content_translation_expiry'"
    ).fetchone())


def apply_migration(conn):
    if conn.in_transaction:
        raise ValueError("translation migration requires a committed connection")
    if ready(conn):
        return
    if not prerequisite_ready(conn):
        raise ValueError("valid global 48 required")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM fetch_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError("drain the job queue before applying migration")
        for sql in SQL:
            conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
            (VERSION, NAME, CHECKSUM, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
