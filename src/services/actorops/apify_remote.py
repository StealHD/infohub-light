"""Apify Client bridge that keeps v2 unknown-start scope local."""

from __future__ import annotations

import inspect
from typing import Any

from ...scrapers.apify_client import ApifyClient, ApifyClientError
from .domain import FailureClass
from .ports import AttemptEventSink, RemoteRunRequest, RemoteRunResult
from .runtime import ActorOpsRuntimeError


class _LocalAttemptCoordinator:
    def __init__(self, base: Any, events: AttemptEventSink) -> None:
        self.base = base
        self.events = events
        self.remote_run_id: str | None = None
        self.dataset_id: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    async def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        value = getattr(self.base, name)(*args, **kwargs)
        return await value if inspect.isawaitable(value) else value

    async def acquire_credential(self, *args: Any, **kwargs: Any) -> Any:
        lease = await self._call("acquire_credential", *args, **kwargs)
        self.events.starting(
            secret_ref_id=str(lease.secret_id),
            secret_version=int(lease.secret_version),
            pool_generation=int(lease.pool_generation),
        )
        return lease

    async def register_run(
        self,
        lease: Any,
        remote_run_id: str,
        dataset_id: str | None,
        logical_run_id: str | None = None,
    ) -> None:
        await self._call(
            "register_run", lease, remote_run_id, dataset_id, logical_run_id
        )
        self.remote_run_id = str(remote_run_id)
        self.dataset_id = str(dataset_id) if dataset_id else None
        self.events.registered(
            remote_run_id=self.remote_run_id, dataset_id=self.dataset_id
        )
        self.events.running()

    async def report_start_outcome_unknown(
        self, lease: Any, error_code: str = "apify_start_outcome_unknown"
    ) -> None:
        self.events.start_unknown(error_code=error_code)

    async def block_run_reconciliation(
        self, lease: Any, error_code: str = "apify_run_reconcile_required"
    ) -> None:
        self.events.remote_unknown(error_code=error_code)


class ApifyV2RemoteClient:
    """Execute one bounded Actor request through an existing per-source client."""

    def __init__(self, client: ApifyClient) -> None:
        self.client = client

    async def execute(
        self, request: RemoteRunRequest, events: AttemptEventSink
    ) -> RemoteRunResult:
        base = self.client.coordinator
        if base is None:
            raise ActorOpsRuntimeError(
                "actorops_v2_credential_coordinator_required",
                failure_class=FailureClass.CREDENTIAL,
            )
        coordinator = _LocalAttemptCoordinator(base, events)
        self.client.coordinator = coordinator
        try:
            result = await self.client.run_actor_detailed(
                request.actor_id,
                dict(request.actor_input),
                max_total_charge_usd=request.max_total_charge_usd,
                logical_run_id=request.attempt_id,
                build_number=request.build_number,
                max_paid_dataset_items=request.max_items,
                dataset_item_limit=min(max(request.max_items + 1, 2), 100),
                max_remote_starts=3,
            )
        except ApifyClientError as error:
            raise ActorOpsRuntimeError(
                str(error.code), failure_class=_failure_class(str(error.code))
            ) from None
        finally:
            self.client.coordinator = base
        if coordinator.remote_run_id is None:
            raise ActorOpsRuntimeError(
                "actorops_v2_remote_run_unregistered",
                failure_class=FailureClass.REMOTE_UNKNOWN,
            )
        return RemoteRunResult(
            rows=tuple(result.items),
            remote_run_id=coordinator.remote_run_id,
            dataset_id=coordinator.dataset_id,
            actual_cost_usd=result.actual_charge_usd,
            cost_final=result.cost_final,
        )


def _failure_class(code: str) -> FailureClass:
    normalized = code.casefold()
    if "start_outcome_unknown" in normalized or "reconcile_required" in normalized:
        return FailureClass.REMOTE_UNKNOWN
    if any(marker in normalized for marker in ("key", "quota", "pool", "token", "credential")):
        return FailureClass.CREDENTIAL
    if any(marker in normalized for marker in ("target", "account_private", "account_not_found")):
        return FailureClass.TARGET
    if any(marker in normalized for marker in ("actor", "build", "manifest", "dataset")):
        return FailureClass.CANDIDATE
    return FailureClass.INTERNAL


__all__ = ["ApifyV2RemoteClient"]
