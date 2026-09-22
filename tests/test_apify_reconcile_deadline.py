"""Slow provider reads cannot hold the pre-claim loop indefinitely."""
import asyncio
from types import SimpleNamespace

from src.services import apify_pool_reconciliation as module


def test_slow_workspace_is_cancelled_without_blocking_next_workspace(monkeypatch):
    monkeypatch.setattr(module, 'apify_key_pool_enabled', lambda: True)
    monkeypatch.setattr(module, 'POOL_RECONCILE_TIMEOUT_SECONDS', 0.01)
    store = SimpleNamespace(connect=lambda: SimpleNamespace(
        execute=lambda _: SimpleNamespace(fetchall=lambda: [{'id': 'slow'}, {'id': 'fast'}]),
    ))
    cancelled, calls = [], []
    monkeypatch.setattr(module, 'apify_coordinator_for_workspace', lambda _, **kw: kw['workspace_id'])
    async def reconcile(coordinator):
        calls.append(coordinator)
        if coordinator == 'slow':
            try:
                await asyncio.sleep(3600)
            finally:
                cancelled.append(coordinator)
        return {'status': 'ready'}
    monkeypatch.setattr(module, 'reconcile_apify_pool', reconcile)
    outcomes = asyncio.run(module.reconcile_all_apify_pools(store))
    assert outcomes == [
        {'workspace_id': 'slow', 'ok': False, 'code': 'apify_pool_reconcile_deadline'},
        {'workspace_id': 'fast', 'ok': True, 'status': 'ready'},
    ]
    assert cancelled == ['slow'] and calls == ['slow', 'fast']
