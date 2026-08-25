"""Automatic, local-only readiness and activation for v2 bindings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .binding_service import ActorOpsBindingError, ActorOpsBindingService


@dataclass(frozen=True, slots=True)
class BindingReconcileResult:
    source_id: str
    state: str
    binding_status: str
    reason: str | None
    proof_kind: str | None
    binding_promoted: bool
    source_activated: bool
    source_enabled: bool

    def public(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BindingReconcileSummary:
    checked_count: int
    verified_binding_count: int
    enabled_source_count: int
    blocked_binding_count: int

    def public(self) -> dict[str, int]:
        return asdict(self)


class ActorOpsBindingReconciler:
    """Converge Binding facts without creating a remote Actor run."""

    def __init__(self, store: Any, *, workspace_id: str) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)
        self.bindings = ActorOpsBindingService(
            store, workspace_id=self.workspace_id
        )

    def reconcile_source(self, source_id: str) -> BindingReconcileResult:
        binding = self.bindings.repository.get_binding(source_id)
        source = self._source(source_id)
        if binding.status == "disabled":
            source = self._disable_source(source_id, source)
            return self._result(
                binding,
                source,
                state="disabled",
                reason="actorops_v2_binding_disabled",
                proof_kind=None,
                binding_promoted=False,
                source_activated=False,
            )
        evidence = self.bindings.assess(source_id)
        promoted = False
        if binding.status == "pending":
            if not evidence.eligible:
                source = self._disable_source(source_id, source)
                return self._result(
                    binding,
                    source,
                    state="preparing",
                    reason=evidence.reason,
                    proof_kind=evidence.proof_kind,
                    binding_promoted=False,
                    source_activated=False,
                )
            binding = self.bindings.verify(
                source_id,
                expected_binding_version=binding.binding_version,
                expected_target_fingerprint=binding.target_fingerprint,
            )
            promoted = True
        usage = self.store.source_subscription_usage(source_id)
        if int(usage["enabled_subscriber_count"]) < 1:
            source = self._source(source_id)
            if bool(source.get("enabled")):
                with self.bindings.repository.transaction():
                    self.store.update_source(source_id, enabled=False, commit=False)
                source = self._source(source_id)
            return self._result(
                binding,
                source,
                state="preparing",
                reason="actorops_v2_subscription_inactive",
                proof_kind=evidence.proof_kind,
                binding_promoted=promoted,
                source_activated=False,
            )
        execution = self.bindings.execution_state(source_id)
        if not execution.allowed:
            return self._result(
                binding,
                self._source(source_id),
                state="preparing",
                reason=execution.reason,
                proof_kind=evidence.proof_kind,
                binding_promoted=promoted,
                source_activated=False,
            )
        source = self._source(source_id)
        source_activated = not bool(source.get("enabled"))
        if source_activated:
            self.bindings.enable_ready(source_id)
            source = self._source(source_id)
        return self._result(
            binding,
            source,
            state="enabled",
            reason=None,
            proof_kind=evidence.proof_kind,
            binding_promoted=promoted,
            source_activated=source_activated,
        )

    def reconcile_route(
        self, route_id: str, *, include_ready: bool = True
    ) -> BindingReconcileSummary:
        return self._reconcile_many(
            binding.source_id
            for binding in self.bindings.repository.list_route_bindings(route_id)
            if binding.status == "pending"
            or (include_ready and binding.status == "ready")
        )

    def reconcile_workspace(self, *, limit: int = 100) -> BindingReconcileSummary:
        rows = self.bindings.repository.connection.execute(
            """SELECT binding.source_id
               FROM actor_source_bindings_v2 AS binding
               JOIN source_catalog AS source ON source.id=binding.source_id
               WHERE binding.workspace_id=?
                 AND (
                   binding.status='pending'
                   OR (binding.status='ready' AND source.enabled=0)
                   OR (binding.status='disabled' AND source.enabled=1)
                 )
                 AND (
                   binding.status='disabled' OR EXISTS (
                     SELECT 1 FROM user_subscriptions AS subscription
                     WHERE subscription.source_id=binding.source_id
                       AND subscription.enabled=1
                   )
                 )
               ORDER BY binding.updated_at, binding.source_id
               LIMIT ?""",
            (self.workspace_id, max(1, min(int(limit), 100))),
        ).fetchall()
        return self._reconcile_many(str(row["source_id"]) for row in rows)

    def _source(self, source_id: str) -> dict[str, Any]:
        source = self.store.get_source(source_id)
        if source is None or str(source.get("workspace_id")) != self.workspace_id:
            raise ActorOpsBindingError("actorops_v2_source_not_found")
        return source

    def _disable_source(
        self, source_id: str, source: dict[str, Any]
    ) -> dict[str, Any]:
        if bool(source.get("enabled")):
            with self.bindings.repository.transaction():
                self.store.update_source(source_id, enabled=False, commit=False)
            return self._source(source_id)
        return source

    def _reconcile_many(
        self, source_ids: Iterable[str]
    ) -> BindingReconcileSummary:
        results: list[BindingReconcileResult] = []
        for source_id in source_ids:
            try:
                results.append(self.reconcile_source(str(source_id)))
            except ActorOpsBindingError as error:
                binding = self.bindings.repository.get_binding(str(source_id))
                source = self.store.get_source(str(source_id)) or {}
                results.append(
                    self._result(
                        binding,
                        source,
                        state="preparing",
                        reason=error.code,
                        proof_kind=None,
                        binding_promoted=False,
                        source_activated=False,
                    )
                )
        return self._summary(results)

    @staticmethod
    def _result(
        binding: Any,
        source: dict[str, Any],
        *,
        state: str,
        reason: str | None,
        proof_kind: str | None,
        binding_promoted: bool,
        source_activated: bool,
    ) -> BindingReconcileResult:
        return BindingReconcileResult(
            source_id=str(binding.source_id),
            state=state,
            binding_status=str(binding.status),
            reason=reason,
            proof_kind=proof_kind,
            binding_promoted=binding_promoted,
            source_activated=source_activated,
            source_enabled=bool(source.get("enabled")),
        )

    @staticmethod
    def _summary(
        results: list[BindingReconcileResult],
    ) -> BindingReconcileSummary:
        return BindingReconcileSummary(
            checked_count=len(results),
            verified_binding_count=sum(item.binding_promoted for item in results),
            enabled_source_count=sum(item.source_activated for item in results),
            blocked_binding_count=sum(item.state == "preparing" for item in results),
        )


__all__ = [
    "ActorOpsBindingReconciler",
    "BindingReconcileResult",
    "BindingReconcileSummary",
]
