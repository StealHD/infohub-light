"""Thin source-facing ActorOps v2 service and v1 compatibility facade."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .adapters import build_source_registry
from .apify_remote import ApifyV2RemoteClient
from .domain import ExecutionSnapshot, RuntimeMode
from .ports import ExecutionResult, FetchWindow, PublicationProof
from .publication import (
    ActorOpsV2RoutedList,
    publication_proof,
    v2_proof_payload,
)
from .readiness import actorops_v2_enabled, require_actorops_v2_if_enabled
from .repository import ActorOpsRepository
from .repository_errors import ActorOpsRepositoryError
from .runtime import ActorOpsRuntime


@dataclass(slots=True)
class V2ExecutionHandle:
    snapshot: ExecutionSnapshot
    proof: PublicationProof | None = None
    latest_published_at: str | None = None
    latest_item_id_hash: str | None = None
    actorops_version: int = 2


class ActorOpsV2Service:
    def __init__(self, store: Any, *, workspace_id: str) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)
        self.repository = ActorOpsRepository(store.connect(), self.workspace_id)
        self._handles: list[V2ExecutionHandle] = []

    def freeze_execution(self, route_id: str, *, source_id: str) -> V2ExecutionHandle:
        binding = self.repository.get_binding(source_id)
        handle = V2ExecutionHandle(
            self.repository.freeze_execution(
                route_id, source_id, binding.target_fingerprint
            )
        )
        self._handles.append(handle)
        return handle

    async def fetch_subscription(
        self,
        *,
        subscription: Any,
        since: datetime,
        client_factory: Any,
        job_id: str | None,
        handle: V2ExecutionHandle,
    ) -> list[Any]:
        client = client_factory()
        registry = build_source_registry(subscription, client.http_client)
        runtime = ActorOpsRuntime(
            self.repository, registry, ApifyV2RemoteClient(client)
        )
        result = await runtime.fetch(
            route_id=handle.snapshot.route.route_id,
            source_id=str(subscription.source_id),
            source_config={"target": str(subscription.target)},
            window=FetchWindow(
                max_items=int(subscription.fetch_limit),
                since=since.astimezone(timezone.utc),
                until=datetime.now(timezone.utc),
            ),
            logical_job_id=str(job_id or subscription.source_id),
        )
        self._latch(handle, result)
        items = self._project_items(result.items, subscription, result.execution_mode)
        return ActorOpsV2RoutedList(
            items,
            v2_proof_payload(
                result.publication_proof,
                latest_published_at=handle.latest_published_at,
                latest_item_id_hash=handle.latest_item_id_hash,
            ),
        )

    def assert_publishable(self, handle: V2ExecutionHandle) -> None:
        if handle.proof is not None:
            self.repository.assert_publishable(handle.proof)

    def publish_pending_successes(self, *, connection: Any) -> None:
        repository = ActorOpsRepository(connection, self.workspace_id)
        for handle in self._handles:
            if not all(
                (handle.proof, handle.latest_published_at, handle.latest_item_id_hash)
            ):
                continue
            repository.publish_success(
                handle.proof,
                latest_published_at=str(handle.latest_published_at),
                latest_item_id_hash=str(handle.latest_item_id_hash),
            )

    def capture_publication_result(self, items: Any) -> None:
        payload = getattr(items, "_actorops_v2_publication_proof", None)
        if not isinstance(payload, dict):
            return
        proof = publication_proof(payload)
        handle = next(
            (
                item for item in self._handles
                if item.snapshot.binding.source_id == proof.source_id
                and item.snapshot.route.route_id == proof.route_id
            ),
            None,
        )
        if handle is None:
            return
        handle.proof = proof
        handle.latest_published_at = payload.get("latest_published_at")
        handle.latest_item_id_hash = payload.get("latest_item_id_hash")

    @staticmethod
    def _latch(handle: V2ExecutionHandle, result: ExecutionResult) -> None:
        handle.proof = result.publication_proof
        if (
            result.semantic_outcome == "advanced"
            and result.latest_published_at
            and result.latest_item_id
        ):
            handle.latest_published_at = result.latest_published_at
            handle.latest_item_id_hash = hashlib.sha256(
                result.latest_item_id.encode("utf-8")
            ).hexdigest()

    @staticmethod
    def _project_items(items: tuple[object, ...], subscription: Any, mode: str) -> list[Any]:
        projected = []
        analysis_mode = getattr(subscription.analysis_mode, "value", subscription.analysis_mode)
        for value in items:
            item = value.model_copy(deep=True)
            item.metadata.update(
                {
                    "source_id": str(subscription.source_id),
                    "source_key": str(subscription.source_key or subscription.target),
                    "source_name": str(subscription.source_display_name or subscription.target),
                    "tags": list(subscription.tags),
                    "topics": list(subscription.topics),
                    "personal_tags": list(subscription.personal_tags),
                    "analysis_mode": str(analysis_mode),
                    "acquisition_origin": (
                        "apify_actor" if mode == "actor" else "native_fallback"
                    ),
                    **({"channel": subscription.channel} if subscription.channel else {}),
                }
            )
            projected.append(item)
        return projected


class ActorOpsCompatibilityService:
    def __init__(self, store: Any, *, workspace_id: str) -> None:
        from ..apify_actor_ops import ApifyActorOpsService

        self.store = store
        self.workspace_id = str(workspace_id)
        self.v1 = ApifyActorOpsService(store, workspace_id=self.workspace_id)
        self.v2 = ActorOpsV2Service(store, workspace_id=self.workspace_id)

    def freeze_execution(self, route_id: str, *, source_id: str):
        route = self.v2.repository.get_route(route_id)
        if route.runtime_mode is RuntimeMode.ACTIVE:
            return self.v2.freeze_execution(route_id, source_id=source_id)
        if route.runtime_mode is RuntimeMode.SHADOW:
            try:
                self.v2.freeze_execution(route_id, source_id=source_id)
            except ActorOpsRepositoryError:
                pass
        return self.v1.freeze_execution(route_id, source_id=source_id)

    def assert_publishable(self, snapshot: Any) -> None:
        if isinstance(snapshot, V2ExecutionHandle):
            self.v2.assert_publishable(snapshot)
        else:
            self.v1.assert_publishable(snapshot)

    async def fetch_subscription(
        self,
        *,
        subscription: Any,
        since: datetime,
        client_factory: Any,
        job_id: str | None,
        snapshot: Any,
    ) -> list[Any]:
        if not isinstance(snapshot, V2ExecutionHandle):
            raise TypeError("v1 snapshots use the compatibility source executor")
        return await self.v2.fetch_subscription(
            subscription=subscription,
            since=since,
            client_factory=client_factory,
            job_id=job_id,
            handle=snapshot,
        )

    def publish_pending_successes(self, *, connection: Any) -> None:
        self.v2.publish_pending_successes(connection=connection)

    def capture_publication_result(self, items: Any) -> None:
        self.v2.capture_publication_result(items)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.v1, name)


def build_source_actorops_service(store: Any, *, workspace_id: str) -> Any:
    if not actorops_v2_enabled():
        from ..apify_actor_ops import ApifyActorOpsService

        return ApifyActorOpsService(store, workspace_id=workspace_id)
    require_actorops_v2_if_enabled(store)
    return ActorOpsCompatibilityService(store, workspace_id=workspace_id)


__all__ = [
    "ActorOpsCompatibilityService",
    "ActorOpsV2Service",
    "V2ExecutionHandle",
    "build_source_actorops_service",
]
