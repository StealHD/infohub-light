"""Small Apify API client used by social scrapers."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from ..services.apify_actor_run_reconciliation import prove_no_user_run_in_window
from ..services.apify_actor_run_registration import reconcile_failed_run_registration
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _safe_nonnegative_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


@dataclass(frozen=True, slots=True)
class ApifyCredentialLease:
    """One durable credential reservation for starting exactly one Actor Run."""

    secret_id: str
    secret_version: int
    pool_generation: int
    env_name: str
    reservation_id: str
    token: str = field(repr=False)
    quota_check_required: bool = False


@dataclass(frozen=True, slots=True)
class ApifyActorRunResult:
    """Dataset rows plus bounded accounting reported by the terminal Run."""

    items: list[dict[str, Any]]
    actual_charge_usd: float | None = None
    cost_final: bool = False


class ApifyCredentialFailureKind(str, Enum):
    """Pool-level reasons that make a credential unavailable for new Runs."""

    DEPLETED = "depleted"
    INVALID = "invalid"


ApifyRunAborter = Callable[[ApifyCredentialLease, str], Awaitable[str]]


class ApifyRunCoordinator(Protocol):
    """Storage/service boundary used by :class:`ApifyClient` in pool mode.

    Methods may be synchronous or awaitable. ``report_credential_failure`` must
    not return until the old generation has been drained and a failover is safe.
    """

    def acquire_credential(
        self,
        attempted_secret_ids: Collection[str] = (),
        *,
        logical_run_id: str | None = None,
        expected_pool_generation: int | None = None,
    ) -> ApifyCredentialLease | Awaitable[ApifyCredentialLease]: ...

    def record_quota_snapshot(
        self,
        lease: ApifyCredentialLease,
        *,
        remaining_included_credits_usd: float,
        checked_at: str | None = None,
        cycle_start_at: str | None = None,
        cycle_end_at: str | None = None,
        monthly_included_credits_usd: float | None = None,
        monthly_usage_usd: float | None = None,
        max_monthly_usage_usd: float | None = None,
        remaining_hard_limit_usd: float | None = None,
    ) -> None | Awaitable[None]: ...

    def assert_lease_startable(
        self,
        lease: ApifyCredentialLease,
    ) -> None | Awaitable[None]: ...

    def register_run(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
        dataset_id: str | None,
        logical_run_id: str | None = None,
    ) -> None | Awaitable[None]: ...

    def get_run(
        self,
        reservation_id: str,
    ) -> dict[str, Any] | None | Awaitable[dict[str, Any] | None]: ...

    def mark_run_aborting(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
    ) -> None | Awaitable[None]: ...

    def mark_run_terminal(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
        status: str,
    ) -> bool | None | Awaitable[bool | None]: ...

    def record_run_accounting(
        self,
        lease: ApifyCredentialLease,
        *,
        actual_cost_usd: float | None,
        cost_final: bool,
        reserved_cost_usd: float | None = None,
    ) -> None | Awaitable[None]: ...

    def should_retry_after_terminal(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
        status: str,
    ) -> bool | None | Awaitable[bool | None]: ...

    def report_credential_failure(
        self,
        lease: ApifyCredentialLease,
        *,
        failure_kind: ApifyCredentialFailureKind,
        status_code: int,
        error_type: str | None,
        abort_run: ApifyRunAborter,
    ) -> None | Awaitable[None]: ...

    def report_start_outcome_unknown(
        self,
        lease: ApifyCredentialLease,
        error_code: str = "apify_start_outcome_unknown",
    ) -> None | Awaitable[None]: ...

    def block_run_reconciliation(
        self,
        lease: ApifyCredentialLease,
        error_code: str = "apify_run_reconcile_required",
    ) -> None | Awaitable[None]: ...

    def lease_for_run(
        self,
        reservation_id: str,
    ) -> ApifyCredentialLease | Awaitable[ApifyCredentialLease]: ...

    def complete_run_reconciliation(
        self,
        lease: ApifyCredentialLease,
    ) -> None | Awaitable[None]: ...

    def release_reservation(
        self,
        lease: ApifyCredentialLease,
        error_code: str,
    ) -> None | Awaitable[None]: ...


_TERMINAL_RUN_STATUSES = frozenset({"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"})
_DEFAULT_DATASET_ITEM_LIMIT = 2
_DEFAULT_DATASET_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
_EXPLICIT_QUOTA_ERROR_TYPES = frozenset(
    {
        "account-credit-exhausted",
        "failed-to-charge-user",
        "insufficient-account-credit",
        "monthly-usage-limit-exceeded",
        "monthly-usage-limit-too-low",
        "not-enough-usage-to-run-paid-actor",
        "quota-exceeded",
        "usage-limit-exceeded",
    }
)
_INVALID_TOKEN_ERROR_TYPES = frozenset(
    {
        "invalid-token",
        "invalid-token-type",
        "missing-api-token",
        "token-not-provided",
    }
)


class ApifyClientError(RuntimeError):
    """Safe, machine-readable Apify client failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ):
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


class _ApifyCredentialRejected(RuntimeError):
    """Internal signal to retry a whole Run with a different credential."""

    def __init__(
        self,
        failure_kind: ApifyCredentialFailureKind,
        status_code: int,
        error_type: str | None,
    ):
        self.failure_kind = failure_kind
        self.status_code = status_code
        self.error_type = error_type
        self.remote_run_id: str | None = None
        self.run_is_terminal = False
        super().__init__(f"Apify credential rejected ({failure_kind.value})")


class _RetryRunAfterDrain(RuntimeError):
    """Internal signal for a Run aborted by a concurrent pool drain."""


