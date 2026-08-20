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


@dataclass(frozen=True, slots=True)
class DiscoverySpec:
    queries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActorManifest:
    actor_id: str
    build_id: str
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


@dataclass(frozen=True, slots=True)
class NativeFallbackResult:
    supported: bool
    items: tuple[object, ...] = ()
    degraded_reason: str | None = None

    @classmethod
    def unsupported(cls) -> NativeFallbackResult:
        return cls(supported=False)


class ActorRouteAdapter(Protocol):
    route_key: RouteKey

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec: ...

    def discovery_spec(self) -> DiscoverySpec: ...

    def build_actor_input(
        self, target: TargetSpec, manifest: ActorManifest, window: FetchWindow
    ) -> Mapping[str, object]: ...

    def validate_output(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec
    ) -> NormalizedBatch: ...

    async def fetch_native_fallback(
        self, target: TargetSpec, window: FetchWindow
    ) -> NativeFallbackResult: ...
