from __future__ import annotations

import asyncio

import pytest

from src.services.actorops.apify_remote import ApifyV2RemoteClient
from src.services.actorops.domain import FailureClass
from src.services.actorops.ports import RemoteRunRequest
from src.services.actorops.runtime import ActorOpsRuntimeError
from src.scrapers.apify_client import ApifyClientError


class _Client:
    connections = []

    def __init__(self, rows=None, error=None):
        import sqlite3
        from types import SimpleNamespace
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE actor_attempts_v2 (workspace_id,attempt_id,remote_run_id,dataset_id,
                secret_ref_id,secret_version,pool_generation,kind);
            CREATE TABLE apify_actor_runs (id,workspace_id,logical_run_id,remote_run_id,dataset_id,
                secret_id,secret_version,pool_generation,purpose);
            INSERT INTO actor_attempts_v2 VALUES ('w','attempt','run','dataset/known','original',1,2,'fetch');
            INSERT INTO apify_actor_runs VALUES ('reservation','w','attempt','run','dataset/known','original',1,2,'acquisition');
        """)
        self.connection = connection
        self.connections.append(connection)
        self.rows, self.error, self.calls = rows, error, []
        self.coordinator = SimpleNamespace(
            workspace_id='w', store=SimpleNamespace(connect=lambda: connection),
            lease_for_run=lambda rid: ('original-key', rid),
        )

    async def _request_json(self, lease, method, path, **kwargs):
        self.calls.append((lease, method, path, kwargs))
        if self.error:
            raise self.error
        return self.rows


@pytest.fixture(autouse=True)
def close_replay_test_connections():
    yield
    while _Client.connections:
        _Client.connections.pop().close()


def request():
    from src.services.actorops.dataset_replay import DatasetReadRequest
    return DatasetReadRequest('attempt', 'run', 'dataset/known', 3)


def test_dataset_replay_uses_original_key_without_new_reservation():
    client = _Client(rows=[{'id': '1'}])
    assert asyncio.run(ApifyV2RemoteClient(client).read_dataset(request())) == ({'id': '1'},)
    lease, method, path, kwargs = client.calls[0]
    assert lease == ('original-key', 'reservation')
    assert method == 'GET' and path == '/datasets/dataset%2Fknown/items'
    assert kwargs['params'] == {'clean': 'true', 'limit': '3'}
    assert kwargs['classify_credential'] is False
    assert kwargs['max_response_bytes'] == 8 * 1024 * 1024
    assert client.connection.execute('SELECT COUNT(*) FROM apify_actor_runs').fetchone()[0] == 1


@pytest.mark.parametrize(('status', 'code'), [(403, 'access_denied'), (404, 'missing'), (503, 'read_transient')])
def test_dataset_errors_are_classified_without_new_start(status, code):
    client = _Client(error=ApifyClientError('upstream_error', 'safe', retryable=False, status_code=status))
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(ApifyV2RemoteClient(client).read_dataset(request()))
    assert caught.value.code == 'actorops_dataset_' + code
    assert caught.value.retryable == (status == 503)
    assert [call[1] for call in client.calls] == ['GET']


@pytest.mark.parametrize('change', ["workspace_id='other'", "remote_run_id='other'", "secret_version=2", "purpose='validation'"])
def test_dataset_requires_exact_tenant_run_credential_and_purpose(change):
    client = _Client(rows=[])
    client.connection.execute('UPDATE apify_actor_runs SET ' + change)
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(ApifyV2RemoteClient(client).read_dataset(request()))
    assert caught.value.code == 'actorops_dataset_identity_unproven'
    assert client.calls == []


def test_unavailable_original_secret_never_uses_current_key():
    client = _Client(rows=[])
    def missing(_):
        raise ValueError('secret rotated')
    client.coordinator.lease_for_run = missing
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(ApifyV2RemoteClient(client).read_dataset(request()))
    assert caught.value.code == 'actorops_dataset_credential_unavailable'
    assert client.calls == []


@pytest.mark.parametrize('rows', [{}, [None], [{}] * 4])
def test_invalid_dataset_shape_is_not_silently_filtered(rows):
    client = _Client(rows=rows)
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(ApifyV2RemoteClient(client).read_dataset(request()))
    assert caught.value.code == 'actorops_dataset_invalid'


def test_explicit_http_start_rejection_carries_no_start_evidence() -> None:
    class Client:
        coordinator = object()

        async def run_actor_detailed(self, *_args, **_kwargs):
            raise ApifyClientError(
                "apify_actor_start_rejected",
                "safe rejection",
                retryable=False,
                status_code=403,
            )

    class Events:
        pass

    request = RemoteRunRequest(
        attempt_id="attempt",
        candidate_id="candidate",
        actor_id="publisher/actor",
        build_number="1.0.0",
        actor_input={},
        max_total_charge_usd=0.05,
        max_items=1,
    )
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(
            ApifyV2RemoteClient(Client()).execute(request, Events())  # type: ignore[arg-type]
        )

    assert caught.value.code == "apify_actor_start_rejected"
    assert caught.value.failure_class is FailureClass.CANDIDATE
    assert caught.value.proven_no_start is True


def test_invalid_json_stops_dataset_recovery():
    client = _Client(error=ValueError('Apify response was not valid JSON'))
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(ApifyV2RemoteClient(client).read_dataset(request()))
    assert caught.value.code == 'actorops_dataset_invalid'
    assert caught.value.retryable is False


@pytest.mark.parametrize('started', [False, True])
def test_unhandled_transport_error_preserves_start_uncertainty_and_never_retries(started):
    import httpx
    from types import SimpleNamespace

    class Coordinator:
        async def acquire_credential(self):
            return SimpleNamespace(secret_id='key', secret_version=1, pool_generation=1)

    class Events:
        def starting(self, **kwargs):
            pass

    class Client:
        coordinator = Coordinator()
        calls = 0

        async def run_actor_detailed(self, *args, **kwargs):
            self.calls += 1
            if started:
                await self.coordinator.acquire_credential()
            raise httpx.ConnectError('private upstream detail')

    client = Client()
    original = client.coordinator
    req = RemoteRunRequest(attempt_id='a', candidate_id='c', actor_id='actor',
                           build_number='1', actor_input={}, max_total_charge_usd=.05, max_items=1)
    with pytest.raises(ActorOpsRuntimeError) as error:
        asyncio.run(ApifyV2RemoteClient(client).execute(req, Events()))
    assert error.value.code == ('apify_run_reconcile_required' if started else 'apify_transport_unavailable')
    assert error.value.failure_class is (FailureClass.REMOTE_UNKNOWN if started else FailureClass.INTERNAL)
    assert not error.value.proven_no_start
    assert client.coordinator is original and client.calls == 1


def test_unknown_start_keeps_original_exception_for_safe_diagnostics(monkeypatch):
    import httpx
    from src.services.actorops import remote_diagnostics
    cause = httpx.ConnectTimeout('sensitive upstream content')
    seen = []
    monkeypatch.setattr(remote_diagnostics, 'record_remote_exception', lambda error, code: seen.append((error, code)))
    class Client:
        coordinator = object()
        async def run_actor_detailed(self, *args, **kwargs):
            try:
                raise cause
            except httpx.TransportError:
                raise ApifyClientError('apify_start_outcome_unknown', 'safe', retryable=False) from None
    req = RemoteRunRequest(attempt_id='a', candidate_id='c', actor_id='actor',
                           build_number='1', actor_input={}, max_total_charge_usd=.05, max_items=1)
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(ApifyV2RemoteClient(Client()).execute(req, object()))
    assert seen == [(cause, 'apify_start_outcome_unknown')]
    assert 'sensitive' not in str(caught.value)
    assert not caught.value.proven_no_start
