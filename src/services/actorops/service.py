"""Thin source-facing ActorOps v2 service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .adapters import build_source_registry
from .apify_remote import ApifyV2RemoteClient
from .domain import ExecutionSnapshot, FailureClass, RuntimeMode
from .errors import ActorOpsRuntimeError
from .identity import stable_actor_item_id
from .ports import ExecutionResult, FetchWindow, PublicationProof
from .publication import (
    ActorOpsV2RoutedList,
    publication_proof,
    v2_proof_payload,
)
from .readiness import require_actorops_v2_schema
from .repository import ActorOpsRepository
from .runtime import ActorOpsRuntime


@dataclass(slots=True)
class V2ExecutionHandle:
    snapshot: ExecutionSnapshot
    proof: PublicationProof | None = None
    latest_published_at: str | None = None
    latest_item_id_hash: str | None = None
    actorops_version: int = 2


class ActorOpsSourceServiceProtocol(Protocol):
    def freeze_execution(self, route_id: str, *, source_id: str) -> Any: ...

    async def fetch_subscription(self, **values: Any) -> list[Any]: ...

    def assert_publishable(self, handle: Any) -> None: ...

    def publish_pending_successes(self, *, connection: Any) -> None: ...


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
        snapshot: V2ExecutionHandle,
        public_http_client: Any | None = None,
    ) -> list[Any]:
        handle = snapshot
        active = handle.snapshot.route.runtime_mode is RuntimeMode.ACTIVE
        client = client_factory() if active else None
        http_client = public_http_client or getattr(client, "http_client", None)
        registry = build_source_registry(subscription, http_client)
        runtime = ActorOpsRuntime(
            self.repository, registry, ApifyV2RemoteClient(client)  # type: ignore[arg-type]
        )
        result = await runtime.fetch(
            route_id=handle.snapshot.route.route_id,
            source_id=str(subscription.source_id),
            source_config={"target": str(subscription.target)},
            window=FetchWindow(
                max_items=int(subscription.fetch_limit),
                since=_acquisition_since(
                    handle.snapshot.binding,
                    since.astimezone(timezone.utc),
                ),
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
            source_avatar_url=result.source_avatar_url,
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
        source_key = str(
            subscription.source_key
            or f"apify_social:{subscription.profile_id}:{subscription.source_id}"
        )
        for value in items:
            item = value.model_copy(deep=True)
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            native_id = str(metadata.get("native_id") or "")
            if native_id and metadata.get("catalog_type") != "rss":
                item.id = stable_actor_item_id(
                    str(metadata.get("platform") or ""), source_key, native_id
                )
            item.metadata.update(
                {
                    "source_id": str(subscription.source_id),
                    "source_key": source_key,
                    "source_display_name": str(subscription.source_display_name or subscription.target),
                    "catalog_source_type": str(
                        subscription.catalog_source_type or item.source_type.value
                    ),
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


def build_source_actorops_service(
    store: Any, *, workspace_id: str
) -> ActorOpsSourceServiceProtocol:
    require_actorops_v2_schema(store)
    return ActorOpsV2Service(store, workspace_id=workspace_id)


def _acquisition_since(binding: Any, requested: datetime) -> datetime:
    """Catch up from the durable source watermark, not the Feed display window."""

    raw_watermark = getattr(binding, "watermark_latest_published_at", None)
    if not raw_watermark:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    try:
        watermark = datetime.fromisoformat(
            str(raw_watermark).replace("Z", "+00:00")
        )
    except ValueError:
        raise ActorOpsRuntimeError(
            "actorops_v2_watermark_invalid",
            failure_class=FailureClass.CONFIGURATION,
        ) from None
    if watermark.tzinfo is None:
        watermark = watermark.replace(tzinfo=timezone.utc)
    else:
        watermark = watermark.astimezone(timezone.utc)
    return min(requested, watermark)


__all__ = [
    "ActorOpsSourceServiceProtocol",
    "ActorOpsV2Service",
    "V2ExecutionHandle",
    "build_source_actorops_service",
]
