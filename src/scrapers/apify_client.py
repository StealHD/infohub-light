"""Small Apify API client used by social scrapers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Sequence
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


_ROTATE_STATUS_CODES = {402, 403, 429}


class _ApifyTokenRotationError(RuntimeError):
    """Raised when a request should be retried with the next Apify token."""

    def __init__(self, env_name: str, status_code: int, message: str):
        self.env_name = env_name
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class ApifyClient:
    """Run an Apify actor and return its default dataset items."""

    def __init__(
        self,
        *,
        token: str | None = None,
        tokens: Sequence[tuple[str, str]] | None = None,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.apify.com/v2",
        poll_interval: float = 3.0,
        timeout_seconds: int = 180,
        retry_base_delay: float = 1.0,
    ):
        if tokens is None:
            if not token:
                raise ValueError("Apify token is required")
            tokens = [("APIFY_TOKEN", token)]
        cleaned_tokens: list[tuple[str, str]] = []
        for env_name, token_value in tokens:
            name = str(env_name or "APIFY_TOKEN").strip() or "APIFY_TOKEN"
            value = str(token_value or "").strip()
            if value:
                cleaned_tokens.append((name, value))
        if not cleaned_tokens:
            raise ValueError("No configured Apify tokens are set")

        self.tokens = cleaned_tokens
        self._token_index = 0
        self.token = self.tokens[0][1]
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.timeout_seconds = timeout_seconds
        self.retry_base_delay = retry_base_delay

    async def run_actor(self, actor_id: str, actor_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Start an actor run, wait for success, then fetch dataset items."""
        run = await self._request(
            "POST",
            f"/acts/{self._actor_path_id(actor_id)}/runs",
            json=actor_input,
            timeout=30.0,
        )
        data = run.get("data") or {}
        run_id = data.get("id")
        dataset_id = data.get("defaultDatasetId")
        if not run_id or not dataset_id:
            raise ValueError("Apify run response missing id or defaultDatasetId")

        await self._wait_for_run(str(run_id))
        items = await self._request(
            "GET",
            f"/datasets/{dataset_id}/items",
            params={"clean": "true"},
            timeout=30.0,
        )
        if not isinstance(items, list):
            raise ValueError("Apify dataset items response is not a list")
        return [item for item in items if isinstance(item, dict)]

    async def _wait_for_run(self, run_id: str) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            payload = await self._request(
                "GET",
                f"/actor-runs/{quote(run_id, safe='')}",
                timeout=10.0,
            )
            status = ((payload.get("data") or {}).get("status") or "").upper()
            if status == "SUCCEEDED":
                return
            if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                raise ValueError(f"Apify run {run_id} ended with status {status}")
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError(f"Apify run {run_id} timed out after {self.timeout_seconds}s")

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        failures: list[str] = []
        while self._token_index < len(self.tokens):
            env_name, token = self.tokens[self._token_index]
            try:
                self.token = token
                return await self._request_with_token(env_name, token, method, path, **kwargs)
            except _ApifyTokenRotationError as exc:
                failures.append(f"{exc.env_name}: {exc}")
                logger.warning(
                    "Apify token %s cannot continue (%s); trying next token if available",
                    exc.env_name,
                    exc,
                )
                self._token_index += 1

        raise ValueError("All Apify token envs failed: " + "; ".join(failures))

    async def _request_with_token(
        self,
        env_name: str,
        token: str,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        provided_headers = kwargs.pop("headers", None) or {}
        headers.update(provided_headers)

        for attempt in range(3):
            response = await self.http_client.request(
                method,
                url,
                headers=headers,
                **kwargs,
            )
            if response.status_code != 429:
                break
            if len(self.tokens) > 1:
                raise _ApifyTokenRotationError(
                    env_name,
                    response.status_code,
                    self._response_error_message(response),
                )
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else self.retry_base_delay * (2**attempt)
            except ValueError:
                delay = self.retry_base_delay * (2**attempt)
            logger.warning("Apify rate limited %s %s, retrying in %.1fs", method, path, delay)
            await asyncio.sleep(delay)
        if self._should_rotate_response(response):
            raise _ApifyTokenRotationError(
                env_name,
                response.status_code,
                self._response_error_message(response),
            )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _actor_path_id(actor_id: str) -> str:
        normalized = actor_id.strip().replace("/", "~")
        return quote(normalized, safe="~")

    @staticmethod
    def _response_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if payload.get("message"):
                return str(payload["message"])
        return str(payload)[:500]

    @classmethod
    def _should_rotate_response(cls, response: httpx.Response) -> bool:
        return response.status_code in _ROTATE_STATUS_CODES
