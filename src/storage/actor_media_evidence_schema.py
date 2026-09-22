"""Explicit additive global 48: optional, private media capability evidence."""

from datetime import datetime, timezone
from .notification_extension_schema import ready as prerequisite_ready

VERSION = 48
NAME = 'actor_media_evidence'
CHECKSUM = 'actor-media-evidence-v1'
TABLE = 'actor_media_evidence_v2'
SQL = '''CREATE TABLE actor_media_evidence_v2 (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    attempt_id TEXT NOT NULL REFERENCES actor_attempts_v2(attempt_id),
    source_id TEXT NOT NULL, binding_version INTEGER NOT NULL,
    candidate_id TEXT NOT NULL REFERENCES actor_candidates_v2(candidate_id),
    build_id TEXT NOT NULL, schema_hash TEXT NOT NULL, manifest_hash TEXT NOT NULL,
    parser_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('unknown','observed_multi','mapping_gap','upstream_incomplete')),
    reason TEXT NOT NULL, sample_count INTEGER NOT NULL CHECK(sample_count >= 0),
    media_count INTEGER NOT NULL CHECK(media_count >= 0), observed_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id,attempt_id,parser_version))'''
INDEX = '''CREATE INDEX actor_media_evidence_lookup ON actor_media_evidence_v2
    (workspace_id,source_id,binding_version,candidate_id,build_id,schema_hash,
     manifest_hash,parser_version,observed_at)'''
COLUMNS = {'workspace_id', 'attempt_id', 'source_id', 'binding_version', 'candidate_id',
           'build_id', 'schema_hash', 'manifest_hash', 'parser_version', 'status',
           'reason', 'sample_count', 'media_count', 'observed_at'}

PROVENANCE_SQL = """CREATE TABLE actor_output_schema_provenance_v2 (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    candidate_id TEXT NOT NULL REFERENCES actor_candidates_v2(candidate_id),
    origin TEXT NOT NULL CHECK(origin IN ('declared_fields','dataset_view','observed_dataset','unknown')),
    PRIMARY KEY(workspace_id,candidate_id))"""


def ready(conn):
    marker = conn.execute('SELECT name,checksum FROM schema_migrations WHERE version=?',
                          (VERSION,)).fetchone()
    return bool(marker and tuple(marker) == (NAME, CHECKSUM)) and {
        row[1] for row in conn.execute('PRAGMA table_info(actor_media_evidence_v2)')
    } == COLUMNS and {
        row[1] for row in conn.execute("PRAGMA table_info(actor_output_schema_provenance_v2)")
    } == {"workspace_id", "candidate_id", "origin"}


def apply_migration(conn):
    if conn.in_transaction:
        raise ValueError('media evidence migration requires a committed connection')
    if ready(conn):
        return
    if not prerequisite_ready(conn):
        raise ValueError('valid global 47 required')
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (VERSION,)).fetchone():
            raise ValueError('global 48 marker conflict')
        conn.execute(SQL)
        conn.execute(INDEX)
        conn.execute(PROVENANCE_SQL)
        conn.execute('INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)',
                     (VERSION, NAME, CHECKSUM, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
