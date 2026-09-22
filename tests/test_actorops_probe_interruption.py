import asyncio
import json

import pytest

from src.services.actorops.domain import AttemptStatus
from src.services.actorops.probe_recovery import close_created_probe
from src.services.actorops.reconciliation import ActorOpsReconciler
from tests.test_actorops_v2_maintenance import _repository, _authorize, _prober, _Preflight
from tests.test_actorops_v2_reconciliation import _Ledger, _job
from src.services.actorops.ports import ReconciliationRunResolution


class BeforeStartFailure:
    calls = 0

    async def execute(self, request, events):
        self.calls += 1
        raise ConnectionError('secret upstream text must not become a job error')


def test_probe_before_start_failure_releases_reservation_without_changing_candidate(tmp_path):
    store, repo, route, source = _repository(tmp_path)
    try:
        _authorize(repo, route)
        before = repo.get_candidate('candidate')
        remote = BeforeStartFailure()
        prober = _prober(repo, remote, _Preflight())
        args = dict(route_id=route, candidate_id='candidate', source_id=source,
                    source_config={'target': 'openai'}, maintenance_slot='failed-start')
        result = asyncio.run(prober.probe(**args))
        attempt = repo.get_attempt(result.attempt_id)
        assert result.error_code == 'actorops_maintenance_remote_failed'
        assert attempt['status'] == 'cancelled'
        assert attempt['cost_final'] == 1 and attempt['actual_cost_usd'] == 0
        assert repo.get_candidate('candidate') == before
        asyncio.run(prober.probe(**args))
        assert remote.calls == 1
    finally:
        store.close()


def create_probe(repo, route, source, *, owner='owner', state='created'):
    with repo.transaction():
        repo.create_attempt(attempt_id='interrupted', idempotency_key='interrupted',
            route_id=route, source_id=source, candidate_id='candidate', kind='probe',
            attempt_group_id='maintenance:slot', attempt_index=0,
            route_generation=repo.get_route(route).generation, binding_version=1,
            target_fingerprint=repo.get_binding(source).target_fingerprint,
            reserved_usd=.05, logical_job_id=owner, request_fingerprint='a' * 64)
        if state == 'starting':
            repo.transition_attempt('interrupted', AttemptStatus.CREATED, AttemptStatus.STARTING)


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('job_status', ['failed', 'running', 'queued', 'cancelled'])
def test_only_terminal_exact_probe_owner_can_reconcile(tmp_path, legacy, job_status):
    store, repo, route, source = _repository(tmp_path)
    try:
        create_probe(repo, route, source, owner='maintenance:slot' if legacy else 'owner')
        _job(store, 'owner', status=job_status)
        repo.connection.execute("UPDATE fetch_jobs SET job_type='actorops_v2_maintenance',result_json=? WHERE id='owner'",
                                (json.dumps({'attempt_id': 'interrupted'}) if legacy else None,))
        repo.connection.commit()
        ledger = _Ledger({})  # No remote read is necessary for no reservation.
        result = asyncio.run(ActorOpsReconciler(repo, ledger).reconcile())
        assert result.settled == int(job_status in ('failed', 'cancelled'))
        row = repo.get_attempt('interrupted')
        assert bool(row['cost_final']) == (job_status in ('failed', 'cancelled'))
        assert ledger.reads == []
        assert asyncio.run(ActorOpsReconciler(repo, ledger).reconcile()).settled == 0
    finally:
        store.close()


def test_created_probe_preserves_existing_validation_reservation(tmp_path):
    store, repo, route, source = _repository(tmp_path)
    try:
        create_probe(repo, route, source)
        repo.connection.execute("""INSERT INTO apify_actor_runs
            (id,workspace_id,logical_run_id,secret_id,secret_version,pool_generation,status,
             created_at,updated_at,charge_reserved_usd,charge_final,purpose)
            VALUES ('reservation',?,'interrupted','secret',1,1,'reserved',
                    '2026-09-21T00:00:00+00:00','2026-09-21T00:00:00+00:00',.05,0,'validation')""",
            (repo.workspace_id,))
        repo.connection.commit()
        assert close_created_probe(repo, 'interrupted', error_code='actorops_probe_interrupted')
        row = repo.get_attempt('interrupted')
        assert row['status'] == 'cancelled' and row['cost_final'] == 0
        assert row['actual_cost_usd'] is None
        assert not close_created_probe(repo, 'interrupted', error_code='actorops_probe_interrupted')
        assert len(repo.list_reconcilable_attempts(limit=10)) == 1
    finally:
        store.close()


def test_crashed_starting_probe_enters_ledger_recovery_without_new_start(tmp_path):
    store, repo, route, source = _repository(tmp_path)
    try:
        create_probe(repo, route, source, state='starting')
        _job(store, 'owner', status='failed')
        repo.connection.execute("UPDATE fetch_jobs SET job_type='actorops_v2_maintenance' WHERE id='owner'")
        repo.connection.commit()
        ledger = _Ledger({'interrupted': ReconciliationRunResolution(None, reservation_absent=True)})
        result = asyncio.run(ActorOpsReconciler(repo, ledger).reconcile())
        assert result.pending == 1
        assert repo.get_attempt('interrupted')['cost_final'] == 0
        assert ledger.reads == []
    finally:
        store.close()
