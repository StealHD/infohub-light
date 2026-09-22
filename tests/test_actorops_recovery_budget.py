from datetime import datetime
import pytest
from src.services.actorops.reconciliation_lifecycle import recover_observed_result_after_terminal_job
from tests.test_actorops_v2_reconciliation import _repository, _job
from tests.test_actorops_v2_result_recovery import _observed_attempt


def setup(tmp_path, *, cost_final=True):
    store, repo, route = _repository(tmp_path)
    source = store.create_source(workspace_id='default', scope='workspace', owner_user_id=None,
                                 source_type='apify_social', display_name='Recovery',
                                 config={'platform': 'youtube', 'kind': 'channel', 'target': 'safe'})
    _job(store, 'job', status='failed', source_id=source)
    _observed_attempt(repo, route, source, job_id='job', cost_final=cost_final)
    return store, repo


@pytest.mark.parametrize('attempts', [3, 10])
def test_repeated_reconciliation_never_reopens_exhausted_job(tmp_path, attempts):
    store, repo = setup(tmp_path)
    store.connect().execute("UPDATE fetch_jobs SET attempts=?,max_attempts=3 WHERE id='job'", (attempts,))
    store.connect().commit()
    for _ in range(12):
        row = repo.get_attempt('attempt-result-recovery')
        assert recover_observed_result_after_terminal_job(repo, row) is None
    job = store.connect().execute("SELECT status,attempts FROM fetch_jobs WHERE id='job'").fetchone()
    assert tuple(job) == ('failed', attempts)
    row = repo.get_attempt('attempt-result-recovery')
    assert row['error_code'] == 'actorops_result_recovery_exhausted'
    assert row['status'] == 'failed'
    assert row['failure_class'] == 'remote_unknown'
    assert row['cost_final'] == 1 and row['actual_cost_usd'] == pytest.approx(0.000996)
    with repo.transaction():
        assert repo.fetch_blocking_code(route_id=row['route_id'], source_id=row['source_id']) is None
    generation = row['generation']
    assert repo.list_reconcilable_attempts() == ()
    assert repo.get_attempt('attempt-result-recovery')['generation'] == generation


def test_permanent_dataset_failure_does_not_requeue(tmp_path):
    store, repo = setup(tmp_path)
    store.connect().execute("UPDATE actor_attempts_v2 SET error_code='actorops_dataset_access_denied'")
    store.connect().commit()
    assert recover_observed_result_after_terminal_job(repo, repo.get_attempt('attempt-result-recovery')) is None
    assert repo.list_reconcilable_attempts() == ()


def test_recovery_queue_cas_preserves_budget_and_backoff(tmp_path):
    store, repo = setup(tmp_path)
    stamp = datetime.now().astimezone().isoformat()
    store.connect().execute("UPDATE fetch_jobs SET attempts=2,max_attempts=3,finished_at=? WHERE id='job'", (stamp,))
    store.connect().commit()
    row = repo.get_attempt('attempt-result-recovery')
    assert recover_observed_result_after_terminal_job(repo, row) == 'queued'
    assert recover_observed_result_after_terminal_job(repo, row) is None
    job = store.connect().execute("SELECT attempts,next_run_at FROM fetch_jobs WHERE id='job'").fetchone()
    assert job['attempts'] == 2
    assert (datetime.fromisoformat(job['next_run_at']) - datetime.fromisoformat(stamp)).total_seconds() >= 60


def test_permanent_result_failure_settles_cost_without_faulting_candidate(tmp_path):
    import asyncio
    from datetime import timedelta
    from src.services.actorops.recovery_policy import record_recovery_error, raise_if_recovery_stopped
    from src.services.actorops.errors import ActorOpsRuntimeError
    from src.services.actorops.reconciliation import ActorOpsReconciler
    from src.services.actorops.ports import ReconciliationRunResolution, ReconciliationRunObservation
    from tests.test_actorops_v2_reconciliation import _Ledger, _link
    store, repo = setup(tmp_path, cost_final=False)
    row = repo.get_attempt('attempt-result-recovery')
    candidate = repo.get_candidate(row['candidate_id'])
    with repo.transaction():
        record_recovery_error(repo, row, 'actorops_dataset_access_denied')
    failed = repo.get_attempt(row['attempt_id'])
    assert failed['status'] == 'failed' and failed['cost_final'] == 0
    with pytest.raises(ActorOpsRuntimeError) as caught:
        raise_if_recovery_stopped(failed)
    assert caught.value.retryable is False
    assert len(repo.list_reconcilable_attempts()) == 1
    ledger = _Ledger({row['attempt_id']: ReconciliationRunResolution(
        _link('reservation', remote='remote-result-recovery'))},
        {'reservation': ReconciliationRunObservation('succeeded', 0.002, True, 'dataset-result-recovery')})
    asyncio.run(ActorOpsReconciler(repo, ledger,
        now=lambda: datetime.fromisoformat(row['updated_at']) + timedelta(seconds=61)).reconcile())
    settled = repo.get_attempt(row['attempt_id'])
    assert settled['cost_final'] == 1 and settled['actual_cost_usd'] == 0.002
    assert settled['status'] == 'failed'
    assert settled['error_code'] == 'actorops_dataset_access_denied'
    assert repo.get_candidate(row['candidate_id']) == candidate
    assert repo.list_reconcilable_attempts() == ()
