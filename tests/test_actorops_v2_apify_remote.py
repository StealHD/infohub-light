from __future__ import annotations

import asyncio

import pytest

from src.services.actorops.apify_remote import ApifyV2RemoteClient
from src.services.actorops.domain import FailureClass
from src.services.actorops.ports import RemoteRunRequest
from src.services.actorops.runtime import ActorOpsRuntimeError
from src.scrapers.apify_client import ApifyClientError


class _Client:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.calls = []
        self.released = []

    async def _acquire_credential(self, attempted, *, logical_run_id):
        self.calls.append(("acquire", tuple(attempted), logical_run_id))
        return "lease", None

    async def _request_json(self, lease, method, path, **kwargs):
        self.calls.append((method, path, kwargs["params"]))
        if self.error:
            raise self.error
        return self.rows

    async def _release_reservation(self, lease, error_code):
        self.released.append((lease, error_code))


def test_dataset_replay_is_one_bounded_get_and_releases_reservation() -> None:
    client = _Client(rows=[{"id": "1"}])
    remote = ApifyV2RemoteClient(client)  # type: ignore[arg-type]

    rows = asyncio.run(remote.read_dataset("dataset/known", max_items=3))

    assert rows == ({"id": "1"},)
    assert client.calls[1] == (
        "GET",
        "/datasets/dataset%2Fknown/items",
        {"clean": "true", "limit": "3"},
    )
    assert client.released == [
        ("lease", "actorops_dataset_replay_read_only")
    ]


def test_expired_dataset_is_stable_unrecoverable_and_never_posts() -> None:
    client = _Client(error=RuntimeError("expired"))
    remote = ApifyV2RemoteClient(client)  # type: ignore[arg-type]

    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(remote.read_dataset("expired", max_items=3))

    assert caught.value.code == "actorops_dataset_unrecoverable"
    assert caught.value.failure_class is FailureClass.REMOTE_UNKNOWN
    assert all(call[0] != "POST" for call in client.calls)
    assert len(client.released) == 1


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
