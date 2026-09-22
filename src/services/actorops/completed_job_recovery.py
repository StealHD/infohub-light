"""Close unused, settled results after their exact source job has succeeded."""

from .domain import AttemptStatus, FailureClass


def settle_completed_job_result(repository, row):
    with repository.transaction():
        current = repository.get_attempt(str(row['attempt_id']))
        if (current['generation'] != row['generation'] or current['kind'] != 'fetch'
                or current['status'] not in {'registered', 'running'}
                or current['result_state'] != 'observed' or not current['cost_final']
                or not current['remote_run_id'] or not current['dataset_id']):
            return False
        job = repository.connection.execute(
            """SELECT 1 FROM fetch_jobs WHERE workspace_id=? AND id=?
               AND source_id=? AND job_type='source_fetch' AND status='succeeded'""",
            (repository.workspace_id, current['logical_job_id'], current['source_id']),
        ).fetchone()
        if job is None:
            return False
        repository.reconcile_attempt(
            str(current['attempt_id']), expected_status=AttemptStatus(current['status']),
            expected_generation=int(current['generation']), target_status=AttemptStatus.CANCELLED,
            remote_run_id=None, dataset_id=None, actual_cost_usd=None, cost_final=True,
            semantic_outcome='actorops_result_recovery_superseded',
            failure_class=FailureClass.REMOTE_UNKNOWN.value,
            error_code='actorops_result_recovery_superseded',
        )
    repository.resilience.wake_repairs_after_cost_settlement(
        str(current['route_id']), str(current['source_id']))
    return True
