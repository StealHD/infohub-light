"""CAS-only legacy Actor cost mutations used by the offline audit."""

from __future__ import annotations

import sqlite3
from typing import Protocol


class LegacyCostMutationError(RuntimeError):
    pass


class LegacyFact(Protocol):
    identity: str
    status: str
    updated_at: str


def settle_run(
    connection: sqlite3.Connection, fact: LegacyFact, amount: float, stamp: str
) -> None:
    run_id = fact.identity.split(":", 2)[1]
    changed = connection.execute(
        """UPDATE apify_actor_runs SET charge_actual_usd=?, charge_final=1, updated_at=?
           WHERE id=? AND status=? AND updated_at=? AND charge_final=0
             AND remote_run_id IS NOT NULL""",
        (amount, stamp, run_id, fact.status, fact.updated_at),
    ).rowcount
    if changed != 1:
        raise LegacyCostMutationError("legacy run changed before exact settlement")
    connection.execute(
        """UPDATE apify_actor_attempts SET actual_cost_usd=?, cost_final=1, updated_at=?
           WHERE id=(SELECT logical_run_id FROM apify_actor_runs WHERE id=?)
             AND status IN ('succeeded','valid_empty','actor_failed','target_failed','failed','cancelled')
             AND cost_final=0""",
        (amount, stamp, run_id),
    )


def quarantine_run(
    connection: sqlite3.Connection, fact: LegacyFact, stamp: str, code: str
) -> None:
    run_id = fact.identity.split(":", 2)[1]
    changed = connection.execute(
        """UPDATE apify_actor_runs SET last_error_code=?, updated_at=?
           WHERE id=? AND status=? AND updated_at=? AND charge_final=0
             AND remote_run_id IS NOT NULL
             AND COALESCE(last_error_code, '') != ?""",
        (code, stamp, run_id, fact.status, fact.updated_at, code),
    ).rowcount
    if changed != 1:
        raise LegacyCostMutationError("legacy run changed before quarantine")
    connection.execute(
        """UPDATE apify_actor_attempts SET last_error_code=?, updated_at=?
           WHERE id=(SELECT logical_run_id FROM apify_actor_runs WHERE id=?)
             AND status IN ('succeeded','valid_empty','actor_failed','target_failed','failed','cancelled')
             AND cost_final=0""",
        (code, stamp, run_id),
    )


def quarantine_attempt(
    connection: sqlite3.Connection, fact: LegacyFact, stamp: str, code: str
) -> None:
    attempt_id = fact.identity.split(":", 1)[1]
    changed = connection.execute(
        """UPDATE apify_actor_attempts SET last_error_code=?, updated_at=?
           WHERE id=? AND status=? AND updated_at=? AND cost_final=0
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_runs AS run
                 WHERE run.logical_run_id=apify_actor_attempts.id
                   AND run.remote_run_id IS NOT NULL
             )
             AND COALESCE(last_error_code, '') != ?""",
        (code, stamp, attempt_id, fact.status, fact.updated_at, code),
    ).rowcount
    if changed != 1:
        raise LegacyCostMutationError("legacy attempt changed before quarantine")


def quarantine_batch(
    connection: sqlite3.Connection, fact: LegacyFact, stamp: str, code: str
) -> None:
    batch_id = fact.identity.split(":", 1)[1]
    connection.execute(
        """UPDATE apify_actor_validations SET status='failed', semantic_outcome=?, completed_at=COALESCE(completed_at, ?)
           WHERE validation_id IN (SELECT validation_id FROM apify_actor_canary_batch_items WHERE batch_id=?)
             AND status IN ('queued','running')""",
        (code, stamp, batch_id),
    )
    connection.execute(
        """UPDATE apify_actor_canary_batch_items SET status='failed', semantic_outcome=?, completed_at=COALESCE(completed_at, ?), updated_at=?
           WHERE batch_id=? AND status IN ('planned','preflight_passed','queued','running','blocked_unknown_start')""",
        (code, stamp, stamp, batch_id),
    )
    changed = connection.execute(
        """UPDATE apify_actor_canary_batches SET status='partial', stop_reason=?, completed_at=COALESCE(completed_at, ?), updated_at=?
           WHERE batch_id=? AND status=? AND updated_at=?
             AND NOT EXISTS (
                 SELECT 1 FROM fetch_jobs
                 WHERE job_type='apify_actor_canary_batch' AND status IN ('queued','running')
                   AND json_valid(payload_json)
                   AND json_extract(payload_json, '$.batch_id')=apify_actor_canary_batches.batch_id
             )
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_canary_batch_items AS item
                 JOIN apify_actor_validations AS validation
                   ON validation.workspace_id=item.workspace_id AND validation.validation_id=item.validation_id
                 JOIN apify_actor_runs AS run ON run.logical_run_id=validation.attempt_id
                 WHERE item.batch_id=apify_actor_canary_batches.batch_id
                   AND run.status IN ('reserved','starting','running','aborting','start_outcome_unknown')
             )""",
        (code, stamp, stamp, batch_id, fact.status, fact.updated_at),
    ).rowcount
    if changed != 1:
        raise LegacyCostMutationError("legacy batch changed before quarantine")


__all__ = [
    "LegacyCostMutationError",
    "quarantine_attempt",
    "quarantine_batch",
    "quarantine_run",
    "settle_run",
]
