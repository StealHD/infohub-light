"""Recover interrupted probes without repeating a paid start or guessing cost."""

from .domain import AttemptStatus, FailureClass


# A terminal owner is required; age alone never proves that execution stopped.
PROBE_OWNER_TERMINAL_SQL = """
    kind='probe' AND status IN ('created','starting') AND cost_final=0
    AND EXISTS (
        SELECT 1 FROM fetch_jobs AS job
        WHERE job.workspace_id=actor_attempts_v2.workspace_id
          AND job.job_type IN ('actorops_v2_maintenance','actorops_v2_replacement')
          AND job.status IN ('succeeded','failed','partial','cancelled')
          AND (job.id=actor_attempts_v2.logical_job_id
               OR json_extract(job.result_json, '$.attempt_id')=actor_attempts_v2.attempt_id)
    )
"""


def close_created_probe(repository, attempt_id, *, error_code, require_terminal_owner=False):
    """Called after execution exits, or after its durable owner is terminal."""
    with repository.transaction():
        row = repository.get_attempt(attempt_id)
        if row['kind'] != 'probe' or row['status'] != 'created':
            return False
        if require_terminal_owner and repository.connection.execute(
            f"SELECT 1 FROM actor_attempts_v2 WHERE workspace_id=? AND attempt_id=? AND ({PROBE_OWNER_TERMINAL_SQL})",
            (repository.workspace_id, attempt_id),
        ).fetchone() is None:
            return False
        reservation = repository.connection.execute(
            "SELECT 1 FROM apify_actor_runs WHERE workspace_id=? AND logical_run_id=? LIMIT 1",
            (repository.workspace_id, attempt_id),
        ).fetchone()
        # Credential acquisition may reserve a Run before events.starting.
        # Preserve that liability for the regular ledger reconciler.
        repository.reconcile_attempt(
            attempt_id, expected_status=AttemptStatus.CREATED,
            expected_generation=int(row['generation']), target_status=AttemptStatus.CANCELLED,
            remote_run_id=None, dataset_id=None, semantic_outcome=error_code,
            actual_cost_usd=0.0 if reservation is None else None,
            cost_final=reservation is None, failure_class=FailureClass.INTERNAL.value,
            error_code=error_code,
        )
    if reservation is None:
        repository.resilience.wake_repairs_after_cost_settlement(str(row['route_id']), row['source_id'])
    return True
