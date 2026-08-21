"""Pure ActorOps v2 identities, states, transitions, and records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


_ROUTE_PART = re.compile(r"^[a-z][a-z0-9_-]*$")


class InvalidTransition(ValueError):
    """Raised when a persisted v2 fact would move backwards or reopen."""


@dataclass(frozen=True, slots=True)
class RouteKey:
    platform: str
    target_type: str
    capability: str

    def __post_init__(self) -> None:
        for field in ("platform", "target_type", "capability"):
            normalized = str(getattr(self, field)).strip().casefold()
            if not _ROUTE_PART.fullmatch(normalized):
                raise ValueError(f"invalid ActorOps RouteKey {field}")
            object.__setattr__(self, field, normalized)

    def __str__(self) -> str:
        return f"{self.platform}/{self.target_type}/{self.capability}"


class RouteHealth(StrEnum):
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    HEALTHY = "healthy"


class RuntimeMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    ACTIVE = "active"


class CandidateLifecycle(StrEnum):
    DISCOVERED = "discovered"
    MAPPING_PENDING = "mapping_pending"
    STATIC_VALID = "static_valid"
    PROBATIONARY = "probationary"
    CERTIFIED = "certified"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"
    SUPERSEDED = "superseded"


class AssignmentRole(StrEnum):
    ACTIVE = "active"
    STANDBY = "standby"
    INACTIVE = "inactive"


class AttemptKind(StrEnum):
    FETCH = "fetch"
    PROBE = "probe"


class AttemptStatus(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    REGISTERED = "registered"
    RUNNING = "running"
    START_UNKNOWN = "start_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DiscoveryStage(StrEnum):
    STORE_SEARCH = "store_search"
    METADATA = "metadata"
    VALIDATION = "validation"
    MAPPING = "mapping"
    RANKING = "ranking"
    PERSIST = "persist"


class DiscoveryStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReplacementStatus(StrEnum):
    PREVIEWED = "previewed"
    AUTHORIZED = "authorized"
    RUNNING = "running"
    READY = "ready"
    APPLIED = "applied"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureClass(StrEnum):
    CONFIGURATION = "configuration"
    TARGET = "target"
    CREDENTIAL = "credential"
    CANDIDATE = "candidate"
    REMOTE_UNKNOWN = "remote_unknown"
    INTERNAL = "internal"


RUNNABLE_LIFECYCLES = frozenset(
    {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}
)
TERMINAL_CANDIDATE_LIFECYCLES = frozenset(
    {
        CandidateLifecycle.REJECTED,
        CandidateLifecycle.QUARANTINED,
        CandidateLifecycle.DISABLED,
        CandidateLifecycle.SUPERSEDED,
    }
)
TERMINAL_ATTEMPT_STATUSES = frozenset(
    {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
)
TERMINAL_DISCOVERY_STATUSES = frozenset(
    {DiscoveryStatus.COMPLETED, DiscoveryStatus.FAILED, DiscoveryStatus.CANCELLED}
)
TERMINAL_REPLACEMENT_STATUSES = frozenset(
    {ReplacementStatus.APPLIED, ReplacementStatus.FAILED, ReplacementStatus.CANCELLED}
)


_CANDIDATE_TRANSITIONS = {
    CandidateLifecycle.DISCOVERED: frozenset(
        {CandidateLifecycle.MAPPING_PENDING, CandidateLifecycle.STATIC_VALID, CandidateLifecycle.REJECTED}
    ),
    CandidateLifecycle.MAPPING_PENDING: frozenset(
        {CandidateLifecycle.STATIC_VALID, CandidateLifecycle.REJECTED}
    ),
    CandidateLifecycle.STATIC_VALID: frozenset(
        {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.REJECTED, CandidateLifecycle.DISABLED}
    ),
    CandidateLifecycle.PROBATIONARY: frozenset(
        {
            CandidateLifecycle.CERTIFIED,
            CandidateLifecycle.QUARANTINED,
            CandidateLifecycle.DISABLED,
            CandidateLifecycle.SUPERSEDED,
        }
    ),
    CandidateLifecycle.CERTIFIED: frozenset(
        {CandidateLifecycle.QUARANTINED, CandidateLifecycle.DISABLED, CandidateLifecycle.SUPERSEDED}
    ),
}


_ATTEMPT_TRANSITIONS = {
    AttemptStatus.CREATED: frozenset({AttemptStatus.STARTING, AttemptStatus.CANCELLED}),
    AttemptStatus.STARTING: frozenset(
        {AttemptStatus.REGISTERED, AttemptStatus.START_UNKNOWN, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
    ),
    AttemptStatus.START_UNKNOWN: frozenset(
        {AttemptStatus.REGISTERED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
    ),
    AttemptStatus.REGISTERED: frozenset(
        {AttemptStatus.RUNNING, AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
    ),
    AttemptStatus.RUNNING: frozenset(
        {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
    ),
}


_DISCOVERY_STATUS_TRANSITIONS = {
    DiscoveryStatus.QUEUED: frozenset({DiscoveryStatus.RUNNING, DiscoveryStatus.CANCELLED}),
    DiscoveryStatus.RUNNING: frozenset(
        {
            DiscoveryStatus.RUNNING,
            DiscoveryStatus.RETRY_WAIT,
            DiscoveryStatus.COMPLETED,
            DiscoveryStatus.FAILED,
            DiscoveryStatus.CANCELLED,
        }
    ),
    DiscoveryStatus.RETRY_WAIT: frozenset(
        {DiscoveryStatus.RUNNING, DiscoveryStatus.FAILED, DiscoveryStatus.CANCELLED}
    ),
}
_STAGE_ORDER = {stage: index for index, stage in enumerate(DiscoveryStage)}


def ensure_candidate_transition(
    current: CandidateLifecycle, target: CandidateLifecycle
) -> None:
    if target not in _CANDIDATE_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(f"candidate transition {current} -> {target} is invalid")


def ensure_attempt_transition(current: AttemptStatus, target: AttemptStatus) -> None:
    if target not in _ATTEMPT_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(f"attempt transition {current} -> {target} is invalid")


def ensure_discovery_transition(
    current_status: DiscoveryStatus,
    current_stage: DiscoveryStage,
    target_status: DiscoveryStatus,
    target_stage: DiscoveryStage,
) -> None:
    if target_status not in _DISCOVERY_STATUS_TRANSITIONS.get(
        current_status, frozenset()
    ):
        raise InvalidTransition(
            f"discovery status {current_status} -> {target_status} is invalid"
        )
    if _STAGE_ORDER[target_stage] < _STAGE_ORDER[current_stage]:
        raise InvalidTransition(
            f"discovery stage {current_stage} -> {target_stage} is invalid"
        )
    if target_status is DiscoveryStatus.COMPLETED and target_stage is not DiscoveryStage.PERSIST:
        raise InvalidTransition("discovery may complete only after persist")


@dataclass(frozen=True, slots=True)
class RouteRecord:
    route_id: str
    workspace_id: str
    route_key: RouteKey
    runtime_mode: RuntimeMode
    per_run_cap_usd: float
    generation: int
    source_v1_generation: int


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    candidate_id: str
    route_id: str
    lifecycle: CandidateLifecycle
    assignment_role: AssignmentRole
    priority: int | None
    generation: int
    build_id: str | None
    manifest_hash: str | None
    actor_id: str = ""
    publisher: str = ""
    build_number: str | None = None
    manifest_json: str | None = None
    input_schema_hash: str | None = None
    output_schema_hash: str | None = None


@dataclass(frozen=True, slots=True)
class BindingRecord:
    binding_id: str
    source_id: str
    route_id: str
    target_fingerprint: str
    binding_version: int
    preferred_candidate_id: str | None
    last_known_good_candidate_id: str | None
    status: str = "pending"
    last_success_at: str | None = None
    watermark_latest_published_at: str | None = None
    watermark_item_id_hash: str | None = None


@dataclass(frozen=True, slots=True)
class MaintenancePolicyRecord:
    policy_id: str
    workspace_id: str
    route_id: str | None
    enabled: bool
    monthly_budget_usd: float | None
    max_probe_usd: float | None
    max_probes_per_utc_day: int | None
    auto_add_standby: bool | None
    auto_replace_non_last: bool | None
    generation: int
    authorized_by_user_id: str | None
    authorized_at: str | None


@dataclass(frozen=True, slots=True)
class MaintenanceBudget:
    spent_usd: float
    reserved_usd: float
    probe_count: int


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    workspace_id: str
    route: RouteRecord
    binding: BindingRecord
    candidates: tuple[CandidateRecord, ...]
    target_fingerprint: str


@dataclass(frozen=True, slots=True)
class StoreMetadataRecord:
    candidate_id: str
    actor_slug: str
    display_name: str
    short_description: str | None
    developer_name: str | None
    maintained_by_apify: bool
    rating: float | None
    review_count: int | None
    bookmark_count: int | None
    total_users: int | None
    monthly_active_users: int | None
    pricing_json: str
    last_modified_at: str | None
    observed_at: str
    generation: int


@dataclass(frozen=True, slots=True)
class ReplacementPlanRecord:
    plan_id: str
    route_id: str
    target_assignment: AssignmentRole
    target_priority: int
    current_candidate_id: str
    current_candidate_generation: int
    proposed_candidate_id: str
    proposed_candidate_generation: int
    pricing_hash: str
    route_generation: int
    binding_set_hash: str
    binding_count: int
    per_probe_cap_usd: float
    total_cap_usd: float
    status: ReplacementStatus
    idempotency_key: str
    error_code: str | None
    generation: int
