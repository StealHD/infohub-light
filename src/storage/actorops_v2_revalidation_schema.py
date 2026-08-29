"""Global 34 trigger gate for evidence-backed Candidate revalidation."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_stability_schema import (
    migration_marker_exists as stability_marker,
    schema_shapes_valid as stability_shapes,
)


MIGRATION_VERSION = 34
MIGRATION_NAME = "actorops_v2_dataset_revalidation"
MIGRATION_CHECKSUM = "actorops-v2-dataset-revalidation-v2"
TRIGGER_NAME = "trg_actor_candidates_v2_transition"

TRIGGER_SQL = f"""
CREATE TRIGGER {TRIGGER_NAME}
BEFORE UPDATE OF lifecycle ON actor_candidates_v2
WHEN NEW.lifecycle != OLD.lifecycle AND NOT (
    (OLD.lifecycle = 'discovered' AND NEW.lifecycle IN ('mapping_pending','static_valid','rejected')) OR
    (OLD.lifecycle = 'mapping_pending' AND NEW.lifecycle IN ('static_valid','rejected')) OR
    (OLD.lifecycle = 'static_valid' AND NEW.lifecycle IN ('probationary','rejected','disabled')) OR
    (OLD.lifecycle = 'probationary' AND NEW.lifecycle IN ('certified','quarantined','disabled','superseded')) OR
    (OLD.lifecycle = 'certified' AND NEW.lifecycle IN ('quarantined','disabled','superseded')) OR
    (OLD.lifecycle = 'rejected' AND NEW.lifecycle IN ('static_valid','probationary')
      AND OLD.assignment_role = 'inactive' AND NEW.assignment_role = 'inactive'
      AND OLD.last_error_code IN (
        'actorops_replacement_contract_mismatch',
        'actorops_replacement_published_at_invalid',
        'actorops_replacement_target_identity_mismatch',
        'actorops_replacement_output_url_invalid',
        'actorops_replacement_output_outside_window'
      )
      AND NEW.last_error_class IS NULL AND NEW.last_error_code IS NULL
      AND EXISTS (
        SELECT 1 FROM actor_attempts_v2 AS proof
        WHERE proof.workspace_id = NEW.workspace_id
          AND proof.candidate_id = NEW.candidate_id
          AND proof.kind = 'probe' AND proof.status = 'succeeded'
          AND proof.cost_final = 1 AND proof.actual_cost_usd = 0
          AND proof.remote_run_id IS NULL AND proof.dataset_id IS NOT NULL
          AND proof.logical_job_id LIKE 'revalidate:%'
          AND (
            (NEW.lifecycle = 'probationary' AND proof.semantic_outcome = 'valid_nonempty') OR
            (NEW.lifecycle = 'static_valid' AND proof.semantic_outcome = 'no_evidence')
          )
      )
      AND (
        (NEW.lifecycle = 'probationary' AND NEW.last_success_at IS NOT NULL
          AND (OLD.last_failure_at IS NULL OR NEW.last_success_at > OLD.last_failure_at)) OR
        (NEW.lifecycle = 'static_valid' AND NEW.last_success_at IS OLD.last_success_at)
      ))
)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_candidate_transition'); END;
"""


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    return stability_marker(connection) and stability_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (TRIGGER_NAME,),
    ).fetchone()
    sql = "".join(str(row[0] if row else "").lower().split())
    return bool(
        prerequisite_ready(connection)
        and "old.lifecycle='rejected'andnew.lifecyclein('static_valid','probationary')" in sql
        and "new.last_success_atisnotnull" in sql
        and "new.last_error_codeisnull" in sql
        and "proof.semantic_outcome='no_evidence'" in sql
    )


def apply_migration(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.in_transaction:
        raise RuntimeError("ActorOps revalidation migration requires a committed connection")
    existing = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None:
        existing_name = existing["name"] if isinstance(existing, sqlite3.Row) else existing[0]
        existing_checksum = existing["checksum"] if isinstance(existing, sqlite3.Row) else existing[1]
    if existing is not None and (
        str(existing_name) != MIGRATION_NAME
        or str(existing_checksum) != MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 34 is already occupied")
    if migration_marker_exists(connection):
        if not schema_shapes_valid(connection):
            raise RuntimeError("ActorOps revalidation marker exists with an invalid trigger")
        return {"candidate_transition_trigger_replaced": 0}
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 33 is required before ActorOps revalidation")
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME}")
        connection.execute(TRIGGER_SQL)
        connection.execute(
            "INSERT INTO schema_migrations (version,name,checksum,applied_at) VALUES (?,?,?,?)",
            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, stamp),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    if not schema_shapes_valid(connection):
        raise RuntimeError("ActorOps revalidation trigger validation failed")
    return {"candidate_transition_trigger_replaced": 1}


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool,
) -> None:
    if not existing_schema:
        apply_migration(connection)


__all__ = [
    "MIGRATION_CHECKSUM", "MIGRATION_NAME", "MIGRATION_VERSION", "TRIGGER_NAME",
    "apply_migration", "bootstrap_service_store_schema",
    "migration_marker_exists", "prerequisite_ready", "schema_shapes_valid",
]
