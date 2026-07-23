"""Safe quota projection for configured third-party secrets."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx


class SecretQuotaError(Exception):
    """Public-safe quota lookup failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool,
        action: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


class ApifySecretQuotaService:
    """Read Apify account limits and return only the approved numeric projection."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def fetch(self, *, secret_id: str, token: str) -> dict[str, Any]:
        timeout = httpx.Timeout(8.0, connect=3.0)
        try:
            async with httpx.AsyncClient(
                base_url="https://api.apify.com/v2",
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                user_response = await client.get("/users/me")
                self._raise_for_status(user_response)
                limits_response = await client.get("/users/me/limits")
                self._raise_for_status(limits_response)
        except SecretQuotaError:
            raise
        except httpx.RequestError:
            raise SecretQuotaError(
                "apify_quota_unavailable",
                "暂时无法连接 Apify，请稍后重试。",
                status_code=503,
                retryable=True,
                action="稍后手动刷新额度。",
            ) from None

        try:
            user_data = self._object(self._json(user_response), "data")
            plan = self._object(user_data, "plan")
            limits_data = self._object(self._json(limits_response), "data")
            cycle = self._object(limits_data, "monthlyUsageCycle")
            limits = self._object(limits_data, "limits")
            current = self._object(limits_data, "current")

            included = self._number(plan, "monthlyUsageCreditsUsd")
            usage = self._number(current, "monthlyUsageUsd")
            hard_limit = self._number(limits, "maxMonthlyUsageUsd")
            cycle_start = self._timestamp(cycle, "startAt")
            cycle_end = self._timestamp(cycle, "endAt")
        except (KeyError, TypeError, ValueError):
            raise SecretQuotaError(
                "apify_quota_invalid_response",
                "Apify 返回了无法识别的额度数据。",
                status_code=502,
                retryable=True,
                action="稍后重试；若持续失败，请检查 Apify 服务状态。",
            ) from None

        checked_at = self._now()
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)

        return {
            "secret_id": secret_id,
            "provider": "apify",
            "currency": "USD",
            "cycle_start_at": cycle_start,
            "cycle_end_at": cycle_end,
            "checked_at": checked_at.astimezone(timezone.utc).isoformat(),
            "monthly_included_credits_usd": included,
            "monthly_usage_usd": usage,
            "remaining_included_credits_usd": max(included - usage, 0.0),
            "max_monthly_usage_usd": hard_limit,
            "remaining_hard_limit_usd": max(hard_limit - usage, 0.0),
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        if response.status_code in {401, 403}:
            raise SecretQuotaError(
                "apify_quota_unauthorized",
                "Apify Token 无效或无权读取额度。",
                status_code=422,
                retryable=False,
                action="请轮换为有效的 Apify Token。",
            )
        if response.status_code == 429:
            raise SecretQuotaError(
                "apify_quota_rate_limited",
                "Apify 请求过于频繁，请稍后重试。",
                status_code=429,
                retryable=True,
                action="稍后手动刷新额度。",
            )
        if response.status_code >= 500:
            raise SecretQuotaError(
                "apify_quota_unavailable",
                "Apify 额度服务暂时不可用。",
                status_code=503,
                retryable=True,
                action="稍后手动刷新额度。",
            )
        raise SecretQuotaError(
            "apify_quota_invalid_response",
            "Apify 拒绝了额度请求。",
            status_code=502,
            retryable=False,
            action="请检查 Token 权限或稍后重试。",
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("response is not an object")
        return payload

    @staticmethod
    def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
        value = payload[key]
        if not isinstance(value, dict):
            raise TypeError(f"{key} is not an object")
        return value

    @staticmethod
    def _number(payload: dict[str, Any], key: str) -> float:
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{key} is not numeric")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{key} is not a safe non-negative number")
        return number

    @staticmethod
    def _timestamp(payload: dict[str, Any], key: str) -> str:
        value = payload[key]
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"{key} is not a timestamp")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(f"{key} must include a timezone")
        return value
