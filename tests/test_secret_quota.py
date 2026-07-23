from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from src.services.secret_quota import ApifySecretQuotaService, SecretQuotaError


TEST_TOKEN = "apify-test-token-that-must-never-leak"


def _user_payload(*, included: float | str = 49) -> dict:
    return {
        "data": {
            "id": "private-user-id",
            "email": "private@example.com",
            "plan": {"monthlyUsageCreditsUsd": included},
        }
    }


def _limits_payload(*, usage: float = 13.5, hard_limit: float = 100) -> dict:
    return {
        "data": {
            "monthlyUsageCycle": {
                "startAt": "2026-07-01T00:00:00.000Z",
                "endAt": "2026-07-31T23:59:59.999Z",
            },
            "limits": {"maxMonthlyUsageUsd": hard_limit},
            "current": {"monthlyUsageUsd": usage},
        }
    }


def test_apify_quota_projects_safe_numbers_and_clamps_remaining_values() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
        if request.url.path == "/v2/users/me":
            return httpx.Response(200, json=_user_payload(included=10))
        if request.url.path == "/v2/users/me/limits":
            return httpx.Response(200, json=_limits_payload(usage=13.5, hard_limit=12))
        raise AssertionError(f"unexpected request path: {request.url.path}")

    service = ApifySecretQuotaService(
        transport=httpx.MockTransport(handler),
        now=lambda: datetime(2026, 7, 23, 8, 30, tzinfo=timezone.utc),
    )

    result = asyncio.run(service.fetch(secret_id="secret-safe", token=TEST_TOKEN))

    assert [request.url.path for request in requests] == ["/v2/users/me", "/v2/users/me/limits"]
    assert result == {
        "secret_id": "secret-safe",
        "provider": "apify",
        "currency": "USD",
        "cycle_start_at": "2026-07-01T00:00:00.000Z",
        "cycle_end_at": "2026-07-31T23:59:59.999Z",
        "checked_at": "2026-07-23T08:30:00+00:00",
        "monthly_included_credits_usd": 10.0,
        "monthly_usage_usd": 13.5,
        "remaining_included_credits_usd": 0.0,
        "max_monthly_usage_usd": 12.0,
        "remaining_hard_limit_usd": 0.0,
    }
    serialized = repr(result)
    assert TEST_TOKEN not in serialized
    assert "private-user-id" not in serialized
    assert "private@example.com" not in serialized


@pytest.mark.parametrize(
    ("status_code", "expected_code", "expected_status", "retryable"),
    [
        (401, "apify_quota_unauthorized", 422, False),
        (403, "apify_quota_unauthorized", 422, False),
        (429, "apify_quota_rate_limited", 429, True),
        (500, "apify_quota_unavailable", 503, True),
    ],
)
def test_apify_quota_maps_upstream_status_without_leaking_response(
    status_code: int,
    expected_code: str,
    expected_status: int,
    retryable: bool,
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            status_code,
            json={"error": {"message": f"upstream leaked {TEST_TOKEN}"}},
        )
    )
    service = ApifySecretQuotaService(transport=transport)

    with pytest.raises(SecretQuotaError) as raised:
        asyncio.run(service.fetch(secret_id="secret-error", token=TEST_TOKEN))

    assert raised.value.code == expected_code
    assert raised.value.status_code == expected_status
    assert raised.value.retryable is retryable
    assert TEST_TOKEN not in str(raised.value)
    assert TEST_TOKEN not in repr(raised.value)


def test_apify_quota_maps_timeout_to_retryable_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout with {TEST_TOKEN}", request=request)

    service = ApifySecretQuotaService(transport=httpx.MockTransport(handler))

    with pytest.raises(SecretQuotaError) as raised:
        asyncio.run(service.fetch(secret_id="secret-timeout", token=TEST_TOKEN))

    assert raised.value.code == "apify_quota_unavailable"
    assert raised.value.status_code == 503
    assert raised.value.retryable is True
    assert TEST_TOKEN not in str(raised.value)


@pytest.mark.parametrize(
    "payloads",
    [
        (_user_payload(), {"data": {"monthlyUsageCycle": {}}}),
        (_user_payload(included="NaN"), _limits_payload()),
        ({"data": {"plan": {"monthlyUsageCreditsUsd": True}}}, _limits_payload()),
        (_user_payload(), _limits_payload(usage=-1)),
    ],
)
def test_apify_quota_rejects_malformed_or_unsafe_responses(payloads: tuple[dict, dict]) -> None:
    responses = iter(payloads)
    service = ApifySecretQuotaService(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=next(responses)))
    )

    with pytest.raises(SecretQuotaError) as raised:
        asyncio.run(service.fetch(secret_id="secret-malformed", token=TEST_TOKEN))

    assert raised.value.code == "apify_quota_invalid_response"
    assert raised.value.status_code == 502
    assert raised.value.retryable is True
    assert TEST_TOKEN not in str(raised.value)
