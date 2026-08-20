"""Apify-specific durable Run reader for ActorOps v2 reconciliation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ...scrapers.apify_client import ApifyClient
from ...storage.service_store import ServiceStore
from ..apify_pool_runtime import apify_coordinator_for_workspace
from .ports import (
    ReconciliationRunLink,
    ReconciliationRunObservation,
    ReconciliationRunResolution,
)


_PENDING_STATUSES = frozenset(
    {"reserved", "starting", "running", "aborting", "start_outcome_unknown"}
)


class ApifyRunLedger:
    """Correlate v2 Attempts to existing `apify_actor_runs` reservations only."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        workspace_id: str,
        data_dir: str | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)
        self.data_dir = data_dir or str(store.data_dir)
        self.http_transport = http_transport
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def resolve(
        self, attempt: Mapping[str, object]
    ) -> ReconciliationRunResolution:
        attempt_id = str(attempt["attempt_id"])
        remote_run_id = str(attempt["remote_run_id"] or "") or None
        rows = self.store.connect().execute(
            """SELECT id, logical_run_id, remote_run_id, dataset_id, status,
                      created_at, updated_at
               FROM apify_actor_runs
               WHERE workspace_id=? AND purpose='acquisition' AND logical_run_id=?
               ORDER BY created_at, id""",
            (self.workspace_id, attempt_id),
        ).fetchall()
        if remote_run_id is not None:
            matches = [row for row in rows if str(row["remote_run_id"] or "") == remote_run_id]
            if len(matches) != 1:
                return ReconciliationRunResolution(None, ambiguous=bool(rows))
            return ReconciliationRunResolution(self._link(matches[0]))
        known = [row for row in rows if row["remote_run_id"]]
        if len(known) == 1:
            return ReconciliationRunResolution(self._link(known[0]))
        if len(known) > 1:
            return ReconciliationRunResolution(None, ambiguous=True)
        pending = [row for row in rows if str(row["status"] or "") in _PENDING_STATUSES]
        if len(pending) == 1:
            return ReconciliationRunResolution(self._link(pending[0]))
        return ReconciliationRunResolution(None, ambiguous=bool(pending))

    async def read_known(
        self, link: ReconciliationRunLink
    ) -> ReconciliationRunObservation:
        remote_run_id = str(link.remote_run_id or "")
        if not remote_run_id:
            raise ValueError("known Apify Run is missing its remote identifier")
        coordinator = self._coordinator()
        lease = coordinator.lease_for_run(link.reservation_id)
        async with self._client(coordinator) as client:
            await client.refresh_registered_run_status(lease, remote_run_id)
        durable = coordinator.get_run(link.reservation_id)
        if durable is None:
            raise LookupError("Apify reservation disappeared during reconciliation")
        return ReconciliationRunObservation(
            status=str(durable.get("status") or "running"),
            actual_cost_usd=self._cost(durable.get("charge_actual_usd")),
            cost_final=bool(durable.get("charge_final")),
            dataset_id=str(durable.get("dataset_id") or "") or None,
        )

    async def prove_no_start(self, link: ReconciliationRunLink) -> bool:
        if link.remote_run_id or str(link.status) not in _PENDING_STATUSES:
            return False
        started_at = self._timestamp(link.created_at)
        unknown_at = self._timestamp(link.updated_at)
        if self.now().astimezone(timezone.utc) < unknown_at + timedelta(seconds=30):
            return False
        coordinator = self._coordinator()
        lease = coordinator.lease_for_run(link.reservation_id)
        async with self._client(coordinator) as client:
            return await client.prove_no_user_run_in_window(
                lease,
                started_after=self._apify_time(started_at - timedelta(seconds=5)),
                started_before=self._apify_time(unknown_at + timedelta(seconds=30)),
            )

    async def settle_proven_no_start(self, link: ReconciliationRunLink) -> None:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        stamp = self.now().astimezone(timezone.utc).isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """UPDATE apify_actor_runs
                   SET status='start_rejected', last_error_code='actorops_v2_proven_no_start',
                       charge_reserved_usd=0, charge_actual_usd=0, charge_final=1,
                       terminal_at=?, updated_at=?
                   WHERE id=? AND workspace_id=? AND purpose='acquisition'
                     AND remote_run_id IS NULL
                     AND status IN ('reserved', 'starting', 'start_outcome_unknown')""",
                (stamp, stamp, link.reservation_id, self.workspace_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("Apify reservation changed before no-start settlement")
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise

    def _coordinator(self) -> Any:
        coordinator = apify_coordinator_for_workspace(
            self.store,
            workspace_id=self.workspace_id,
            data_dir=self.data_dir,
        )
        if coordinator is None:
            raise RuntimeError("actorops_v2 Apify ledger is unavailable")
        return coordinator

    def _client(self, coordinator: Any) -> _LedgerClientContext:
        timeout = httpx.Timeout(15.0, connect=5.0)
        http_client = httpx.AsyncClient(
            timeout=timeout, transport=self.http_transport, trust_env=False
        )
        return _LedgerClientContext(ApifyClient(coordinator=coordinator, http_client=http_client), http_client)

    @staticmethod
    def _link(row: Any) -> ReconciliationRunLink:
        return ReconciliationRunLink(
            reservation_id=str(row["id"]),
            remote_run_id=str(row["remote_run_id"] or "") or None,
            dataset_id=str(row["dataset_id"] or "") or None,
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _apify_time(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _cost(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if value >= 0 else None


class _LedgerClientContext:
    """Close the short-lived HTTP client without exposing it to generic code."""

    def __init__(self, client: ApifyClient, http_client: httpx.AsyncClient) -> None:
        self.client = client
        self.http_client = http_client

    async def __aenter__(self) -> ApifyClient:
        return self.client

    async def __aexit__(self, *_args: object) -> None:
        await self.http_client.aclose()


__all__ = ["ApifyRunLedger"]
