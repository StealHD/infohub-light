"""No-start recovery preserves Job idempotency and does not condemn an Actor."""

import asyncio
from datetime import datetime, timezone

import pytest

from src.services.actorops.domain import AttemptStatus, FailureClass
from src.services.actorops.errors import ActorOpsRuntimeError
from src.services.actorops.ports import FetchWindow
from tests.test_actorops_v2_runtime import _runtime


def test_confirmed_no_start_keeps_history_and_next_job_can_use_same_actor(tmp_path):
    store, repo, runtime, remote, route, source, candidates = _runtime(
        tmp_path,
        [ActorOpsRuntimeError('apify_start_outcome_unknown',
                             failure_class=FailureClass.REMOTE_UNKNOWN), 'valid_nonempty'],
        candidate_count=1,
    )
    args = dict(route_id=route, source_id=source, source_config={'target': 'openai'},
                window=FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None))
    try:
        with pytest.raises(ActorOpsRuntimeError, match='apify start outcome unknown'):
            asyncio.run(runtime.fetch(**args, logical_job_id='job'))
        with repo.transaction():
            row = repo.get_attempt('id-0')
            repo.reconcile_attempt(
                'id-0', expected_status=AttemptStatus(str(row['status'])),
                expected_generation=int(row['generation']), target_status=AttemptStatus.FAILED,
                remote_run_id=None, dataset_id=None, semantic_outcome='actorops_proven_no_start',
                actual_cost_usd=0.0, cost_final=True, failure_class='remote_unknown',
                error_code='actorops_proven_no_start',
            )
        before = dict(repo.get_attempt('id-0'))
        repairs = [dict(row) for row in repo.connection.execute('SELECT * FROM actor_route_repairs_v2')]
        for _ in range(2):
            with pytest.raises(ActorOpsRuntimeError) as caught:
                asyncio.run(runtime.fetch(**args, logical_job_id='job'))
            assert caught.value.code == 'apify_request_not_started'
            assert caught.value.failure_class is FailureClass.INTERNAL
            assert caught.value.retryable is False
        assert len(remote.requests) == 1
        assert [dict(row) for row in repo.connection.execute('SELECT * FROM actor_route_repairs_v2')] == repairs
        result = asyncio.run(runtime.fetch(**args, logical_job_id='next-scheduled-job'))
        assert len(result.items) == 1 and result.candidate_id == candidates[0]
        assert len(remote.requests) == 2
        assert dict(repo.get_attempt('id-0')) == before
        assert len(asyncio.run(runtime.fetch(**args, logical_job_id='next-scheduled-job')).items) == 1
        assert len(remote.requests) == 2
    finally:
        store.close()


def test_transport_failure_does_not_enqueue_actor_repair(tmp_path):
    store, repo, runtime, remote, route, source, _ = _runtime(
        tmp_path, [ActorOpsRuntimeError('apify_transport_unavailable',
                                       failure_class=FailureClass.INTERNAL)], candidate_count=1,
    )
    try:
        with pytest.raises(ActorOpsRuntimeError, match='apify transport unavailable'):
            asyncio.run(runtime.fetch(
                route_id=route, source_id=source, source_config={'target': 'openai'},
                window=FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
                logical_job_id='transport-failure',
            ))
        assert repo.connection.execute('SELECT count(*) FROM actor_route_repairs_v2').fetchone()[0] == 0
        assert len(remote.requests) == 1
    finally:
        store.close()
