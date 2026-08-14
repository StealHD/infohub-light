from __future__ import annotations

import asyncio

import httpx
import pytest

from src.scrapers.apify_client import (
    ApifyClient,
    ApifyClientError,
    ApifyCredentialLease,
)


class _RegistrationFailureCoordinator:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def acquire_credential(self, _attempted_secret_ids=(), **_kwargs) -> ApifyCredentialLease:
        return ApifyCredentialLease(
            secret_id="validation-key",
            secret_version=1,
            pool_generation=3,
            env_name="APIFY_VALIDATION_TOKEN",
            reservation_id="reservation-1",
            token="test-token",
        )

    def assert_lease_startable(self, _lease: ApifyCredentialLease) -> None:
        return None

    def register_run(self, *_args, **_kwargs) -> None:
        raise RuntimeError("local persistence failed")

    def confirm_zero_cost_aborted_start(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
        dataset_id: str | None,
    ) -> dict[str, str]:
        self.events.append(
            ("confirmed_zero_cost_abort", lease.reservation_id, remote_run_id, dataset_id)
        )
        return {"status": "aborted"}

    def report_start_outcome_unknown(self, *_args, **_kwargs) -> None:
        self.events.append(("unexpected_unknown_start",))


def test_registration_failure_recovers_only_known_zero_cost_aborted_run() -> None:
    coordinator = _RegistrationFailureCoordinator()
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/runs"):
            return httpx.Response(
                200,
                json={"data": {"id": "remote-known", "defaultDatasetId": "dataset-known"}},
            )
        if request.method == "POST" and request.url.path.endswith("/abort"):
            return httpx.Response(200, json={"data": {"status": "ABORTING"}})
        if request.method == "GET" and "/actor-runs/remote-known" in request.url.path:
            return httpx.Response(
                200,
                json={"data": {"status": "ABORTED", "usageTotalUsd": 0}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    poll_interval=0,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_registration_failed"
    assert coordinator.events == [
        ("confirmed_zero_cost_abort", "reservation-1", "remote-known", "dataset-known")
    ]
    assert requests == [
        ("POST", "/v2/acts/actor~id/runs"),
        ("POST", "/v2/actor-runs/remote-known/abort"),
        ("GET", "/v2/actor-runs/remote-known"),
        ("GET", "/v2/actor-runs/remote-known"),
    ]
