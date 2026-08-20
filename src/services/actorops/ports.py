"""Small platform ports for ActorOps v2 adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .domain import RouteKey


@dataclass(frozen=True, slots=True)
class TargetSpec:
    canonical_url: str
    native_id: str | None = None
    handle: str | None = None
    native_url: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoverySpec:
    queries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActorManifest:
    actor_id: str
    build_id: str
    build_number: str
    manifest_json: str
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class FetchWindow:
    max_items: int
    since: datetime
    until: datetime | None


@dataclass(frozen=True, slots=True)
class NormalizedBatch:
    items: tuple[object, ...]
    semantic_outcome: str
    latest_published_at: str | None = None
    latest_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class NativeFallbackResult:
    supported: bool
    items: tuple[object, ...] = ()
    degraded_reason: str | None = None

    @classmethod
    def unsupported(cls) -> NativeFallbackResult:
        return cls(supported=False)


@dataclass(frozen=True, slots=True)
class RemoteRunRequest:
    attempt_id: str
    candidate_id: str
    actor_id: str
    build_number: str
    actor_input: Mapping[str, object]
    max_total_charge_usd: float
    max_items: int


@dataclass(frozen=True, slots=True)
class RemoteRunResult:
    rows: tuple[Mapping[str, object], ...]
    remote_run_id: str
    dataset_id: str | None
    actual_cost_usd: float | None
    cost_final: bool


@dataclass(frozen=True, slots=True)
class PublicationProof:
    workspace_id: str
    route_id: str
    source_id: str
    target_fingerprint: str
    binding_version: int
    candidate_id: str | None
    candidate_generation: int | None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    items: tuple[object, ...]
    execution_mode: str
    health: str
    degraded_reason: str | None
    candidate_id: str | None
    semantic_outcome: str
    publication_proof: PublicationProof
    latest_published_at: str | None = None
    latest_item_id: str | None = None


class AttemptEventSink(Protocol):
    def starting(
        self,
        *,
        secret_ref_id: str | None,
        secret_version: int | None,
        pool_generation: int | None,
    ) -> None: ...

    def registered(self, *, remote_run_id: str, dataset_id: str | None) -> None: ...

    def running(self) -> None: ...

    def start_unknown(self, *, error_code: str) -> None: ...

    def remote_unknown(self, *, error_code: str) -> None: ...


class RemoteActorClient(Protocol):
    async def execute(
        self, request: RemoteRunRequest, events: AttemptEventSink
    ) -> RemoteRunResult: ...


class ActorRouteAdapter(Protocol):
    route_key: RouteKey

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec: ...

    def discovery_spec(self) -> DiscoverySpec: ...

    def build_actor_input(
        self, target: TargetSpec, manifest: ActorManifest, window: FetchWindow
    ) -> Mapping[str, object]: ...

    def validate_output(
        self,
        rows: Sequence[Mapping[str, object]],
        target: TargetSpec,
        manifest: ActorManifest,
        window: FetchWindow,
    ) -> NormalizedBatch: ...

    async def fetch_native_fallback(
        self, target: TargetSpec, window: FetchWindow
    ) -> NativeFallbackResult: ...
