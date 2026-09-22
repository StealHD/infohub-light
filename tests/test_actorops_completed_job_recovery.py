import asyncio
from types import SimpleNamespace

import httpx
import pytest

from src.services.actorops.completed_job_recovery import settle_completed_job_result
from src.services.actorops.reconciliation import ActorOpsReconciler
from src.services.actorops.runtime_control_flow import fallback_or_fail, fetch_disabled_route
from tests.test_actorops_recovery_budget import setup
from tests.test_actorops_v2_resilience import _repository


def test_successful_source_job_closes_unused_result_without_remote_or_publication(tmp_path):
    store, repo = setup(tmp_path)
    try:
        conn = repo.connection
        conn.execute("UPDATE fetch_jobs SET status='succeeded',attempts=50,max_attempts=3 WHERE id='job'")
        conn.commit()
        job = tuple(conn.execute("SELECT * FROM fetch_jobs WHERE id='job'").fetchone())
        before = repo.get_attempt('attempt-result-recovery')
        candidate = repo.get_candidate(before['candidate_id'])
        # This object has no remote methods: even resolve() must not be called.
        result = asyncio.run(ActorOpsReconciler(repo, object()).reconcile())
        assert result.settled == 1 and result.remote_reads == 0 and result.errors == 0
        after = repo.get_attempt(before['attempt_id'])
        assert after['status'] == 'cancelled'
        assert after['error_code'] == 'actorops_result_recovery_superseded'
        for key in ('cost_final', 'actual_cost_usd', 'remote_run_id', 'dataset_id', 'result_state'):
            assert after[key] == before[key]
        assert repo.get_candidate(before['candidate_id']) == candidate
        assert tuple(conn.execute("SELECT * FROM fetch_jobs WHERE id='job'").fetchone()) == job
        with repo.transaction():
            assert repo.fetch_blocking_code(route_id=after['route_id'], source_id=after['source_id']) is None
        assert asyncio.run(ActorOpsReconciler(repo, object()).reconcile()).scanned == 0
    finally:
        store.close()


@pytest.mark.parametrize('condition', ['running', 'failed', 'cancelled', 'cost_pending',
                                       'different_source', 'different_job', 'stale_generation'])
def test_completed_job_cleanup_requires_exact_settled_terminal_facts(tmp_path, condition):
    store, repo = setup(tmp_path, cost_final=condition != 'cost_pending')
    try:
        conn = repo.connection
        conn.execute("UPDATE fetch_jobs SET status='succeeded' WHERE id='job'")
        if condition in {'running', 'failed', 'cancelled'}:
            conn.execute("UPDATE fetch_jobs SET status=? WHERE id='job'", (condition,))
        elif condition == 'different_source':
            conn.execute("UPDATE fetch_jobs SET source_id=NULL WHERE id='job'")
        conn.commit()
        row = dict(repo.get_attempt('attempt-result-recovery'))
        if condition == 'different_job':
            conn.execute("UPDATE fetch_jobs SET id='other-job' WHERE id='job'")
            conn.commit()
            row = dict(repo.get_attempt('attempt-result-recovery'))
        if condition == 'stale_generation':
            row['generation'] -= 1
        assert not settle_completed_job_result(repo, row)
        assert repo.get_attempt(row['attempt_id'])['status'] == 'registered'
    finally:
        store.close()


@pytest.mark.parametrize('blocked_code', [None, 'actorops_result_recovery_required'])
def test_native_http_failure_keeps_original_error_and_queues_repair(tmp_path, blocked_code):
    store, repo, route, source = _repository(tmp_path)
    response = httpx.Response(404, request=httpx.Request('GET', 'https://example.com/feed'))
    error = httpx.HTTPStatusError('missing', request=response.request, response=response)

    async def fail(*args):
        raise error

    try:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            asyncio.run(fallback_or_fail(repo, adapter=SimpleNamespace(fetch_native_fallback=fail),
                target=None, window=None, snapshot=None, plan=SimpleNamespace(blocked_code=blocked_code),
                health=None, route_id=route, source_id=source, logical_job_id='job-native-error'))
        assert caught.value is error
        repair = repo.connection.execute('SELECT * FROM actor_route_repairs_v2').fetchone()
        assert repair['origin_job_id'] == 'job-native-error'
        if blocked_code:
            assert repair['error_code'] == blocked_code
        assert repo.connection.execute('SELECT count(*) FROM actor_attempts_v2').fetchone()[0] == 0
        events, _, _ = repo.resilience.execution_events(root_job_id='job-native-error')
        assert events[0]['phase'] == 'route_repair'
        # A deliberately disabled route must not be repaired merely because RSS failed.
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(fetch_disabled_route(repo, adapter=SimpleNamespace(fetch_native_fallback=fail),
                                             target=None, window=None, snapshot=None, health=None))
        assert repo.connection.execute('SELECT count(*) FROM actor_route_repairs_v2').fetchone()[0] == 1
    finally:
        store.close()
