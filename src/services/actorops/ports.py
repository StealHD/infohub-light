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
class DiscoveryActorMatch:
    """Safe Store-search facts used to rank Actors before Build reads."""

    actor_id: str
    total_users: int = 0
    rating: float = 0.0
    review_count: int = 0
    bookmark_count: int = 0
    query_hits: int = 1
    display_name: str = ""
    short_description: str = ""


@dataclass(frozen=True, slots=True)
class DiscoveryRevision:
    """Public, exact Actor Build facts needed for Discovery only."""

    actor_id: str
    publisher: str
    build_id: str
    build_number: str
    price_per_run_usd: float | None
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object]
    mapping_feedback: str | None = None
    account_fit_rank: int = 0
    account_fit_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryMapping:
    """One deterministic or AI-assisted, non-runnable Manifest proposal."""

    manifest_json: str | None
    rejection_code: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryAiResult:
    """Bounded AI result; raw prompts and model output are never retained."""

    mappings: Mapping[str, DiscoveryMapping]
    config_id: str | None = None
    input_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    finish_reason: str | None = None
    latency_ms: int | None = None
    response_bytes: int | None = None


class DiscoveryCatalog(Protocol):
    """Read only public Store/Build metadata; it never starts an Actor Run."""

    async def search(
        self, query: str
    ) -> Sequence[str | DiscoveryActorMatch]: ...

    async def get_revision(self, actor_id: str) -> DiscoveryRevision: ...


class DiscoveryAiMapper(Protocol):
    """Optional enhancement for candidates deterministic mapping cannot resolve."""

    async def map(
        self, route_key: RouteKey, revisions: Sequence[DiscoveryRevision]
    ) -> DiscoveryAiResult: ...


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
class PresentationEvidence:
    """Target-bound avatar evidence kept only for the current validation."""

    rows: tuple[Mapping[str, object], ...] = ()
    avatar_url: str | None = None
    content_row_count: int = 0


@dataclass(frozen=True, slots=True)
class NormalizedBatch:
    items: tuple[object, ...]
    semantic_outcome: str
    latest_published_at: str | None = None
    latest_item_id: str | None = None
    source_avatar_url: str | None = None
    presentation_evidence: PresentationEvidence | None = None


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
    max_remote_starts: int = 1
    dataset_item_limit: int | None = None


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
    source_avatar_url: str | None = None


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

    async def read_dataset(
        self, dataset_id: str, *, max_items: int
    ) -> tuple[Mapping[str, object], ...]: ...


@dataclass(frozen=True, slots=True)
class ProbePreflightResult:
    allowed: bool
    error_code: str | None = None


class CandidateProbePreflight(Protocol):
    """Free exact-revision verification before a paid maintenance Probe."""

    async def verify(
        self, candidate: object, *, max_charge_usd: float
    ) -> ProbePreflightResult: ...


@dataclass(frozen=True, slots=True)
class ReconciliationRunLink:
    """One exact durable reservation that may be read during reconciliation."""

    reservation_id: str
    remote_run_id: str | None
    dataset_id: str | None
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ReconciliationRunResolution:
    """Fail-closed result of linking an Attempt to a durable reservation."""

    link: ReconciliationRunLink | None
    ambiguous: bool = False
    reservation_absent: bool = False


@dataclass(frozen=True, slots=True)
class ReconciliationRunObservation:
    """Safe projection read from one already-known remote Run."""

    status: str
    actual_cost_usd: float | None
    cost_final: bool
    dataset_id: str | None = None


class RemoteRunLedger(Protocol):
    """Read and settle existing Run reservations without starting Actors."""

    async def resolve(
        self, attempt: Mapping[str, object]
    ) -> ReconciliationRunResolution: ...

    async def read_known(
        self, link: ReconciliationRunLink
    ) -> ReconciliationRunObservation: ...

    async def prove_no_start(self, link: ReconciliationRunLink) -> bool: ...

    async def settle_proven_no_start(self, link: ReconciliationRunLink) -> None: ...


class ActorRouteAdapter(Protocol):
    route_key: RouteKey

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec: ...

    def discovery_spec(self) -> DiscoverySpec: ...

    def map_discovery_manifest(
        self, revision: DiscoveryRevision
    ) -> DiscoveryMapping: ...

    def map_discovery_input_plan(
        self, revision: DiscoveryRevision
    ) -> tuple[str | None, str | None]: ...

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
