from __future__ import annotations

import asyncio

import httpx
import pytest

from src.scrapers.apify_client import ApifyClient, ApifyClientError


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        ("actor-not-found", "apify_actor_deleted"),
        ("build-not-found", "apify_actor_build_unavailable"),
        ("actor-build-not-found", "apify_actor_build_unavailable"),
    ],
)
def test_forbidden_missing_revision_is_classified_without_body_leak(
    error_type: str,
    expected_code: str,
) -> None:
    private_body = "private-upstream-detail"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"type": error_type, "message": private_body}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    token="token-one",
                    http_client=client,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == expected_code
    assert raised.value.status_code == 403
    assert private_body not in str(raised.value)
