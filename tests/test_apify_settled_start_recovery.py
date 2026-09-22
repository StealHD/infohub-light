"""Reproduce ActorOps settling first, leaving the acquisition pool blocked."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.services.actorops.apify_ledger import ApifyRunLedger
from src.services.actorops.ports import ReconciliationRunLink
from src.services.apify_pool_runtime import reconcile_apify_pool
from tests.test_apify_pool_runtime import _pool, _Quota


def settled_but_blocked(tmp_path):
    store, secrets, coordinator, refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id='fetch-proof')
    coordinator.report_start_outcome_unknown(lease, error_code='apify_restart_start_outcome_unknown')
    run = coordinator.get_run(lease.reservation_id)
    link = ReconciliationRunLink(
        reservation_id=lease.reservation_id, remote_run_id=None, dataset_id=None,
        status=run['status'], created_at=run['created_at'], updated_at=run['updated_at'],
    )
    asyncio.run(ApifyRunLedger(store, workspace_id=coordinator.workspace_id).settle_proven_no_start(link))
    assert coordinator.public_state(coordinator.workspace_id)['status'] == 'blocked'
    return store, coordinator, lease, refs


def test_normal_reconciliation_releases_settled_block_without_remote_calls(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_APIFY_KEY_POOL_ENABLED', 'true')
    store, coordinator, lease, _ = settled_but_blocked(tmp_path)
    before = dict(coordinator.get_run(lease.reservation_id))
    requests = []
    def reject_http(request):
        requests.append(request.method)
        raise AssertionError('settled proof needs no network or paid Run')
    try:
        state = asyncio.run(reconcile_apify_pool(
            coordinator, quota_service=_Quota(), http_transport=httpx.MockTransport(reject_http),
        ))
        assert state['status'] == 'ready' and not state['blocked_reason']
        assert coordinator.get_run(lease.reservation_id) == before
        generation = state['generation']
        coordinator.reconcile_settled_unknown_start_block()
        assert coordinator.public_state(coordinator.workspace_id)['generation'] == generation
        assert not requests
        # The same active credential is usable again; no forced key/Actor switch.
        next_lease = coordinator.acquire_credential(logical_run_id='next-normal-fetch')
        assert next_lease.secret_id == lease.secret_id
    finally:
        store.close()


@pytest.mark.parametrize('case', [
    'unknown_reason', 'newer_block', 'nonzero_cost', 'unsettled_cost', 'reserved_cost',
    'known_run', 'wrong_key', 'no_proof', 'pending_run',
])
def test_unrelated_or_incomplete_evidence_cannot_unlock_pool(tmp_path, case):
    store, coordinator, lease, refs = settled_but_blocked(tmp_path)
    conn = store.connect()
    try:
        if case == 'unknown_reason':
            conn.execute("UPDATE apify_key_pool_state SET blocked_reason='operator_block'")
        elif case == 'newer_block':
            conn.execute('UPDATE apify_key_pool_state SET updated_at=?',
                         ((datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),))
        elif case == 'wrong_key':
            conn.execute('UPDATE apify_actor_runs SET secret_id=?', (refs[1]['id'],))
        else:
            changes = {
                'nonzero_cost': 'charge_actual_usd=1', 'unsettled_cost': 'charge_final=0',
                'reserved_cost': 'charge_reserved_usd=1', 'known_run': "remote_run_id='knownremote'",
                'no_proof': 'last_error_code=NULL', 'pending_run': "status='start_outcome_unknown'",
            }
            conn.execute('UPDATE apify_actor_runs SET ' + changes[case])
        conn.commit()
        before = coordinator.public_state(coordinator.workspace_id)
        coordinator.reconcile_settled_unknown_start_block()
        after = coordinator.public_state(coordinator.workspace_id)
        assert after['status'] == 'blocked' and after['generation'] == before['generation']
    finally:
        store.close()


def test_another_unresolved_reservation_blocks_release_even_with_valid_proof(tmp_path):
    store, coordinator, lease, _ = settled_but_blocked(tmp_path)
    conn = store.connect()
    try:
        row = dict(conn.execute('SELECT * FROM apify_actor_runs WHERE id=?', (lease.reservation_id,)).fetchone())
        row.update(id='other-reservation', logical_run_id='other-fetch', status='starting',
                   charge_final=0, charge_actual_usd=None, last_error_code=None)
        columns = ','.join(row)
        conn.execute(f"INSERT INTO apify_actor_runs ({columns}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        conn.commit()
        coordinator.reconcile_settled_unknown_start_block()
        assert coordinator.public_state(coordinator.workspace_id)['status'] == 'blocked'
    finally:
        store.close()


def test_settled_proof_cannot_release_other_workspace(tmp_path):
    from src.services.apify_settled_start_recovery import settled_start_can_release
    store, coordinator, lease, _ = settled_but_blocked(tmp_path)
    try:
        state = dict(store.connect().execute('SELECT * FROM apify_key_pool_state').fetchone())
        state['workspace_id'] = 'unrelated-workspace'
        assert not settled_start_can_release(store.connect(), state)
    finally:
        store.close()