class ApifyClient:
    """Run an Apify actor with one immutable credential lease per remote Run."""

    def __init__(
        self,
        *,
        token: str | None = None,
        tokens: Sequence[tuple[str, str]] | None = None,
        coordinator: ApifyRunCoordinator | None = None,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.apify.com/v2",
        poll_interval: float = 3.0,
        timeout_seconds: int = 180,
        drain_timeout_seconds: float = 30.0,
        retry_base_delay: float = 1.0,
        accounting_settle_delay_seconds: float = 10.0,
    ):
        if tokens is None and token:
            tokens = [("APIFY_TOKEN", token)]
        elif tokens is None:
            tokens = []

        cleaned_tokens: list[tuple[str, str]] = []
        for env_name, token_value in tokens:
            name = str(env_name or "APIFY_TOKEN").strip() or "APIFY_TOKEN"
            value = str(token_value or "").strip()
            if value:
                cleaned_tokens.append((name, value))
        if coordinator is None and not cleaned_tokens:
            if token is None:
                raise ValueError("Apify token is required")
            raise ValueError("No configured Apify tokens are set")

        self.tokens = cleaned_tokens
        self.coordinator = coordinator
        self._legacy_token_index = 0
        self.token = self.tokens[0][1] if self.tokens else ""
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.timeout_seconds = timeout_seconds
        self.drain_timeout_seconds = drain_timeout_seconds
        self.retry_base_delay = retry_base_delay
        self.accounting_settle_delay_seconds = max(
            float(accounting_settle_delay_seconds),
            0.0,
        )

    async def prove_no_user_run_in_window(
        self,
        lease: ApifyCredentialLease,
        *,
        started_after: str,
        started_before: str,
    ) -> bool:
        """Return true only when Apify proves an account-wide empty window."""

        return await prove_no_user_run_in_window(
            self._request_json,
            lease,
            started_after=started_after,
            started_before=started_before,
        )
    async def refresh_registered_run_status(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
    ) -> str:
        """Read one known Run and persist only an authoritative terminal state."""

        path = f"/actor-runs/{quote(str(remote_run_id), safe='')}"
        payload = await self._request_json(
            lease,
            "GET",
            path,
            timeout=10.0,
            classify_credential=False,
        )
        status = self._run_status(payload)
        actual_charge_usd = self._run_usage_total_usd(payload)
        if status not in _TERMINAL_RUN_STATUSES:
            return status
        if actual_charge_usd is not None:
            await self._coordinator_call(
                "record_run_accounting", lease,
                actual_cost_usd=actual_charge_usd, cost_final=True, optional=True,
            )
        await self._coordinator_call(
            "mark_run_terminal", lease, str(remote_run_id), status,
        )
        return status

    async def run_actor(
        self,
        actor_id: str,
        actor_input: dict[str, Any],
        *,
        max_total_charge_usd: float | None = None,
        logical_run_id: str | None = None,
        build_number: str | None = None,
        max_paid_dataset_items: int = 1,
        dataset_item_limit: int = _DEFAULT_DATASET_ITEM_LIMIT,
        dataset_response_max_bytes: int = _DEFAULT_DATASET_RESPONSE_MAX_BYTES,
    ) -> list[dict[str, Any]]:
        """Start a fresh Run per credential attempt and return dataset items."""
        result = await self.run_actor_detailed(
            actor_id,
            actor_input,
            max_total_charge_usd=max_total_charge_usd,
            logical_run_id=logical_run_id,
            build_number=build_number,
            max_paid_dataset_items=max_paid_dataset_items,
            dataset_item_limit=dataset_item_limit,
            dataset_response_max_bytes=dataset_response_max_bytes,
        )
        return result.items

    async def preflight_actor_revision(
        self,
        actor_id: str,
        *,
        build_id: str,
        build_number: str,
    ) -> dict[str, str]:
        """Recheck one public Actor and exact Build without starting a Run."""

        token = str(self.token or "").strip()
        if not token:
            raise ApifyClientError(
                "apify_key_rejected",
                "Apify metadata preflight has no active credential",
                retryable=False,
                status_code=401,
            )
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }

        async def get_data(path: str) -> dict[str, Any]:
            response: httpx.Response | None = None
            for attempt in range(3):
                try:
                    response = await self.http_client.get(
                        f"{self.base_url}{path}",
                        headers=headers,
                        timeout=10.0,
                    )
                except (httpx.TransportError, httpx.DecodingError):
                    if attempt >= 2:
                        raise ApifyClientError(
                            "apify_actor_revision_preflight_unavailable",
                            "Actor metadata preflight is temporarily unavailable",
                            retryable=True,
                        ) from None
                    await asyncio.sleep(
                        min(max(self.retry_base_delay * (2**attempt), 0.0), 5.0)
                    )
                    continue
                if response.status_code == 401 or response.status_code == 402:
                    raise ApifyClientError(
                        "apify_key_rejected",
                        "Apify rejected the metadata credential",
                        retryable=False,
                        status_code=response.status_code,
                    )
                if response.status_code in {403, 404, 410}:
                    raise ApifyClientError(
                        "apify_actor_revision_unavailable",
                        "The immutable Actor revision is unavailable",
                        retryable=False,
                        status_code=response.status_code,
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = (
                                float(retry_after)
                                if retry_after
                                else self.retry_base_delay * (2**attempt)
                            )
                        except ValueError:
                            delay = self.retry_base_delay * (2**attempt)
                        await asyncio.sleep(min(max(delay, 0.0), 5.0))
                        continue
                    raise ApifyClientError(
                        "apify_actor_revision_preflight_unavailable",
                        "Actor metadata preflight is temporarily unavailable",
                        retryable=True,
                        status_code=response.status_code,
                    )
                if response.status_code >= 400:
                    raise ApifyClientError(
                        "apify_actor_revision_unavailable",
                        "The immutable Actor revision failed metadata preflight",
                        retryable=False,
                        status_code=response.status_code,
                    )
                if len(response.content) > 1024 * 1024:
                    raise ApifyClientError(
                        "apify_actor_revision_preflight_invalid",
                        "Actor metadata preflight exceeded the response limit",
                        retryable=False,
                    )
                try:
                    payload = response.json()
                except ValueError:
                    raise ApifyClientError(
                        "apify_actor_revision_preflight_invalid",
                        "Actor metadata preflight returned invalid JSON",
                        retryable=False,
                    ) from None
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, dict):
                    raise ApifyClientError(
                        "apify_actor_revision_preflight_invalid",
                        "Actor metadata preflight returned an invalid envelope",
                        retryable=False,
                    )
                return data
            raise AssertionError("bounded metadata preflight did not terminate")

        actor = await get_data(f"/acts/{self._actor_path_id(actor_id)}")
        build = await get_data(
            f"/actor-builds/{quote(str(build_id), safe='')}"
        )
        actor_data_id = str(actor.get("id") or "")
        build_actor_id = str(build.get("actorId") or "")
        if (
            actor.get("isPublic") is False
            or bool(actor.get("isDeprecated"))
            or str(build.get("id") or "") != str(build_id)
            or str(build.get("buildNumber") or "") != str(build_number)
            or str(build.get("status") or "").upper() != "SUCCEEDED"
            or (actor_data_id and build_actor_id and actor_data_id != build_actor_id)
        ):
            raise ApifyClientError(
                "apify_actor_revision_unavailable",
                "The immutable Actor revision changed before the paid Run",
                retryable=False,
                status_code=412,
            )
        return {
            "status": "available",
            "build_id": str(build_id),
            "build_number": str(build_number),
        }

    async def run_actor_detailed(
        self,
        actor_id: str,
        actor_input: dict[str, Any],
        *,
        max_total_charge_usd: float | None = None,
        logical_run_id: str | None = None,
        build_number: str | None = None,
        max_paid_dataset_items: int = 1,
        dataset_item_limit: int = _DEFAULT_DATASET_ITEM_LIMIT,
        dataset_response_max_bytes: int = _DEFAULT_DATASET_RESPONSE_MAX_BYTES,
        expected_pool_generation: int | None = None,
        max_remote_starts: int | None = None,
        timeout_seconds: int | None = None,
    ) -> ApifyActorRunResult:
        """Return dataset rows together with terminal Apify charge metadata."""
        build = self._optional_build_number(build_number)
        paid_item_limit = self._positive_limit(
            max_paid_dataset_items,
            label="max_paid_dataset_items",
            maximum=100,
        )
        response_item_limit = self._positive_limit(
            dataset_item_limit,
            label="dataset_item_limit",
            maximum=100,
        )
        response_byte_limit = self._positive_limit(
            dataset_response_max_bytes,
            label="dataset_response_max_bytes",
            maximum=16 * 1024 * 1024,
        )
        attempted_secret_ids: set[str] = set()
        remote_start_attempts = 0
        if max_remote_starts is not None:
            max_remote_starts = self._positive_limit(
                max_remote_starts,
                label="max_remote_starts",
                maximum=3,
            )
        if timeout_seconds is not None:
            timeout_seconds = self._positive_limit(
                timeout_seconds,
                label="timeout_seconds",
                maximum=3600,
            )

        while True:
            lease, legacy_index = await self._acquire_credential(
                attempted_secret_ids,
                logical_run_id=logical_run_id,
                expected_pool_generation=expected_pool_generation,
            )
            if lease.secret_id in attempted_secret_ids:
                raise ApifyClientError(
                    "apify_key_pool_stalled",
                    "Apify credential coordinator returned an already-attempted key",
                    retryable=True,
                )
            attempted_secret_ids.add(lease.secret_id)
            self.token = lease.token

            try:
                if lease.quota_check_required:
                    await self._refresh_quota_snapshot(lease)
                remote_start_attempts += 1
                result = await self._run_actor_once(
                    lease,
                    actor_id,
                    actor_input,
                    max_total_charge_usd=max_total_charge_usd,
                    logical_run_id=logical_run_id,
                    build_number=build,
                    max_paid_dataset_items=paid_item_limit,
                    dataset_item_limit=response_item_limit,
                    dataset_response_max_bytes=response_byte_limit,
                    timeout_seconds=timeout_seconds,
                )
            except _RetryRunAfterDrain:
                if (
                    max_remote_starts is not None
                    and remote_start_attempts >= max_remote_starts
                ):
                    raise ApifyClientError(
                        "apify_remote_start_limit",
                        "Actor Run cannot be restarted without a new authorization",
                        retryable=False,
                    ) from None
                continue
            except _ApifyCredentialRejected as exc:
                await self._handle_credential_failure(lease, exc)
                if legacy_index is not None:
                    self._legacy_token_index = legacy_index + 1
                if (
                    max_remote_starts is not None
                    and remote_start_attempts >= max_remote_starts
                ):
                    raise ApifyClientError(
                        "apify_remote_start_limit",
                        "Actor Run cannot be retried without a new authorization",
                        retryable=False,
                        status_code=exc.status_code,
                    ) from None
                continue
            else:
                if legacy_index is not None:
                    self._legacy_token_index = legacy_index
                return result

    async def resume_actor_detailed(
        self,
        reservation_id: str,
        *,
        dataset_item_limit: int = _DEFAULT_DATASET_ITEM_LIMIT,
        dataset_response_max_bytes: int = _DEFAULT_DATASET_RESPONSE_MAX_BYTES,
        reserved_cost_usd: float | None = None,
        status_wait_seconds: int = 30,
    ) -> ApifyActorRunResult:
        """Consume a durable Run without issuing another Actor POST."""

        response_item_limit = self._positive_limit(
            dataset_item_limit,
            label="dataset_item_limit",
            maximum=100,
        )
        response_byte_limit = self._positive_limit(
            dataset_response_max_bytes,
            label="dataset_response_max_bytes",
            maximum=16 * 1024 * 1024,
        )
        reconcile_wait = self._positive_limit(
            status_wait_seconds,
            label="status_wait_seconds",
            maximum=300,
        )
        reserved_cost = (
            _safe_nonnegative_float(reserved_cost_usd)
            if reserved_cost_usd is not None
            else None
        )
        if reserved_cost_usd is not None and reserved_cost is None:
            raise ValueError("reserved_cost_usd must be a finite non-negative number")

        if self.coordinator is None:
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "A durable coordinator is required to resume an Apify Run",
                retryable=True,
            )
        try:
            lease = await self._coordinator_call(
                "lease_for_run",
                reservation_id,
            )
            run = await self._coordinator_call("get_run", reservation_id)
        except Exception:
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify Run credential is unavailable",
                retryable=True,
            ) from None
        if not isinstance(lease, ApifyCredentialLease) or not isinstance(run, dict):
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify Run could not be loaded",
                retryable=True,
            )
        remote_run_id = str(run.get("remote_run_id") or "")
        dataset_id = str(run.get("dataset_id") or "")
        if not remote_run_id or not dataset_id:
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify Run is missing reconciliation metadata",
                retryable=True,
            )
        self.token = lease.token
        status = str(run.get("status") or "").lower()
        actual_charge_usd = _safe_nonnegative_float(
            run.get("charge_actual_usd")
        )
        cost_final = bool(run.get("charge_final") and actual_charge_usd is not None)
        terminal_status = status.upper().replace("_", "-")
        if status != "succeeded" and terminal_status in _TERMINAL_RUN_STATUSES:
            await self._complete_started_run(lease)
            raise ValueError("Apify actor run ended without a usable dataset")
        try:
            if status != "succeeded":
                actual_charge_usd, cost_final = await self._wait_for_run(
                    lease,
                    remote_run_id,
                    reserved_cost_usd=reserved_cost,
                    timeout_seconds=reconcile_wait,
                    abort_on_timeout=False,
                )
        except _ApifyCredentialRejected as exc:
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify Run still requires reconciliation",
                retryable=True,
                status_code=exc.status_code,
            ) from None
        except TimeoutError:
            # Read-only reconciliation never aborts a still-running Run.
            raise
        except (httpx.HTTPError, ValueError):
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify Run status still requires reconciliation",
                retryable=True,
            ) from None

        try:
            items = await self._request_json(
                lease,
                "GET",
                f"/datasets/{quote(dataset_id, safe='')}/items",
                params={
                    "clean": "true",
                    "limit": str(response_item_limit),
                },
                timeout=30.0,
                max_response_bytes=response_byte_limit,
            )
        except _ApifyCredentialRejected as exc:
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify dataset still requires reconciliation",
                retryable=True,
                status_code=exc.status_code,
            ) from None
        except (httpx.HTTPError, ValueError):
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify dataset is temporarily unavailable",
                retryable=True,
            ) from None
        if not isinstance(items, list):
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify dataset could not be validated",
                retryable=True,
            )
        if len(items) > response_item_limit:
            raise ApifyClientError(
                "apify_dataset_row_limit_exceeded",
                "The durable Apify dataset exceeded the bounded row limit",
                retryable=False,
            )
        await self._complete_started_run(lease)
        return ApifyActorRunResult(
            items=[item for item in items if isinstance(item, dict)],
            actual_charge_usd=actual_charge_usd,
            cost_final=cost_final,
        )

    async def abort_run(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
    ) -> str:
        """Abort one Run with its original token and confirm a terminal status."""
        run_id = quote(str(remote_run_id), safe="")
        try:
            await self._coordinator_call(
                "mark_run_aborting",
                lease,
                str(remote_run_id),
            )
            try:
                await self._request_json(
                    lease,
                    "POST",
                    f"/actor-runs/{run_id}/abort",
                    params={"gracefully": "false"},
                    timeout=10.0,
                    classify_credential=False,
                )
            except (httpx.HTTPError, ValueError):
                # An idempotent retry can race with a Run that already reached a
                # terminal state. The bounded poll below is the source of truth.
                pass

            deadline = time.monotonic() + self.drain_timeout_seconds
            while time.monotonic() < deadline:
                payload = await self._request_json(
                    lease,
                    "GET",
                    f"/actor-runs/{run_id}",
                    timeout=10.0,
                    classify_credential=False,
                )
                status = self._run_status(payload)
                if status in _TERMINAL_RUN_STATUSES:
                    payload, accounting_settled = await self._settled_terminal_payload(
                        lease,
                        f"/actor-runs/{run_id}",
                        payload,
                    )
                    actual_charge_usd = self._run_usage_total_usd(payload)
                    await self._coordinator_call(
                        "record_run_accounting",
                        lease,
                        actual_cost_usd=actual_charge_usd,
                        cost_final=(
                            accounting_settled
                            and self._run_status(payload) in _TERMINAL_RUN_STATUSES
                            and actual_charge_usd is not None
                        ),
                        optional=True,
                    )
                    await self._coordinator_call(
                        "mark_run_terminal",
                        lease,
                        str(remote_run_id),
                        status,
                    )
                    return status
                await asyncio.sleep(self.poll_interval)
        except ApifyClientError:
            raise
        except (httpx.HTTPError, ValueError):
            raise ApifyClientError(
                "apify_key_drain_pending",
                "Apify Run termination could not be confirmed",
                retryable=True,
            ) from None

        raise ApifyClientError(
            "apify_key_drain_pending",
            "Apify Run termination could not be confirmed within 30 seconds",
            retryable=True,
        )

    async def _run_actor_once(
        self,
        lease: ApifyCredentialLease,
        actor_id: str,
        actor_input: dict[str, Any],
        *,
        max_total_charge_usd: float | None,
        logical_run_id: str | None,
        build_number: str | None,
        max_paid_dataset_items: int,
        dataset_item_limit: int,
        dataset_response_max_bytes: int,
        timeout_seconds: int | None,
    ) -> ApifyActorRunResult:
        start_path = f"/acts/{self._actor_path_id(actor_id)}/runs"
        start_kwargs: dict[str, Any] = {
            "json": actor_input,
            "timeout": 30.0,
        }
        start_params: dict[str, str] = {
            "maxItems": str(max_paid_dataset_items),
        }
        if max_total_charge_usd is not None:
            # ActorOps approvals are stored to six decimal places.  Keeping
            # that precision is safety-critical: rounding an approved
            # $0.006 cap to $0.01 would authorize more spend than requested.
            start_params["maxTotalChargeUsd"] = (
                f"{max_total_charge_usd:.6f}".rstrip("0").rstrip(".")
            )
        if build_number is not None:
            start_params["build"] = build_number
        start_kwargs["params"] = start_params

        try:
            await self._coordinator_call(
                "assert_lease_startable",
                lease,
            )
        except Exception as exc:
            if getattr(exc, "code", None) != "apify_key_drain_pending":
                raise
            await self._release_reservation(
                lease,
                "apify_generation_changed_before_start",
            )
            if await self._should_retry_after_terminal(
                lease,
                "",
                "ABORTED",
            ):
                raise _RetryRunAfterDrain() from None
            raise

        try:
            run = await self._request_json(
                lease,
                "POST",
                start_path,
                **start_kwargs,
            )
        except _ApifyCredentialRejected:
            raise
        except (httpx.TransportError, httpx.DecodingError):
            await self._report_start_outcome_unknown(lease)
            raise ApifyClientError(
                "apify_start_outcome_unknown",
                "Apify Run start outcome is unknown; the key pool is blocked",
                retryable=False,
            ) from None
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code >= 500:
                await self._report_start_outcome_unknown(
                    lease,
                    error_code="apify_start_http_outcome_unknown",
                )
                raise ApifyClientError(
                    "apify_start_outcome_unknown",
                    "Apify Run start outcome is unknown; the key pool is blocked",
                    retryable=False,
                    status_code=status_code,
                ) from None
            await self._release_reservation(
                lease,
                f"apify_start_http_{status_code}",
            )
            if status_code in {404, 410}:
                code = "apify_actor_deleted"
                message = "The selected Actor is unavailable"
            elif status_code in {409, 422}:
                code = "apify_actor_build_unavailable"
                message = "The selected Actor build is unavailable"
            else:
                code = "apify_actor_start_rejected"
                message = "Apify rejected the Actor Run start"
            raise self._safe_http_error(
                code,
                message,
                status_code,
            ) from None
        except ValueError:
            await self._report_start_outcome_unknown(lease)
            raise ApifyClientError(
                "apify_start_outcome_unknown",
                "Apify Run start response could not be reconciled",
                retryable=False,
            ) from None

        data = run.get("data") if isinstance(run, dict) else None
        run_id = data.get("id") if isinstance(data, dict) else None
        dataset_id = data.get("defaultDatasetId") if isinstance(data, dict) else None
        if not run_id:
            await self._report_start_outcome_unknown(lease)
            raise ApifyClientError(
                "apify_start_outcome_unknown",
                "Apify Run response omitted its durable Run identifier",
                retryable=False,
            )
        run_id = str(run_id)
        dataset_id = str(dataset_id) if dataset_id else None

        try:
            await self._coordinator_call(
                "register_run",
                lease,
                run_id,
                dataset_id,
                logical_run_id,
            )
        except Exception as exc:
            if getattr(exc, "code", None) == "apify_key_drain_pending":
                await self.abort_run(lease, run_id)
                if await self._should_retry_after_terminal(
                    lease,
                    run_id,
                    "ABORTED",
                ):
                    raise _RetryRunAfterDrain() from None
                raise
            recovered = await reconcile_failed_run_registration(
                coordinator_call=self._coordinator_call,
                abort_registered_run=self.abort_run,
                abort_unregistered_run=self._abort_remote_without_ledger,
                request_json=self._request_json,
                lease=lease,
                remote_run_id=run_id,
                dataset_id=dataset_id,
            )
            if recovered:
                raise ApifyClientError(
                    "apify_run_registration_failed",
                    "Apify Run registration did not complete cleanly",
                    retryable=False,
                ) from None
            await self._report_start_outcome_unknown(
                lease,
                error_code="apify_start_outcome_unknown",
            )
            raise ApifyClientError(
                "apify_start_outcome_unknown",
                "Apify Run registration could not be reconciled",
                retryable=False,
            ) from None

        if dataset_id is None:
            await self.abort_run(lease, run_id)
            raise ApifyClientError(
                "apify_start_invalid_response",
                "Apify Run response omitted its dataset identifier",
                retryable=True,
            )

        try:
            actual_charge_usd, cost_final = await self._wait_for_run(
                lease,
                run_id,
                reserved_cost_usd=max_total_charge_usd,
                timeout_seconds=timeout_seconds,
            )
        except _ApifyCredentialRejected as exc:
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The started Apify Run requires reconciliation",
                retryable=True,
                status_code=exc.status_code,
            ) from None
        except httpx.HTTPStatusError as exc:
            await self.abort_run(lease, run_id)
            raise self._safe_http_error(
                "apify_run_status_unavailable",
                "Apify rejected a Run status request",
                exc.response.status_code,
            ) from None
        except (httpx.TransportError, httpx.DecodingError):
            await self.abort_run(lease, run_id)
            raise ApifyClientError(
                "apify_run_status_unavailable",
                "Apify Run status is temporarily unavailable",
                retryable=True,
            ) from None
        except ValueError:
            await self.abort_run(lease, run_id)
            raise ApifyClientError(
                "apify_run_status_unavailable",
                "Apify Run status could not be validated",
                retryable=True,
            ) from None
        except TimeoutError:
            # _wait_for_run already aborted and confirmed this Run terminal.
            raise

        try:
            items = await self._request_json(
                lease,
                "GET",
                f"/datasets/{quote(dataset_id, safe='')}/items",
                params={
                    "clean": "true",
                    "limit": str(dataset_item_limit),
                },
                timeout=30.0,
                max_response_bytes=dataset_response_max_bytes,
            )
        except _ApifyCredentialRejected as exc:
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The completed Apify Run dataset requires reconciliation",
                retryable=True,
                status_code=exc.status_code,
            ) from None
        except httpx.HTTPStatusError as exc:
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The completed Apify Run dataset requires reconciliation",
                retryable=True,
                status_code=exc.response.status_code,
            ) from None
        except (httpx.TransportError, httpx.DecodingError):
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The completed Apify Run dataset requires reconciliation",
                retryable=True,
            ) from None
        except ValueError:
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The completed Apify Run dataset requires reconciliation",
                retryable=True,
            ) from None
        if not isinstance(items, list):
            await self._block_started_run(
                lease,
                error_code="apify_run_reconcile_required",
            )
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The completed Apify Run dataset requires reconciliation",
                retryable=True,
            )
        if len(items) > dataset_item_limit:
            raise ApifyClientError(
                "apify_dataset_row_limit_exceeded",
                "The completed Apify dataset exceeded the bounded row limit",
                retryable=False,
            )
        return ApifyActorRunResult(
            items=[item for item in items if isinstance(item, dict)],
            actual_charge_usd=actual_charge_usd,
            cost_final=cost_final,
        )

    async def _wait_for_run(
        self,
        lease: ApifyCredentialLease,
        run_id: str,
        *,
        reserved_cost_usd: float | None,
        timeout_seconds: int | None = None,
        abort_on_timeout: bool = True,
    ) -> tuple[float | None, bool]:
        resolved_timeout_seconds = (
            int(timeout_seconds)
            if timeout_seconds is not None
            else int(self.timeout_seconds)
        )
        deadline = time.monotonic() + resolved_timeout_seconds
        path = f"/actor-runs/{quote(run_id, safe='')}"
        while time.monotonic() < deadline:
            payload = await self._request_json(
                lease,
                "GET",
                path,
                timeout=10.0,
            )
            status = self._run_status(payload)
            if status in _TERMINAL_RUN_STATUSES:
                payload, accounting_settled = await self._settled_terminal_payload(
                    lease,
                    path,
                    payload,
                )
                actual_charge_usd = self._run_usage_total_usd(payload)
                cost_final = (
                    accounting_settled
                    and self._run_status(payload) in _TERMINAL_RUN_STATUSES
                    and actual_charge_usd is not None
                )
                await self._coordinator_call(
                    "record_run_accounting",
                    lease,
                    actual_cost_usd=actual_charge_usd,
                    cost_final=cost_final,
                    reserved_cost_usd=reserved_cost_usd,
                    optional=True,
                )
                mark_result = await self._coordinator_call(
                    "mark_run_terminal",
                    lease,
                    run_id,
                    status,
                )
                if status == "SUCCEEDED":
                    return actual_charge_usd, cost_final
                should_retry = bool(mark_result)
                if self.coordinator is not None and not should_retry:
                    should_retry = await self._should_retry_after_terminal(
                        lease,
                        run_id,
                        status,
                    )
                if should_retry:
                    raise _RetryRunAfterDrain()
                raise ApifyClientError(
                    f"apify_actor_run_{status.lower().replace('-', '_')}",
                    "Actor Run ended before producing a usable dataset",
                    retryable=False,
                )
            await asyncio.sleep(self.poll_interval)

        if abort_on_timeout:
            await self.abort_run(lease, run_id)
        raise TimeoutError(
            f"Apify actor run timed out after {resolved_timeout_seconds}s"
        )

    async def _settled_terminal_payload(
        self,
        lease: ApifyCredentialLease,
        path: str,
        payload: Any,
    ) -> tuple[Any, bool]:
        """Refetch a terminal Run after Apify's documented usage delay.

        Old/fake responses without ``finishedAt`` retain the existing behavior.
        Production Run responses include it, allowing a bounded wait without
        adding a fixed delay when the aggregate is already old enough.
        """

        if self.accounting_settle_delay_seconds <= 0:
            return payload, True
        data = payload.get("data") if isinstance(payload, dict) else None
        finished_raw = data.get("finishedAt") if isinstance(data, dict) else None
        if not isinstance(finished_raw, str) or not finished_raw.strip():
            return payload, True
        try:
            finished_at = datetime.fromisoformat(
                finished_raw.strip().replace("Z", "+00:00")
            )
            if finished_at.tzinfo is None:
                finished_at = finished_at.replace(tzinfo=timezone.utc)
            remaining = (
                finished_at.astimezone(timezone.utc).timestamp()
                + self.accounting_settle_delay_seconds
                - datetime.now(timezone.utc).timestamp()
            )
        except ValueError:
            return payload, False
        if remaining > 0:
            await asyncio.sleep(remaining)
        try:
            refreshed = await self._request_json(
                lease,
                "GET",
                path,
                timeout=10.0,
                classify_credential=False,
            )
        except (httpx.HTTPError, ValueError):
            return payload, False
        return refreshed, True

    async def _handle_credential_failure(
        self,
        lease: ApifyCredentialLease,
        failure: _ApifyCredentialRejected,
    ) -> None:
        if self.coordinator is not None:
            await self._coordinator_call(
                "report_credential_failure",
                lease,
                failure_kind=failure.failure_kind,
                status_code=failure.status_code,
                error_type=failure.error_type,
                abort_run=self.abort_run,
            )
            return

        if failure.remote_run_id and not failure.run_is_terminal:
            await self.abort_run(lease, failure.remote_run_id)

        logger.warning(
            "Apify credential cannot continue failure_kind=%s; trying next credential",
            failure.failure_kind.value,
        )
        if self._legacy_token_index + 1 >= len(self.tokens):
            raise ValueError(
                "All Apify token envs failed: "
                + ", ".join(name for name, _token in self.tokens)
            )

    async def _acquire_credential(
        self,
        attempted_secret_ids: Collection[str],
        *,
        logical_run_id: str | None,
        expected_pool_generation: int | None = None,
    ) -> tuple[ApifyCredentialLease, int | None]:
        if self.coordinator is not None:
            acquire_kwargs: dict[str, Any] = {
                "logical_run_id": logical_run_id,
            }
            if expected_pool_generation is not None:
                acquire_kwargs["expected_pool_generation"] = (
                    expected_pool_generation
                )
            lease = await self._coordinator_call(
                "acquire_credential",
                tuple(attempted_secret_ids),
                **acquire_kwargs,
            )
            if not isinstance(lease, ApifyCredentialLease):
                required = (
                    "secret_id",
                    "secret_version",
                    "pool_generation",
                    "reservation_id",
                    "env_name",
                    "token",
                    "quota_check_required",
                )
                if not all(hasattr(lease, name) for name in required):
                    raise TypeError(
                        "Apify coordinator returned an invalid credential lease"
                    )
            if not str(lease.token or "").strip():
                raise ValueError("Apify coordinator returned an empty token")
            return lease, None

        index = self._legacy_token_index
        while index < len(self.tokens):
            env_name, token = self.tokens[index]
            secret_id = f"legacy:{env_name}"
            if secret_id not in attempted_secret_ids:
                return (
                    ApifyCredentialLease(
                        secret_id=secret_id,
                        secret_version=0,
                        pool_generation=index,
                        env_name=env_name,
                        reservation_id=f"legacy:{index}",
                        token=token,
                    ),
                    index,
                )
            index += 1

        raise ValueError(
            "All Apify token envs failed: "
            + ", ".join(name for name, _token in self.tokens)
        )

    async def _refresh_quota_snapshot(self, lease: ApifyCredentialLease) -> None:
        try:
            user_payload = await self._request_json(
                lease,
                "GET",
                "/users/me",
                timeout=8.0,
            )
            limits_payload = await self._request_json(
                lease,
                "GET",
                "/users/me/limits",
                timeout=8.0,
            )
            snapshot = self._quota_snapshot(user_payload, limits_payload)
        except _ApifyCredentialRejected:
            raise
        except httpx.HTTPStatusError as exc:
            await self._release_reservation(lease, "apify_quota_check_failed")
            raise self._safe_http_error(
                "apify_quota_check_failed",
                "Apify rejected the quota check",
                exc.response.status_code,
            ) from None
        except (httpx.TransportError, httpx.DecodingError):
            await self._release_reservation(lease, "apify_quota_check_failed")
            raise ApifyClientError(
                "apify_quota_check_failed",
                "Apify quota check is temporarily unavailable",
                retryable=True,
            ) from None
        except (TypeError, ValueError):
            await self._release_reservation(lease, "apify_quota_check_failed")
            raise ApifyClientError(
                "apify_quota_check_failed",
                "Apify quota response could not be validated",
                retryable=True,
            ) from None

        await self._coordinator_call(
            "record_quota_snapshot",
            lease,
            **snapshot,
        )
        if snapshot["remaining_included_credits_usd"] <= 0:
            raise _ApifyCredentialRejected(
                ApifyCredentialFailureKind.DEPLETED,
                402,
                "quota-preflight-depleted",
            )

    async def _abort_remote_without_ledger(
        self,
        lease: ApifyCredentialLease,
        run_id: str,
    ) -> None:
        encoded_id = quote(run_id, safe="")
        try:
            await self._request_json(
                lease,
                "POST",
                f"/actor-runs/{encoded_id}/abort",
                params={"gracefully": "false"},
                timeout=10.0,
                classify_credential=False,
            )
        except (httpx.HTTPError, ValueError):
            pass

        deadline = time.monotonic() + self.drain_timeout_seconds
        while time.monotonic() < deadline:
            try:
                payload = await self._request_json(
                    lease,
                    "GET",
                    f"/actor-runs/{encoded_id}",
                    timeout=10.0,
                    classify_credential=False,
                )
            except (httpx.HTTPError, ValueError):
                break
            if self._run_status(payload) in _TERMINAL_RUN_STATUSES:
                return
            await asyncio.sleep(self.poll_interval)
        raise ApifyClientError(
            "apify_key_drain_pending",
            "Unregistered Apify Run termination could not be confirmed",
            retryable=True,
        )

    async def _request_json(
        self,
        lease: ApifyCredentialLease,
        method: str,
        path: str,
        *,
        classify_credential: bool = True,
        **kwargs: Any,
    ) -> Any:
        max_response_bytes = kwargs.pop("max_response_bytes", None)
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {lease.token}",
            "Accept": "application/json",
            # Apify/CDN responses have occasionally declared Brotli while
            # returning bytes that cannot be decoded.  Actor and Dataset
            # payloads are already bounded, so request the identity encoding
            # and keep retries scoped to the same idempotent read.
            "Accept-Encoding": "identity",
        }
        provided_headers = kwargs.pop("headers", None) or {}
        headers.update(provided_headers)
        headers["Accept-Encoding"] = "identity"

        request_method = str(method).upper()
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                if max_response_bytes is None:
                    response = await self.http_client.request(
                        request_method,
                        url,
                        headers=headers,
                        **kwargs,
                    )
                else:
                    content = bytearray()
                    async with self.http_client.stream(
                        request_method,
                        url,
                        headers=headers,
                        **kwargs,
                    ) as streamed:
                        async for chunk in streamed.aiter_bytes():
                            if (
                                len(content) + len(chunk)
                                > int(max_response_bytes)
                            ):
                                raise ApifyClientError(
                                    "apify_dataset_response_too_large",
                                    "The Apify dataset response exceeded the bounded byte limit",
                                    retryable=False,
                                )
                            content.extend(chunk)
                        response = httpx.Response(
                            streamed.status_code,
                            headers=streamed.headers,
                            content=bytes(content),
                            request=streamed.request,
                            extensions=streamed.extensions,
                        )
            except (httpx.TransportError, httpx.DecodingError) as error:
                if request_method != "GET" or attempt >= 2:
                    raise
                delay = min(max(self.retry_base_delay * (2**attempt), 0.0), 30.0)
                logger.warning(
                    "Apify GET response failed category=%s; retrying with the same key in %.1fs",
                    (
                        "decoding"
                        if isinstance(error, httpx.DecodingError)
                        else "transport"
                    ),
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            # Only idempotent reads may be retried inside one HTTP operation.
            # A paid Actor start POST is counted by the outer authorization
            # boundary; retrying it here would bypass Canary's one-start cap.
            retryable_response = request_method == "GET" and (
                response.status_code == 429 or response.status_code >= 500
            )
            if not retryable_response or attempt >= 2:
                break
            retry_after = response.headers.get("Retry-After")
            try:
                delay = (
                    float(retry_after)
                    if retry_after
                    else self.retry_base_delay * (2**attempt)
                )
            except ValueError:
                delay = self.retry_base_delay * (2**attempt)
            delay = min(max(delay, 0.0), 30.0)
            logger.warning(
                "Apify %s request returned retryable HTTP %d; retrying with "
                "the same key in %.1fs",
                request_method,
                response.status_code,
                delay,
            )
            await asyncio.sleep(delay)

        if response is None:  # pragma: no cover - defensive loop invariant
            raise RuntimeError("Apify request produced no response")
        if classify_credential:
            rejected = self._credential_rejection(response)
            if rejected is not None:
                raise rejected
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            raise ValueError("Apify response was not valid JSON") from None

    @staticmethod
    def _positive_limit(value: Any, *, label: str, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must be an integer")
        if value < 1 or value > maximum:
            raise ValueError(f"{label} must be between 1 and {maximum}")
        return int(value)

    @staticmethod
    def _optional_build_number(value: str | None) -> str | None:
        if value is None:
            return None
        build = str(value).strip()
        if not build or len(build) > 128:
            raise ValueError("build_number must be a non-empty bounded string")
        if any(character.isspace() for character in build):
            raise ValueError("build_number cannot contain whitespace")
        return build

    async def _report_start_outcome_unknown(
        self,
        lease: ApifyCredentialLease,
        *,
        error_code: str = "apify_start_outcome_unknown",
    ) -> None:
        try:
            await self._coordinator_call(
                "report_start_outcome_unknown",
                lease,
                error_code,
            )
        except ApifyClientError:
            raise
        except Exception:
            # The remote POST may already have created a paid Run.  A failure
            # in the local poison callback must never degrade into a generic
            # Actor error that lets ActorOps try another slot.
            raise ApifyClientError(
                "apify_start_outcome_unknown",
                "Apify Run start outcome is unknown; reconciliation is required",
                retryable=False,
            ) from None

    async def _block_started_run(
        self,
        lease: ApifyCredentialLease,
        *,
        error_code: str,
    ) -> None:
        """Fail closed after a durable Run id exists; never start a second Run."""

        if self.coordinator is None:
            return
        try:
            if getattr(self.coordinator, "block_run_reconciliation", None) is not None:
                await self._coordinator_call(
                    "block_run_reconciliation",
                    lease,
                    error_code,
                )
                return
            await self._report_start_outcome_unknown(
                lease,
                error_code=error_code,
            )
        except ApifyClientError:
            raise
        except Exception:
            # A known remote Run remains a poison state even if the durable
            # coordinator cannot persist its reconciliation barrier.
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The started Apify Run requires reconciliation",
                retryable=True,
            ) from None

    async def _complete_started_run(
        self,
        lease: ApifyCredentialLease,
    ) -> None:
        try:
            await self._coordinator_call(
                "complete_run_reconciliation",
                lease,
            )
        except Exception:
            raise ApifyClientError(
                "apify_run_reconcile_required",
                "The durable Apify Run reconciliation is not yet complete",
                retryable=True,
            ) from None

    async def _release_reservation(
        self,
        lease: ApifyCredentialLease,
        error_code: str,
    ) -> None:
        await self._coordinator_call(
            "release_reservation",
            lease,
            error_code,
        )

    async def _should_retry_after_terminal(
        self,
        lease: ApifyCredentialLease,
        run_id: str,
        status: str,
    ) -> bool:
        if self.coordinator is None:
            return False
        deadline = time.monotonic() + self.drain_timeout_seconds
        while True:
            decision = await self._coordinator_call(
                "should_retry_after_terminal",
                lease,
                run_id,
                status,
            )
            if decision is not None:
                return bool(decision)
            if time.monotonic() >= deadline:
                raise ApifyClientError(
                    "apify_key_drain_pending",
                    "Apify key failover is still draining",
                    retryable=True,
                )
            await asyncio.sleep(self.poll_interval)

    async def _coordinator_call(
        self,
        method_name: str,
        *args: Any,
        optional: bool = False,
        default: Any = None,
        **kwargs: Any,
    ) -> Any:
        if self.coordinator is None:
            return default
        method = getattr(self.coordinator, method_name, None)
        if method is None:
            if optional:
                return default
            raise TypeError(
                f"Apify coordinator does not implement {method_name}()"
            )
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _run_status(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        data = payload.get("data")
        if not isinstance(data, dict):
            return ""
        return str(data.get("status") or "").upper()

    @staticmethod
    def _run_usage_total_usd(payload: Any) -> float | None:
        """Read only Apify's terminal aggregate charge, never raw usage details."""

        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        value = data.get("usageTotalUsd")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number) or number < 0:
            return None
        return number

    @classmethod
    def _credential_rejection(
        cls,
        response: httpx.Response,
    ) -> _ApifyCredentialRejected | None:
        if response.status_code == 429:
            return None
        error_type = cls._response_error_type(response)
        if response.status_code == 402 or cls._is_explicit_quota_type(error_type):
            return _ApifyCredentialRejected(
                ApifyCredentialFailureKind.DEPLETED,
                response.status_code,
                error_type,
            )
        if (
            response.status_code == 401
            or error_type in _INVALID_TOKEN_ERROR_TYPES
        ):
            return _ApifyCredentialRejected(
                ApifyCredentialFailureKind.INVALID,
                response.status_code,
                error_type,
            )
        return None

    @staticmethod
    def _response_error_type(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        error = payload.get("error")
        if isinstance(error, dict):
            raw_type = error.get("type") or error.get("code")
        else:
            raw_type = payload.get("errorType") or payload.get("code")
        normalized = str(raw_type or "").strip().lower().replace("_", "-")
        return normalized or None

    @staticmethod
    def _is_explicit_quota_type(error_type: str | None) -> bool:
        if not error_type:
            return False
        if error_type in _EXPLICIT_QUOTA_ERROR_TYPES:
            return True
        return (
            "quota" in error_type
            or (
                "credit" in error_type
                and any(
                    marker in error_type
                    for marker in ("exhausted", "insufficient", "not-enough")
                )
            )
            or ("usage" in error_type and "limit" in error_type)
        )

    @staticmethod
    def _quota_snapshot(
        user_payload: Any,
        limits_payload: Any,
    ) -> dict[str, Any]:
        try:
            user_data = user_payload["data"]
            plan = user_data["plan"]
            limits_data = limits_payload["data"]
            cycle = limits_data["monthlyUsageCycle"]
            limits = limits_data["limits"]
            current = limits_data["current"]
            included = ApifyClient._safe_number(plan["monthlyUsageCreditsUsd"])
            usage = ApifyClient._safe_number(current["monthlyUsageUsd"])
            hard_limit = ApifyClient._safe_number(limits["maxMonthlyUsageUsd"])
            cycle_start = ApifyClient._safe_timestamp(cycle["startAt"])
            cycle_end = ApifyClient._safe_timestamp(cycle["endAt"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Apify quota response was not valid") from None

        return {
            "remaining_included_credits_usd": max(included - usage, 0.0),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "cycle_start_at": cycle_start,
            "cycle_end_at": cycle_end,
            "monthly_included_credits_usd": included,
            "monthly_usage_usd": usage,
            "max_monthly_usage_usd": hard_limit,
            "remaining_hard_limit_usd": max(hard_limit - usage, 0.0),
        }

    @staticmethod
    def _safe_number(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("quota number is invalid")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError("quota number is invalid")
        return number

    @staticmethod
    def _safe_timestamp(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TypeError("quota timestamp is invalid")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("quota timestamp must include a timezone")
        return value

    @staticmethod
    def _safe_http_error(
        code: str,
        message: str,
        status_code: int,
    ) -> ApifyClientError:
        return ApifyClientError(
            code,
            f"{message} (HTTP {status_code})",
            retryable=status_code == 429 or status_code >= 500,
            status_code=status_code,
        )

    @staticmethod
    def _actor_path_id(actor_id: str) -> str:
        normalized = actor_id.strip().replace("/", "~")
        return quote(normalized, safe="~")
