from __future__ import annotations

import asyncio

import httpx
import pytest

from src.scrapers.apify_client import ApifyClient, ApifyClientError


def _client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return (
        ApifyClient(
            token="test-token-not-persisted",
            http_client=http_client,
            base_url="https://api.apify.test/v2",
            retry_base_delay=0,
        ),
        http_client,
    )


def test_preflight_checks_actor_and_exact_build_without_post() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.headers["Authorization"] == "Bearer test-token-not-persisted"
        if request.url.path.endswith("/acts/publisher~actor"):
            return httpx.Response(
                200,
                json={"data": {"id": "actor-id", "isPublic": True}},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "build-id",
                    "actorId": "actor-id",
                    "buildNumber": "1.2.3",
                    "status": "SUCCEEDED",
                }
            },
        )

    client, http_client = _client(handler)
    try:
        result = asyncio.run(
            client.preflight_actor_revision(
                "publisher/actor",
                build_id="build-id",
                build_number="1.2.3",
            )
        )
    finally:
        asyncio.run(http_client.aclose())
    assert result == {
        "status": "available",
        "build_id": "build-id",
        "build_number": "1.2.3",
    }
    assert len(requests) == 2


def test_preflight_maps_missing_revision_to_deterministic_zero_start_error() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(404, json={"error": {"type": "record-not-found"}})

    client, http_client = _client(handler)
    try:
        with pytest.raises(ApifyClientError) as caught:
            asyncio.run(
                client.preflight_actor_revision(
                    "publisher/gone",
                    build_id="gone-build",
                    build_number="0.0.900",
                )
            )
    finally:
        asyncio.run(http_client.aclose())
    assert caught.value.code == "apify_actor_revision_unavailable"
    assert caught.value.retryable is False
    assert caught.value.status_code == 404
    assert methods == ["GET"]


def test_preflight_retries_temporary_metadata_failure_with_same_get() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        assert request.method == "GET"
        if request.url.path.endswith("/acts/publisher~actor"):
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"data": {"id": "actor-id"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "build-id",
                    "actorId": "actor-id",
                    "buildNumber": "2.0.0",
                    "status": "SUCCEEDED",
                }
            },
        )

    client, http_client = _client(handler)
    try:
        result = asyncio.run(
            client.preflight_actor_revision(
                "publisher/actor",
                build_id="build-id",
                build_number="2.0.0",
            )
        )
    finally:
        asyncio.run(http_client.aclose())
    assert result["status"] == "available"
    assert attempts == 3


def test_preflight_rejects_changed_exact_build_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/acts/publisher~actor"):
            return httpx.Response(200, json={"data": {"id": "actor-id"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "build-id",
                    "actorId": "actor-id",
                    "buildNumber": "new-default",
                    "status": "SUCCEEDED",
                }
            },
        )

    client, http_client = _client(handler)
    try:
        with pytest.raises(ApifyClientError) as caught:
            asyncio.run(
                client.preflight_actor_revision(
                    "publisher/actor",
                    build_id="build-id",
                    build_number="frozen-build",
                )
            )
    finally:
        asyncio.run(http_client.aclose())
    assert caught.value.code == "apify_actor_revision_unavailable"
    assert caught.value.status_code == 412
