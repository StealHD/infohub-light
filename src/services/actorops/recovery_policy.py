"""Keep result recovery inside the original Job's retry budget."""
from datetime import datetime, timedelta, timezone

from ..system_settings import resolve_system_setting
from .dataset_replay import PERMANENT_DATASET_ERRORS
from .domain import AttemptStatus, FailureClass
from .errors import ActorOpsRuntimeError


def stopped_recovery_code(row):
    for key in ('semantic_outcome', 'error_code'):
        code = str(row[key] or '')
        if code in PERMANENT_DATASET_ERRORS:
            return code
    return None


def raise_if_recovery_stopped(row):
    code = stopped_recovery_code(row)
    if code:
        raise ActorOpsRuntimeError(code, failure_class=FailureClass.REMOTE_UNKNOWN, retryable=False)


def record_recovery_error(repository, row, code):
    status = AttemptStatus(str(row['status']))
    terminal = code in PERMANENT_DATASET_ERRORS
    target = AttemptStatus.FAILED if terminal and status in {
        AttemptStatus.REGISTERED, AttemptStatus.RUNNING} else None
    repository.reconcile_attempt(
        str(row['attempt_id']), expected_status=status,
        expected_generation=int(row['generation']), target_status=target,
        remote_run_id=None, dataset_id=None, actual_cost_usd=None, cost_final=False,
        semantic_outcome=code if target else None,
        failure_class=FailureClass.REMOTE_UNKNOWN.value, error_code=code,
    )


def recovery_due(repository, attempt, job):
    if code := stopped_recovery_code(attempt):
        record_recovery_error(repository, attempt, code)
        return None
    attempts = int(job['attempts'])
    if attempts >= int(job['max_attempts']):
        record_recovery_error(repository, attempt, 'actorops_result_recovery_exhausted')
        return None
    base = float(resolve_system_setting(
        None, repository.workspace_id, 'jobs.retry_base_seconds',
        connection=repository.connection,
    ))
    ended = datetime.fromisoformat(str(job['finished_at'] or job['updated_at']).replace('Z', '+00:00'))
    delay = base * (2 ** min(max(attempts - 1, 0), 16))
    return max(datetime.now(timezone.utc), ended + timedelta(seconds=delay)).isoformat()
