"""Database-backed control plane for generic three-slot Apify Actor routes.

The service deliberately keeps target values, Actor inputs, remote identifiers,
and raw errors out of its public projections.  Runtime callers receive frozen
adapter revisions and must pass the publication fence before using results.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import (
    Any,
    Awaitable,
    Callable,
    Generic,
    Iterator,
    Literal,
    Mapping,
    Sequence,
    TypeVar,
)

from ..apify_actor_identity import source_target_fingerprint
from ..storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from .apify_actor_manifest import (
    ActorManifestError,
    ActorManifestV1,
    actor_manifest_capability_error,
    actor_manifest_hash,
    actor_pricing_capability_error,
    canonical_manifest_json,
    parse_actor_manifest,
)
from .apify_actor_pool_activation import ApifyActorPoolActivationMixin
from .apify_actor_pool_candidates import ApifyActorPoolCandidatesMixin
from .apify_actor_pool_candidate_projection import ApifyActorPoolCandidateProjectionMixin
from .apify_actor_pool_compatibility_projection import ApifyActorPoolCompatibilityProjectionMixin
from .apify_actor_pool_compatibility import ApifyActorPoolCompatibilityMixin
from .apify_actor_pool_cost_settlement import ApifyActorPoolCostSettlementMixin
from .apify_actor_pool_management import ActorPoolManagementMixin
from .apify_actor_pool_readiness import ApifyActorPoolReadinessMixin
from .apify_actor_pool_stage_application import ApifyActorPoolStageApplicationMixin
from .apify_actor_pool_staging import ApifyActorPoolStagingMixin
from .apify_actor_pool_stage_read import load_pool_stage
from .apify_actor_pool_slots import ApifyActorPoolSlotsMixin
from .apify_actor_pool_workflow import project_active_pool_stage_workflow
from .apify_key_pool import APIFY_RUN_TERMINAL_STATUSES


SLOT_NAMES = ("primary", "backup_1", "backup_2")
SUPPORTED_ROUTE_PROFILES = (
    {
        "id": "x/profile/items",
        "route_key": "x/profile",
        "platform": "x",
        "target_type": "profile",
        "capability": "items",
        "mode": "primary",
        "label": "X Profile",
    },
    {
        "id": "youtube/channel/items",
        "route_key": "youtube/channel/items",
        "platform": "youtube",
        "target_type": "channel",
        "capability": "items",
        "mode": "fallback",
        "label": "YouTube Channel",
    },
    {
        "id": "instagram/profile/items",
        "route_key": "instagram/profile/items",
        "platform": "instagram",
        "target_type": "profile",
        "capability": "items",
        "mode": "primary",
        "label": "Instagram Profile",
    },
)
PAID_CANARY_CONFIRMATION = "确认付费试跑"
BATCH_CANARY_CONFIRMATION = "确认付费验证主备"
FIRST_ACTIVATION_CONFIRMATION = "确认首次启用"
ROUTE_POOL_ACTIVATION_CONFIRMATION = "确认启用 Actor 主备"
ROUTE_CANARY_BUDGET_USD = 0.10
ROUTE_CANARY_ATTEMPT_LIMIT = 5
BATCH_CANARY_MAX_CANDIDATES = 3
BATCH_CANARY_MAX_TOTAL_USD = 0.06
POOL_STAGE_MAX_TOTAL_USD = 6.06
POOL_STAGE_MAX_SOURCES = 100
VALIDATION_TIMEOUT_SECONDS_DEFAULT = 300
VALIDATION_TIMEOUT_SECONDS_MIN = 180
VALIDATION_TIMEOUT_SECONDS_MAX = 900
VALIDATION_SAMPLE_ITEMS_ALLOWED = frozenset({1, 3, 5})
VALIDATION_MAX_CHARGE_USD_DEFAULT = 0.02
VALIDATION_MAX_CHARGE_USD_LIMIT = 0.10
SOURCE_CANARY_BUDGET_USD = 0.06
MEMBER_SUPPORT_CHECKS_PER_DAY = 10
MEMBER_PENDING_DISCOVERY_ROUTES = 20
_RUNNABLE_CANDIDATE_STATES = frozenset({"closed", "half_open", "probationary"})
_READY_BINDING_STATUSES = frozenset(
    {"ready_1of1", "ready_2of2", "ready_3of3"}
)
_HARD_OUTPUT_CONTRACT_FAILURES = frozenset(
    {
        "apify_actor_contract_mismatch",
        "apify_actor_metadata_only",
        "apify_actor_placeholder",
    }
)
_BLOCKING_ROUTE_STATUSES = frozenset(
    {
        "blocked",
        "blocked_unknown_start",
        "candidate_shortfall",
        "disabled",
        "discovery_required",
        "quarantined",
    }
)
_PLATFORM_OUTPUT_HOSTS = {
    "x": frozenset({"x.com", "twitter.com"}),
    "youtube": frozenset({"youtube.com", "youtu.be"}),
    "instagram": frozenset({"instagram.com"}),
}
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPABILITY_PART_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_SAFE_ACTOROPS_ERROR_CODE_RE = re.compile(r"^[a-z0-9_]{1,128}$")
_ACTOR_ID_RE = re.compile(
    r"^(?:[A-Za-z0-9]{8,64}|"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,62})$"
)

T = TypeVar("T")


def validation_profile_hash(
    *,
    timeout_seconds: int,
    sample_items: int,
    max_charge_usd: float,
) -> str:
    """Hash the only three browser-adjustable paid validation controls."""

    payload = {
        "timeout_seconds": int(timeout_seconds),
        "sample_items": int(sample_items),
        "max_charge_usd": round(float(max_charge_usd), 6),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _manifest_supports_sample_items(manifest_json: Any) -> bool:
    manifest = _safe_json(manifest_json, {})

    def contains_runtime_max_items(value: Any) -> bool:
        if isinstance(value, dict):
            if value.get("$ref") == "runtime.max_items":
                return True
            return any(contains_runtime_max_items(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_runtime_max_items(item) for item in value)
        return False

    return contains_runtime_max_items(manifest.get("input", {}))


def _validation_options_hash(
    *,
    route_id: str,
    generation: int,
    candidate_id: str,
    revision_id: str,
    build_id: str,
    build_number: str,
    manifest_hash: str,
    supports_sample_items: bool,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "route_id": route_id,
                "generation": int(generation),
                "candidate_id": candidate_id,
                "revision_id": revision_id,
                "build_id": build_id,
                "build_number": build_number,
                "manifest_hash": manifest_hash,
                "supports_sample_items": bool(supports_sample_items),
                "timeout_seconds": [
                    VALIDATION_TIMEOUT_SECONDS_MIN,
                    VALIDATION_TIMEOUT_SECONDS_MAX,
                ],
                "sample_items": [1, 3, 5] if supports_sample_items else [1],
                "max_charge_usd": [
                    VALIDATION_MAX_CHARGE_USD_DEFAULT,
                    VALIDATION_MAX_CHARGE_USD_LIMIT,
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def validation_failure_fingerprint(
    *,
    route_id: str,
    candidate_id: str,
    revision_id: str,
    build_id: str,
    build_number: str,
    manifest_hash: str,
    target_fingerprint: str,
    kind: str,
    profile_hash: str,
) -> str:
    """Identify an unchanged paid attempt without persisting raw input."""

    return hashlib.sha256(
        json.dumps(
            {
                "route_id": route_id,
                "candidate_id": candidate_id,
                "revision_id": revision_id,
                "build_id": build_id,
                "build_number": build_number,
                "manifest_hash": manifest_hash,
                "target_fingerprint": target_fingerprint,
                "kind": kind,
                "profile_hash": profile_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def actor_evidence_fingerprint(
    *,
    route_id: str,
    candidate_id: str,
    actor_id: str,
    build_id: str,
    build_number: str,
    manifest_hash: str,
    pricing: Mapping[str, Any] | None,
    input_schema_hash: str = "",
    output_schema_hash: str = "",
) -> str:
    """Fingerprint only evidence whose change should permit reevaluation."""

    return hashlib.sha256(
        json.dumps(
            {
                "route_id": str(route_id),
                "candidate_id": str(candidate_id),
                "actor_id": str(actor_id),
                "build_id": str(build_id),
                "build_number": str(build_number),
                "manifest_hash": str(manifest_hash),
                "input_schema_hash": str(input_schema_hash),
                "output_schema_hash": str(output_schema_hash),
                "pricing": dict(pricing or {}),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class ActorOpsError(RuntimeError):
    """Stable, safe error for Worker and admin API boundaries."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int = 409,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RouteSlotSnapshot:
    slot_name: Literal["primary", "backup_1", "backup_2"]
    candidate_id: str
    revision_id: str
    actor_id: str
    publisher: str
    build_id: str | None
    build_number: str | None
    manifest_hash: str | None
    lifecycle: str
    candidate_state: str
    manifest: ActorManifestV1 | None
    execution_mode: str = "pinned"
    observed_manifest: bool = False
    compatibility_input_dialect: str = "controlled_default"
    compatibility_input_count_field: str | None = None


@dataclass(frozen=True, slots=True)
class RouteExecutionSnapshot:
    workspace_id: str
    route_id: str
    route_key: str
    route_generation: int
    per_run_cap_usd: float
    slots: tuple[RouteSlotSnapshot, ...]
    source_id: str | None = None
    binding_id: str | None = None
    binding_generation: int | None = None
    binding_revision_set_hash: str | None = None
    target_fingerprint: str | None = None
    key_pool_generation: int | None = None
    attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class RouteScheduleGate:
    allowed: bool
    status: str
    runnable_count: int
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class RouteInvocationResult(Generic[T]):
    value: T | None = None
    semantic_outcome: str = "valid_nonempty"
    cost_usd: float | None = None
    failure_scope: Literal[
        "none",
        "actor",
        "target",
        "key",
        "start_outcome_unknown",
    ] = "none"
    error_code: str | None = None
    latest_published_at: str | None = None
    latest_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class RouteExecutionResult(Generic[T]):
    value: T | None
    semantic_outcome: str
    slot_name: str | None
    attempt_ids: tuple[str, ...]


def revision_set_hash(slots: Mapping[str, str] | tuple[RouteSlotSnapshot, ...]) -> str:
    if isinstance(slots, tuple):
        values = {slot.slot_name: slot.revision_id for slot in slots}
    else:
        values = {str(key): str(value) for key, value in slots.items()}
    payload = {name: values.get(name, "") for name in SLOT_NAMES}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def supported_route_profiles() -> list[dict[str, str]]:
    """Return the fixed first-release Actor Route capability catalog."""

    return [dict(profile) for profile in SUPPORTED_ROUTE_PROFILES]


def _supported_route_profile(
    platform: str,
    target_type: str,
    capability: str,
) -> dict[str, str]:
    for profile in SUPPORTED_ROUTE_PROFILES:
        if (
            profile["platform"],
            profile["target_type"],
            profile["capability"],
        ) == (platform, target_type, capability):
            return dict(profile)
    raise ActorOpsError(
        "apify_actor_route_profile_unsupported",
        "This platform, target type, and capability combination is not supported",
        status_code=422,
    )


class ApifyActorOpsService(
    ActorPoolManagementMixin,
    ApifyActorPoolActivationMixin,
    ApifyActorPoolCompatibilityProjectionMixin,
    ApifyActorPoolCandidateProjectionMixin,
    ApifyActorPoolCandidatesMixin,
    ApifyActorPoolCompatibilityMixin,
    ApifyActorPoolCostSettlementMixin,
    ApifyActorPoolStageApplicationMixin,
    ApifyActorPoolStagingMixin,
    ApifyActorPoolReadinessMixin,
    ApifyActorPoolSlotsMixin,
):
    """Own route profiles, immutable revisions, CAS activation, and fences."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _now_iso(self) -> str:
        value = self._now()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        savepoint = f"actor_ops_{uuid.uuid4().hex}"
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        else:
            connection.execute(f"SAVEPOINT {savepoint}")
        try:
            yield connection
        except Exception:
            if owns_transaction:
                connection.rollback()
            else:
                connection.execute(f"ROLLBACK TO {savepoint}")
                connection.execute(f"RELEASE {savepoint}")
            raise
        else:
            if owns_transaction:
                connection.commit()
            else:
                connection.execute(f"RELEASE {savepoint}")

    def list_routes(self) -> list[dict[str, Any]]:
        rows = self.store.connect().execute(
            """
            SELECT profile.*, COUNT(slot.revision_id) AS configured_slots
            FROM apify_actor_route_profiles AS profile
            LEFT JOIN apify_route_active_slots AS slot
              ON slot.route_id = profile.route_id
             AND slot.workspace_id = profile.workspace_id
            WHERE profile.workspace_id = ?
            GROUP BY profile.route_id
            ORDER BY profile.platform, profile.target_type, profile.capability
            """,
            (self.workspace_id,),
        ).fetchall()
        return [self._safe_route_row(row) for row in rows]

    def catalog_generation(
        self,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        """Return a workspace-wide monotonic CAS token for Route discovery."""

        active = connection or self.store.connect()
        value = active.execute(
            """
            SELECT 1 + COALESCE(SUM(generation), 0)
            FROM apify_actor_route_profiles
            WHERE workspace_id = ?
            """,
            (self.workspace_id,),
        ).fetchone()[0]
        return int(value)

    def get_route(self, route_id: str) -> dict[str, Any]:
        connection = self.store.connect()
        row = self._require_route(connection, route_id)
        slots = connection.execute(
            """
            SELECT slot.slot_name, slot.candidate_id, slot.revision_id,
                   revision.actor_id, revision.publisher, revision.build_number,
                   revision.manifest_hash, revision.lifecycle,
                   revision.execution_mode, revision.observed_manifest,
                   candidate.state AS candidate_state,
                   candidate.display_name,
                   candidate.success_count, candidate.failure_count,
                   revision.canary_passed_at
            FROM apify_route_active_slots AS slot
            LEFT JOIN apify_actor_adapter_revisions AS revision
              ON revision.revision_id = slot.revision_id
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.id = slot.candidate_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
            ORDER BY CASE slot.slot_name
                WHEN 'primary' THEN 1
                WHEN 'backup_1' THEN 2
                ELSE 3 END
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        result = self._safe_route_row(row)
        result["slots"] = [
            {
                "slot_name": str(slot["slot_name"]),
                "candidate_id": slot["candidate_id"],
                "revision_id": slot["revision_id"],
                "actor_id": slot["actor_id"],
                "publisher": slot["publisher"],
                "build_number": slot["build_number"],
                "manifest_hash": slot["manifest_hash"],
                "lifecycle": slot["lifecycle"],
                "execution_mode": slot["execution_mode"],
                "observed_manifest": bool(slot["observed_manifest"] or 0),
                "actor_public_name": slot["display_name"],
                "candidate_state": slot["candidate_state"],
                "success_count": int(slot["success_count"] or 0),
                "failure_count": int(slot["failure_count"] or 0),
                "canary_passed_at": slot["canary_passed_at"],
            }
            for slot in slots
        ]
        gate = self.schedule_gate(route_id)
        result["runtime"] = {
            "status": gate.status,
            "runnable_count": gate.runnable_count,
            "allowed": gate.allowed,
            "error_code": gate.error_code,
        }
        return result

    def recommend_active_pool(self, route_id: str) -> dict[str, Any]:
        """Choose a deterministic full or expedited pool without browser IDs.

        A complete certified/certified/probationary 2+1 pool is always
        preferred. When it is unavailable, the Route's declared runtime and
        publisher minimums apply: X and Instagram still require two, while
        YouTube fallback can run with one exact-Build Canary-proven Actor.
        """

        return self._recommend_active_pool(self.store.connect(), route_id)

    def _recommend_active_pool(
        self,
        connection: sqlite3.Connection,
        route_id: str,
    ) -> dict[str, Any]:
        route = self._require_route(connection, route_id)
        current_rows = connection.execute(
            """
            SELECT slot_name, revision_id
            FROM apify_route_active_slots
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        current = {
            str(row["slot_name"]): str(row["revision_id"] or "")
            for row in current_rows
        }
        rows = connection.execute(
            """
            SELECT revision.revision_id, revision.actor_id,
                   revision.publisher, revision.lifecycle,
                   revision.build_id, revision.build_number,
                   revision.manifest_hash, revision.manifest_json,
                   revision.created_at,
                   candidate.position
            FROM apify_actor_adapter_revisions AS revision
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE revision.workspace_id = ?
              AND candidate.route_key = ?
              AND revision.lifecycle IN (
                  'certified', 'probationary', 'legacy_builtin'
              )
            ORDER BY candidate.position ASC, revision.created_at DESC,
                     revision.revision_id ASC
            """,
            (self.workspace_id, route["route_key"]),
        ).fetchall()

        def eligible(
            row: sqlite3.Row,
            slot_name: str,
            *,
            expedited: bool = False,
        ) -> bool:
            lifecycle = str(row["lifecycle"])
            if lifecycle == "legacy_builtin":
                if expedited:
                    return False
                return current.get(slot_name) == str(row["revision_id"])
            if (
                not row["build_id"]
                or not row["build_number"]
                or not row["manifest_hash"]
            ):
                return False
            try:
                parsed = parse_actor_manifest(str(row["manifest_json"]))
                if (
                    parsed.actor_id != str(row["actor_id"])
                    or parsed.build_number != str(row["build_number"])
                    or actor_manifest_hash(parsed) != str(row["manifest_hash"])
                ):
                    return False
                _assert_manifest_route_hosts(parsed, str(route["platform"]))
            except (ActorManifestError, ActorOpsError):
                return False
            if expedited:
                return lifecycle in {"certified", "probationary"}
            if slot_name in {"primary", "backup_1"}:
                return lifecycle == "certified"
            return lifecycle in {"certified", "probationary"}

        primary_rows = [row for row in rows if eligible(row, "primary")]
        backup_1_rows = [row for row in rows if eligible(row, "backup_1")]
        backup_2_rows = [row for row in rows if eligible(row, "backup_2")]
        row_order = {
            str(row["revision_id"]): index for index, row in enumerate(rows)
        }
        best: (
            tuple[
                tuple[Any, ...],
                tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row],
            ]
            | None
        ) = None
        for primary in primary_rows:
            for backup_1 in backup_1_rows:
                for backup_2 in backup_2_rows:
                    selected = (primary, backup_1, backup_2)
                    if len({str(row["actor_id"]) for row in selected}) != 3:
                        continue
                    if len({str(row["publisher"]).casefold() for row in selected}) < int(
                        route["min_publishers"]
                    ):
                        continue
                    selected_by_slot = dict(zip(SLOT_NAMES, selected, strict=True))
                    current_matches = sum(
                        current.get(slot_name) == str(row["revision_id"])
                        for slot_name, row in selected_by_slot.items()
                    )
                    lifecycle_cost = sum(
                        {
                            "certified": 0,
                            "probationary": 1,
                            "legacy_builtin": 2,
                        }[str(row["lifecycle"])]
                        for row in selected
                    )
                    score: tuple[Any, ...] = (
                        lifecycle_cost,
                        -current_matches,
                        sum(int(row["position"] or 0) for row in selected),
                        *(row_order[str(row["revision_id"])] for row in selected),
                        *(str(row["revision_id"]) for row in selected),
                    )
                    if best is None or score < best[0]:
                        best = (score, selected)

        expedited_rows = [
            row for row in rows if eligible(row, "primary", expedited=True)
        ]
        expedited_best: (
            tuple[tuple[Any, ...], tuple[sqlite3.Row, sqlite3.Row]] | None
        ) = None
        for primary in expedited_rows:
            for backup_1 in expedited_rows:
                selected_pair = (primary, backup_1)
                if len({str(row["actor_id"]) for row in selected_pair}) != 2:
                    continue
                if len(
                    {
                        str(row["publisher"]).casefold()
                        for row in selected_pair
                    }
                ) < int(route["min_publishers"]):
                    continue
                selected_by_slot = {
                    "primary": primary,
                    "backup_1": backup_1,
                }
                current_matches = sum(
                    current.get(slot_name) == str(row["revision_id"])
                    for slot_name, row in selected_by_slot.items()
                ) + int(not current.get("backup_2"))
                lifecycle_cost = sum(
                    {"certified": 0, "probationary": 1}[str(row["lifecycle"])]
                    for row in selected_pair
                )
                score = (
                    lifecycle_cost,
                    -current_matches,
                    sum(int(row["position"] or 0) for row in selected_pair),
                    *(row_order[str(row["revision_id"])] for row in selected_pair),
                    *(str(row["revision_id"]) for row in selected_pair),
                )
                if expedited_best is None or score < expedited_best[0]:
                    expedited_best = (score, selected_pair)
        if (
            best is not None
            and expedited_best is not None
            and any(str(row["lifecycle"]) == "legacy_builtin" for row in best[1])
        ):
            best = None
        single_best = (
            expedited_rows[0]
            if int(route["min_runtime_healthy"]) == 1 and expedited_rows
            else None
        )

        primary_actor_count = len(
            {str(row["actor_id"]) for row in primary_rows}
        )
        backup_2_actor_count = len(
            {str(row["actor_id"]) for row in backup_2_rows}
        )
        eligible_publishers = len(
            {
                str(row["publisher"]).casefold()
                for row in (*primary_rows, *backup_2_rows)
            }
        )
        runnable_actor_count = len(
            {str(row["actor_id"]) for row in expedited_rows}
        )
        if best is None and expedited_best is None and single_best is None:
            problems: list[str] = []
            if runnable_actor_count < int(route["min_runtime_healthy"]):
                problems.append("canary_successful_candidates_incomplete")
            if eligible_publishers < int(route["min_publishers"]):
                problems.append("publisher_diversity_incomplete")
            if not problems:
                problems.append("compatible_pool_unavailable")
            return {
                "ready": False,
                "already_active": False,
                "slots": {},
                "problems": problems,
                "certified_actor_count": primary_actor_count,
                "backup_2_actor_count": backup_2_actor_count,
                "runnable_actor_count": runnable_actor_count,
                "publisher_count": eligible_publishers,
                "activation_mode": None,
            }

        if best is not None:
            activation_mode = "standard_2plus1"
            selected: dict[str, sqlite3.Row | None] = dict(
                zip(SLOT_NAMES, best[1], strict=True)
            )
        elif expedited_best is not None:
            activation_mode = "expedited_2of3"
            selected = {
                "primary": expedited_best[1][0],
                "backup_1": expedited_best[1][1],
                "backup_2": None,
            }
        else:
            assert single_best is not None
            activation_mode = "standard_1of1"
            selected = {
                "primary": single_best,
                "backup_1": None,
                "backup_2": None,
            }
        slots = {
            slot_name: (
                str(row["revision_id"]) if row is not None else None
            )
            for slot_name, row in selected.items()
        }
        already_active = all(
            str(current.get(slot_name) or "") == str(revision_id or "")
            for slot_name, revision_id in slots.items()
        )
        return {
            "ready": True,
            "already_active": already_active,
            "slots": slots,
            "problems": [],
            "certified_actor_count": primary_actor_count,
            "backup_2_actor_count": backup_2_actor_count,
            "runnable_actor_count": runnable_actor_count,
            "publisher_count": len(
                {
                    str(row["publisher"]).casefold()
                    for row in selected.values()
                    if row is not None
                }
            ),
            "activation_mode": activation_mode,
        }

    def activate_recommended_pool(
        self,
        route_id: str,
        *,
        expected_generation: int,
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != ROUTE_POOL_ACTIVATION_CONFIRMATION:
            raise ActorOpsError(
                "apify_actor_route_activation_confirmation_required",
                "Route activation requires the exact confirmation phrase",
                status_code=422,
            )
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            recommendation = self._recommend_active_pool(connection, route_id)
            if not recommendation["ready"]:
                raise ActorOpsError(
                    "apify_actor_active_pool_not_ready",
                    "No safe two-Actor pool is ready to activate",
                    status_code=412,
                )
            if recommendation["already_active"]:
                raise ActorOpsError(
                    "apify_actor_active_pool_already_active",
                    "The recommended Actor pool is already active",
                )
            return self.replace_active_pool(
                route_id,
                slots=recommendation["slots"],
                expected_generation=expected_generation,
            )

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT revision_id, candidate_id, actor_id, publisher, build_id,
                   build_number, manifest_hash, input_schema_hash,
                   output_schema_hash, pricing_json, permission_level,
                   security_evidence_json, execution_mode, observed_manifest,
                   lifecycle, ai_provider, ai_model,
                   prompt_version, discovery_run_id, canary_passed_at,
                   created_at, superseded_at, superseded_from_lifecycle
            FROM apify_actor_adapter_revisions
            WHERE workspace_id = ? AND revision_id = ?
            """,
            (self.workspace_id, revision_id),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_revision_not_found",
                "Actor adapter revision was not found",
                status_code=404,
            )
        result = dict(row)
        for name in ("pricing_json", "security_evidence_json"):
            result[name.removesuffix("_json")] = _safe_json(result.pop(name), {})
        return result

    def promote_compatibility_observation(
        self,
        validation_id: str,
        *,
        observed_fields: Sequence[str],
        observed_build_id: str | None = None,
        observed_build_number: str | None = None,
    ) -> str:
        """Persist a value-free observed contract after a real paid Canary."""

        with self._write() as connection:
            row = connection.execute(
                """
                SELECT validation.status, validation.semantic_outcome,
                       validation.cost_final, validation.revision_id,
                       attempt.build_id AS observed_attempt_build_id,
                       attempt.build_number AS observed_attempt_build_number,
                       revision.*, candidate.state AS candidate_state
                FROM apify_actor_validations AS validation
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = validation.workspace_id
                 AND revision.revision_id = validation.revision_id
                LEFT JOIN apify_actor_attempts AS attempt
                  ON attempt.workspace_id = validation.workspace_id
                 AND attempt.id = validation.attempt_id
                JOIN apify_actor_candidates AS candidate
                  ON candidate.workspace_id = revision.workspace_id
                 AND candidate.id = revision.candidate_id
                WHERE validation.workspace_id = ?
                  AND validation.validation_id = ?
                """,
                (self.workspace_id, str(validation_id)),
            ).fetchone()
            if row is None:
                raise ActorOpsError(
                    "apify_actor_validation_not_found",
                    "Actor validation was not found",
                    status_code=404,
                )
            if (
                str(row["status"]) != "succeeded"
                or str(row["semantic_outcome"]) != "valid_nonempty"
                or not bool(row["cost_final"])
            ):
                raise ActorOpsError(
                    "apify_actor_cost_pending",
                    "Compatibility evidence cannot be promoted before cost settlement",
                    status_code=409,
                )
            if (
                str(row["execution_mode"] or "") == "current"
                and bool(row["observed_manifest"])
            ):
                return str(row["revision_id"])
            if (
                str(row["lifecycle"]) != "legacy_builtin"
                and row["build_id"]
                and row["build_number"]
                and row["manifest_hash"]
            ):
                now = self._now_iso()
                connection.execute(
                    """
                    UPDATE apify_actor_adapter_revisions
                    SET lifecycle = CASE WHEN lifecycle = 'static_valid'
                            THEN 'probationary' ELSE lifecycle END,
                        canary_passed_at = COALESCE(canary_passed_at, ?)
                    WHERE workspace_id = ? AND revision_id = ?
                      AND lifecycle IN (
                          'static_valid', 'probationary', 'certified'
                      )
                    """,
                    (now, self.workspace_id, str(row["revision_id"])),
                )
                return str(row["revision_id"])
            safe_fields = sorted(
                {
                    str(field)
                    for field in observed_fields
                    if str(field)
                    in {"identity", "url", "published_at", "content"}
                }
            )
            if safe_fields != ["content", "identity", "published_at", "url"]:
                raise ActorOpsError(
                    "apify_actor_observed_manifest_incomplete",
                    "Compatibility output did not prove every required field",
                    status_code=412,
                )
            manifest_payload = {
                "schema_version": 1,
                "kind": "observed_x_compatibility",
                "required_fields": safe_fields,
                "input_contract": "controlled_x_profile_v1",
                "publication_fence": "x_profile_v1",
            }
            manifest_json = json.dumps(
                manifest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            manifest_hash = hashlib.sha256(manifest_json.encode()).hexdigest()
            effective_build_id = (
                observed_build_id
                or row["observed_attempt_build_id"]
                or row["build_id"]
            )
            effective_build_number = (
                observed_build_number
                or row["observed_attempt_build_number"]
                or row["build_number"]
            )
            pinned_build = bool(effective_build_id and effective_build_number)
            build_id = str(effective_build_id) if pinned_build else None
            build_number = str(effective_build_number) if pinned_build else None
            execution_mode = "pinned" if pinned_build else "current"
            revision_id = "apify-revision-" + hashlib.sha256(
                "\x1f".join(
                    (
                        self.workspace_id,
                        str(row["candidate_id"]),
                        "compatibility",
                        str(build_id or "current"),
                        str(build_number or "current"),
                        manifest_hash,
                    )
                ).encode()
            ).hexdigest()[:32]
            now = self._now_iso()
            prior_evidence = _safe_json(row["security_evidence_json"], {})
            evidence = {
                "compatibility_canary": True,
                "controlled_input": True,
                "nonempty_reference": True,
                "observed_manifest": True,
                "follows_current_build": not pinned_build,
                "deprecated": bool(prior_evidence.get("deprecated")),
                "permission_unverified": bool(
                    prior_evidence.get("permission_unverified")
                ),
                "input_dialect": str(
                    prior_evidence.get("input_dialect")
                    or "controlled_default"
                ),
                "input_count_field": prior_evidence.get(
                    "input_count_field"
                ),
            }
            connection.execute(
                """
                INSERT OR IGNORE INTO apify_actor_adapter_revisions (
                    revision_id, workspace_id, candidate_id, actor_id,
                    publisher, build_id, build_number, manifest_json,
                    manifest_hash, input_schema_hash, output_schema_hash,
                    execution_mode, observed_manifest, pricing_json,
                    permission_level, security_evidence_json, lifecycle,
                    ai_provider, ai_model, prompt_version, discovery_run_id,
                    canary_passed_at, created_at, superseded_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,
                    ?, 1, ?, ?, ?, 'legacy_builtin',
                    NULL, NULL, 'compatibility_observed_v1', ?, ?, ?, NULL
                )
                """,
                (
                    revision_id,
                    self.workspace_id,
                    str(row["candidate_id"]),
                    str(row["actor_id"]),
                    str(row["publisher"]),
                    build_id,
                    build_number,
                    manifest_json,
                    manifest_hash,
                    execution_mode,
                    row["pricing_json"],
                    str(row["permission_level"]),
                    json.dumps(
                        evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    row["discovery_run_id"],
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE apify_actor_validations
                SET revision_id = ?
                WHERE workspace_id = ? AND validation_id = ?
                """,
                (revision_id, self.workspace_id, str(validation_id)),
            )
            connection.execute(
                """
                UPDATE apify_actor_canary_batch_items
                SET revision_id = ?, updated_at = ?
                WHERE workspace_id = ? AND validation_id = ?
                """,
                (revision_id, now, self.workspace_id, str(validation_id)),
            )
            connection.execute(
                """
                UPDATE apify_actor_pool_stage_candidate_settings
                SET revision_id = ?
                WHERE workspace_id = ? AND revision_id = ?
                  AND candidate_id = ?
                """,
                (
                    revision_id,
                    self.workspace_id,
                    str(row["revision_id"]),
                    str(row["candidate_id"]),
                ),
            )
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = 'closed', recovery_successes = 0,
                    last_error_code = NULL, last_success_at = ?,
                    success_count = success_count + 1, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (now, now, self.workspace_id, str(row["candidate_id"])),
            )
            return revision_id

    def revision_canary_block_reason(
        self,
        route_id: str,
        revision_id: str,
    ) -> str | None:
        return self._revision_canary_block_reason(
            self.store.connect(),
            route_id,
            revision_id,
        )

    def _revision_canary_block_reason(
        self,
        connection: sqlite3.Connection,
        route_id: str,
        revision_id: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT revision.manifest_json, revision.pricing_json,
                   revision.output_schema_hash,
                   revision.security_evidence_json,
                   profile.platform, profile.target_type, profile.capability
            FROM apify_actor_adapter_revisions AS revision
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = candidate.workspace_id
             AND profile.route_key = candidate.route_key
            WHERE revision.workspace_id = ? AND revision.revision_id = ?
              AND profile.route_id = ?
            """,
            (self.workspace_id, revision_id, route_id),
        ).fetchone()
        if row is None:
            return "apify_actor_revision_not_canary_ready"
        incompatible = connection.execute(
            """
            SELECT 1
            FROM apify_actor_validations
            WHERE workspace_id = ? AND route_id = ?
              AND revision_id = ? AND kind = 'route_reference'
              AND status = 'failed'
              AND semantic_outcome IN (?, ?, ?)
            LIMIT 1
            """,
            (
                self.workspace_id,
                route_id,
                revision_id,
                *sorted(_HARD_OUTPUT_CONTRACT_FAILURES),
            ),
        ).fetchone()
        if incompatible is not None:
            return "apify_actor_revision_output_incompatible"
        manifest = _safe_json(row["manifest_json"], {})
        pricing = _safe_json(row["pricing_json"], {})
        try:
            manifest_error = actor_manifest_capability_error(
                manifest,
                platform=str(row["platform"]),
                target_type=str(row["target_type"]),
                capability=str(row["capability"]),
            )
        except ActorManifestError as exc:
            return str(exc.code)
        if manifest_error is not None:
            return manifest_error
        pricing_error = actor_pricing_capability_error(
            pricing,
            platform=str(row["platform"]),
            target_type=str(row["target_type"]),
            capability=str(row["capability"]),
        )
        if pricing_error is None:
            return None
        evidence = _safe_json(row["security_evidence_json"], {})
        schema_proof = evidence.get("output_schema_proves_items") is True
        # Old immutable revisions need exact schema, input, and item proof.
        legacy_schema_proof = (
            bool(row["output_schema_hash"])
            and evidence.get("exact_successful_build") is True
            and evidence.get("input_validation") is True
            and _manifest_has_explicit_item_identity(manifest)
        )
        if schema_proof or legacy_schema_proof:
            return None
        return pricing_error

    def stop_unavailable_revision(
        self,
        revision_id: str,
        *,
        reason: str = "apify_actor_revision_unavailable",
    ) -> dict[str, Any]:
        """Stop one immutable Build after a deterministic free preflight."""

        safe_reason = _safe_label(reason, 128)
        now = self._now_iso()
        with self._write() as connection:
            row = connection.execute(
                """
                SELECT candidate_id, lifecycle
                FROM apify_actor_adapter_revisions
                WHERE workspace_id = ? AND revision_id = ?
                """,
                (self.workspace_id, revision_id),
            ).fetchone()
            if row is None:
                raise ActorOpsError(
                    "apify_actor_revision_not_found",
                    "Actor adapter revision was not found",
                    status_code=404,
                )
            lifecycle = str(row["lifecycle"])
            next_lifecycle = {
                "static_valid": "rejected",
                "probationary": "quarantined",
                "certified": "quarantined",
            }.get(lifecycle)
            if next_lifecycle is not None:
                connection.execute(
                    """
                    UPDATE apify_actor_adapter_revisions
                    SET lifecycle = ?
                    WHERE workspace_id = ? AND revision_id = ?
                    """,
                    (next_lifecycle, self.workspace_id, revision_id),
                )
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = 'disabled', last_error_code = ?, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (
                    safe_reason,
                    now,
                    self.workspace_id,
                    str(row["candidate_id"]),
                ),
            )
        return self.get_revision(revision_id)

    def proven_no_remote_start(self, attempt_id: str) -> bool:
        row = self.store.connect().execute(
            """
            SELECT status, remote_run_id, dataset_id,
                   charge_reserved_usd, charge_actual_usd, charge_final
            FROM apify_actor_runs
            WHERE workspace_id = ? AND logical_run_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (self.workspace_id, attempt_id),
        ).fetchone()
        return bool(
            row is not None
            and str(row["status"]) == "start_rejected"
            and row["remote_run_id"] is None
            and row["dataset_id"] is None
            and float(row["charge_reserved_usd"] or 0) == 0
            and float(row["charge_actual_usd"] or 0) == 0
            and int(row["charge_final"] or 0) == 1
        )

    def _safe_route_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "route_id": str(row["route_id"]),
            "route_key": str(row["route_key"]),
            "platform": str(row["platform"]),
            "target_type": str(row["target_type"]),
            "capability": str(row["capability"]),
            "mode": str(row["mode"]),
            "required_slots": int(row["required_slots"]),
            "min_runtime_healthy": int(row["min_runtime_healthy"]),
            "min_publishers": int(row["min_publishers"]),
            "admission_mode": str(row["admission_mode"]),
            "compatibility_risk_code": row["compatibility_risk_code"],
            "per_run_cap_usd": float(row["per_run_cap_usd"]),
            "status": str(row["status"]),
            "freshness_enabled": bool(row["freshness_enabled"]),
            "freshness_interval_hours": int(row["freshness_interval_hours"]),
            "freshness_status": str(row["freshness_status"]),
            "freshness_last_checked_at": row["freshness_last_checked_at"],
            "freshness_next_check_at": row["freshness_next_check_at"],
            "freshness_last_cost_usd": row["freshness_last_cost_usd"],
            "metadata_check_interval_seconds": int(
                row["metadata_check_interval_seconds"]
            ),
            "policy_version": str(row["policy_version"]),
            "generation": int(row["generation"]),
            "configured_slots": (
                int(row["configured_slots"])
                if "configured_slots" in row.keys()
                else None
            ),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _require_route(
        self,
        connection: sqlite3.Connection,
        route_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM apify_actor_route_profiles
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, str(route_id)),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_route_not_found",
                "Actor route was not found",
                status_code=404,
            )
        return row

    def _require_no_active_freshness_check(
        self,
        connection: sqlite3.Connection,
        route_id: str,
    ) -> None:
        active = connection.execute(
            """
            SELECT 1 FROM apify_actor_freshness_checks
            WHERE workspace_id = ? AND route_id = ?
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (self.workspace_id, str(route_id)),
        ).fetchone()
        if active is not None:
            raise ActorOpsError(
                "apify_actor_freshness_active",
                "Active Actor pool cannot change during a freshness check",
                status_code=409,
            )

    def ensure_candidate(
        self,
        route_id: str,
        *,
        actor_id: str,
        adapter_key: str = "manifest_v1",
        display_name: str | None = None,
    ) -> str:
        """Return a route-local candidate, creating a disabled proposal if absent."""

        normalized_actor = _normalize_actor_id(actor_id)
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            now = self._now_iso()
            connection.execute(
                """
                INSERT OR IGNORE INTO apify_actor_routes (
                    workspace_id, route_key, generation, status,
                    active_candidate_id, last_switch_reason, last_switch_at,
                    budget_blocked_until, blocked_reason, created_at, updated_at
                ) VALUES (?, ?, ?, 'blocked', NULL, 'actor_ops_candidate',
                          ?, NULL, 'candidate_shortfall', ?, ?)
                """,
                (
                    self.workspace_id,
                    route["route_key"],
                    int(route["generation"]),
                    now,
                    now,
                    now,
                ),
            )
            existing = connection.execute(
                """
                SELECT id FROM apify_actor_candidates
                WHERE workspace_id = ? AND route_key = ? AND actor_id = ?
                """,
                (self.workspace_id, route["route_key"], normalized_actor),
            ).fetchone()
            if existing is not None:
                return str(existing["id"])
            position = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(position), -1) + 1
                    FROM apify_actor_candidates
                    WHERE workspace_id = ? AND route_key = ?
                    """,
                    (self.workspace_id, route["route_key"]),
                ).fetchone()[0]
            )
            candidate_id = f"apify-candidate-{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO apify_actor_candidates (
                    id, workspace_id, route_key, actor_id, adapter_key,
                    display_name, position, state, failure_level,
                    recovery_successes, success_count, failure_count,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'disabled', 0, 0, 0, 0, ?, ?)
                """,
                (
                    candidate_id,
                    self.workspace_id,
                    route["route_key"],
                    normalized_actor,
                    _safe_label(adapter_key, 128),
                    _safe_label(display_name or normalized_actor, 256),
                    position,
                    now,
                    now,
                ),
            )
            return candidate_id

    def create_adapter_revision(
        self,
        *,
        candidate_id: str,
        actor_id: str,
        publisher: str,
        build_id: str,
        build_number: str,
        manifest: ActorManifestV1 | Mapping[str, Any] | str,
        input_schema_hash: str | None = None,
        output_schema_hash: str | None = None,
        pricing: Mapping[str, Any] | None = None,
        permission_level: str = "limited",
        security_evidence: Mapping[str, Any] | None = None,
        lifecycle: Literal["proposed", "static_valid"] = "static_valid",
        ai_provider: str | None = None,
        ai_model: str | None = None,
        prompt_version: str | None = None,
        discovery_run_id: str | None = None,
    ) -> str:
        parsed = parse_actor_manifest(manifest)
        normalized_actor = _normalize_actor_id(actor_id)
        if parsed.actor_id != normalized_actor or parsed.build_number != build_number:
            raise ActorOpsError(
                "apify_actor_revision_identity_mismatch",
                "Manifest Actor or exact Build does not match fetched metadata",
                status_code=422,
            )
        canonical = canonical_manifest_json(parsed)
        manifest_digest = actor_manifest_hash(parsed)
        schema_digests = (input_schema_hash, output_schema_hash)
        if any(value is not None and not _HEX_64_RE.fullmatch(value) for value in schema_digests):
            raise ActorOpsError(
                "apify_actor_schema_hash_invalid",
                "Actor schema hash is invalid",
                status_code=422,
            )
        safe_pricing = _bounded_safe_json(pricing or {}, max_bytes=8 * 1024)
        safe_evidence = _bounded_safe_json(
            security_evidence or {},
            max_bytes=16 * 1024,
        )
        normalized_publisher = _safe_label(publisher, 128)
        if not normalized_publisher:
            raise ActorOpsError(
                "apify_actor_publisher_invalid",
                "Actor publisher is required",
                status_code=422,
            )
        revision_id = f"apify-revision-{uuid.uuid4().hex}"
        now = self._now_iso()
        with self._write() as connection:
            candidate = connection.execute(
                """
                SELECT candidate.actor_id, profile.platform
                FROM apify_actor_candidates AS candidate
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = candidate.workspace_id
                 AND profile.route_key = candidate.route_key
                WHERE candidate.workspace_id = ? AND candidate.id = ?
                """,
                (self.workspace_id, candidate_id),
            ).fetchone()
            if candidate is None:
                raise ActorOpsError(
                    "apify_actor_candidate_not_found",
                    "Actor candidate was not found",
                    status_code=404,
                )
            if _normalize_actor_id(str(candidate["actor_id"])) != normalized_actor:
                raise ActorOpsError(
                    "apify_actor_revision_identity_mismatch",
                    "Actor candidate does not match the revision",
                    status_code=422,
                )
            _assert_manifest_route_hosts(parsed, str(candidate["platform"]))
            if lifecycle == "static_valid" and discovery_run_id is not None:
                # A legacy seed can carry the historical ``canary_required``
                # marker on its Candidate.  A newly fetched exact Build and
                # validated Manifest supersede that placeholder evidence while
                # leaving the active legacy Revision untouched until apply.
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET last_error_code = NULL, updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                      AND last_error_code = 'canary_required'
                    """,
                    (now, self.workspace_id, candidate_id),
                )
            if discovery_run_id is not None:
                discovery = connection.execute(
                    """
                    SELECT 1
                    FROM apify_actor_discovery_runs AS run
                    JOIN apify_actor_route_profiles AS profile
                      ON profile.workspace_id = run.workspace_id
                     AND profile.route_id = run.route_id
                    JOIN apify_actor_candidates AS selected
                      ON selected.workspace_id = profile.workspace_id
                     AND selected.route_key = profile.route_key
                    WHERE run.workspace_id = ? AND run.run_id = ?
                      AND selected.id = ?
                    """,
                    (self.workspace_id, discovery_run_id, candidate_id),
                ).fetchone()
                if discovery is None:
                    raise ActorOpsError(
                        "apify_actor_discovery_revision_mismatch",
                        "Actor revision does not belong to this discovery run",
                        status_code=422,
                    )
            try:
                connection.execute(
                    """
                    INSERT INTO apify_actor_adapter_revisions (
                        revision_id, workspace_id, candidate_id, actor_id,
                        publisher, build_id, build_number, manifest_json,
                        manifest_hash, input_schema_hash, output_schema_hash,
                        pricing_json, permission_level, security_evidence_json,
                        lifecycle, ai_provider, ai_model, prompt_version,
                        discovery_run_id, canary_passed_at, created_at,
                        superseded_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, NULL, ?, NULL
                    )
                    """,
                    (
                        revision_id,
                        self.workspace_id,
                        candidate_id,
                        normalized_actor,
                        normalized_publisher,
                        _safe_label(build_id, 256),
                        parsed.build_number,
                        canonical,
                        manifest_digest,
                        input_schema_hash,
                        output_schema_hash,
                        safe_pricing,
                        _safe_label(permission_level, 64),
                        safe_evidence,
                        lifecycle,
                        _optional_label(ai_provider, 128),
                        _optional_label(ai_model, 256),
                        _optional_label(prompt_version, 128),
                        discovery_run_id,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                existing = connection.execute(
                    """
                    SELECT revision_id
                    FROM apify_actor_adapter_revisions
                    WHERE workspace_id = ? AND candidate_id = ?
                      AND build_id = ? AND build_number = ? AND manifest_hash = ?
                    """,
                    (
                        self.workspace_id,
                        candidate_id,
                        build_id,
                        parsed.build_number,
                        manifest_digest,
                    ),
                ).fetchone()
                if existing is not None:
                    existing_revision_id = str(existing["revision_id"])
                    if discovery_run_id is not None:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO
                                apify_actor_discovery_run_revisions (
                                    workspace_id, run_id, revision_id,
                                    created_at
                                )
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                self.workspace_id,
                                discovery_run_id,
                                existing_revision_id,
                                now,
                            ),
                        )
                    return existing_revision_id
                raise ActorOpsError(
                    "apify_actor_revision_conflict",
                    "Actor adapter revision conflicts with existing state",
                ) from error
            if discovery_run_id is not None:
                connection.execute(
                    """
                    INSERT INTO apify_actor_discovery_run_revisions (
                        workspace_id, run_id, revision_id, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        self.workspace_id,
                        discovery_run_id,
                        revision_id,
                        now,
                    ),
                )
        return revision_id

    def transition_revision(
        self,
        revision_id: str,
        *,
        expected_lifecycle: str,
        lifecycle: str,
    ) -> dict[str, Any]:
        allowed = {
            "proposed": {"static_valid", "rejected", "quarantined"},
            "static_valid": {"probationary", "rejected", "quarantined"},
            "probationary": {"certified", "quarantined", "superseded"},
            "certified": {"quarantined", "superseded"},
            "quarantined": {"static_valid", "rejected", "superseded"},
        }
        if lifecycle not in allowed.get(expected_lifecycle, set()):
            raise ActorOpsError(
                "apify_actor_revision_transition_invalid",
                "Actor adapter lifecycle transition is invalid",
                status_code=422,
            )
        now = self._now_iso()
        with self._write() as connection:
            if lifecycle == "probationary":
                evidence = connection.execute(
                    """
                    SELECT
                        SUM(CASE
                            WHEN status = 'succeeded'
                             AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                            THEN 1 ELSE 0 END
                        ) AS successes,
                        COUNT(DISTINCT CASE
                            WHEN status = 'succeeded'
                             AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                            THEN target_fingerprint END
                        ) AS distinct_targets
                    FROM apify_actor_validations
                    WHERE workspace_id = ? AND revision_id = ?
                      AND kind = 'route_reference'
                      AND status IN ('succeeded', 'failed', 'cancelled')
                    """,
                    (self.workspace_id, revision_id),
                ).fetchone()
                successes = int(evidence["successes"] or 0)
                distinct_targets = int(evidence["distinct_targets"] or 0)
                if successes < 1 or distinct_targets < 1:
                    raise ActorOpsError(
                        "apify_actor_revision_canary_incomplete",
                        "Actor adapter requires one successful reference Canary",
                        status_code=412,
                    )
            elif lifecycle == "certified":
                evidence = self._certification_evidence(
                    connection,
                    revision_id,
                )
                if (
                    int(evidence["successes"]) < 2
                    or int(evidence["distinct_identities"]) < 2
                    or (
                        not bool(evidence["active_as_backup_2"])
                        and int(evidence["distinct_reference_targets"]) < 2
                    )
                ):
                    raise ActorOpsError(
                        "apify_actor_revision_canary_incomplete",
                        "Actor adapter needs two successful independent identities",
                        status_code=412,
                    )
                if float(evidence["success_rate"]) < 0.95:
                    raise ActorOpsError(
                        "apify_actor_revision_success_rate_low",
                        "Actor adapter success rate is below certification policy",
                        status_code=412,
                    )
                first_success = evidence["first_success"]
                if (
                    first_success is None
                    or first_success
                    > _as_utc(self._now()) - timedelta(hours=48)
                ):
                    raise ActorOpsError(
                        "apify_actor_revision_observation_incomplete",
                        "Actor adapter has not completed its certification observation",
                        status_code=412,
                    )
            cursor = connection.execute(
                """
                UPDATE apify_actor_adapter_revisions
                SET lifecycle = ?,
                    canary_passed_at = CASE
                        WHEN ? IN ('probationary', 'certified')
                        THEN COALESCE(canary_passed_at, ?)
                        ELSE canary_passed_at END,
                    superseded_at = CASE
                        WHEN ? = 'superseded' THEN ?
                        ELSE superseded_at END,
                    superseded_from_lifecycle = CASE
                        WHEN ? = 'superseded' THEN ?
                        ELSE superseded_from_lifecycle END
                WHERE workspace_id = ? AND revision_id = ? AND lifecycle = ?
                """,
                (
                    lifecycle,
                    lifecycle,
                    now,
                    lifecycle,
                    now,
                    lifecycle,
                    expected_lifecycle,
                    self.workspace_id,
                    revision_id,
                    expected_lifecycle,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_revision_generation_conflict",
                    "Actor adapter revision changed; reload before retrying",
                )
            if lifecycle in {"quarantined", "superseded", "rejected"}:
                active = connection.execute(
                    """
                    SELECT slot.route_id, slot.slot_name, revision.candidate_id,
                           profile.route_key, profile.min_runtime_healthy
                    FROM apify_route_active_slots AS slot
                    JOIN apify_actor_route_profiles AS profile
                      ON profile.workspace_id = slot.workspace_id
                     AND profile.route_id = slot.route_id
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = slot.workspace_id
                     AND revision.revision_id = slot.revision_id
                    WHERE slot.workspace_id = ? AND slot.revision_id = ?
                    """,
                    (self.workspace_id, revision_id),
                ).fetchone()
                if active is not None:
                    connection.execute(
                        """
                        UPDATE apify_actor_candidates
                        SET state = ?, updated_at = ?
                        WHERE workspace_id = ? AND id = ?
                        """,
                        (
                            (
                                "open"
                                if lifecycle == "quarantined"
                                else "disabled"
                            ),
                            now,
                            self.workspace_id,
                            active["candidate_id"],
                        ),
                    )
                    runnable = self._count_runnable_slots(
                        connection,
                        str(active["route_id"]),
                    )
                    minimum = int(active["min_runtime_healthy"])
                    connection.execute(
                        """
                        UPDATE apify_actor_route_profiles
                        SET status = ?, generation = generation + 1,
                            updated_at = ?
                        WHERE workspace_id = ? AND route_id = ?
                        """,
                        (
                            (
                                "ready"
                                if runnable >= minimum
                                else "candidate_shortfall"
                            ),
                            now,
                            self.workspace_id,
                            active["route_id"],
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE apify_actor_routes
                        SET status = ?, generation = generation + 1,
                            blocked_reason = ?, updated_at = ?
                        WHERE workspace_id = ? AND route_key = ?
                        """,
                        (
                            (
                                "ready"
                                if runnable == 3
                                else "degraded"
                                if runnable >= minimum
                                else "exhausted"
                            ),
                            None if runnable >= minimum else "candidate_shortfall",
                            now,
                            self.workspace_id,
                            active["route_key"],
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE apify_source_route_bindings
                        SET validation_status = 'revalidation_pending',
                            generation = generation + 1, updated_at = ?
                        WHERE workspace_id = ? AND route_id = ?
                          AND validation_status IN ('ready_2of2', 'ready_3of3')
                        """,
                        (
                            now,
                            self.workspace_id,
                            active["route_id"],
                        ),
                    )
            if lifecycle == "certified":
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET state = CASE
                            WHEN state = 'probationary' THEN 'closed'
                            ELSE state END,
                        updated_at = ?
                    WHERE workspace_id = ?
                      AND id = (
                          SELECT candidate_id
                          FROM apify_actor_adapter_revisions
                          WHERE workspace_id = ? AND revision_id = ?
                      )
                      AND EXISTS (
                          SELECT 1
                          FROM apify_route_active_slots
                          WHERE workspace_id = ?
                            AND revision_id = ?
                      )
                    """,
                    (
                        now,
                        self.workspace_id,
                        self.workspace_id,
                        revision_id,
                        self.workspace_id,
                        revision_id,
                    ),
                )
        return self.get_revision(revision_id)

    def _certification_evidence(
        self,
        connection: sqlite3.Connection,
        revision_id: str,
    ) -> dict[str, Any]:
        """Evaluate Actor-quality evidence without double-counting Canaries."""

        references = connection.execute(
            """
            SELECT validation.status, validation.semantic_outcome,
                   validation.target_fingerprint, validation.completed_at,
                   validation.attempt_id, attempt.status AS attempt_status,
                   attempt.semantic_outcome AS attempt_semantic,
                   attempt.terminal_at AS attempt_terminal_at
            FROM apify_actor_validations AS validation
            LEFT JOIN apify_actor_attempts AS attempt
              ON attempt.workspace_id = validation.workspace_id
             AND attempt.id = validation.attempt_id
            WHERE validation.workspace_id = ?
              AND validation.revision_id = ?
              AND validation.kind = 'route_reference'
              AND validation.status IN ('succeeded', 'failed', 'cancelled')
            """,
            (self.workspace_id, revision_id),
        ).fetchall()
        identities: set[str] = set()
        reference_identities: set[str] = set()
        considered = 0
        successes = 0
        first_reference_success: datetime | None = None
        for row in references:
            validation_success = (
                str(row["status"]) == "succeeded"
                and str(row["semantic_outcome"])
                in {"valid_nonempty", "valid_empty"}
            )
            if validation_success and row["target_fingerprint"]:
                fingerprint = str(row["target_fingerprint"])
                identities.add(fingerprint)
                reference_identities.add(fingerprint)
                completed = _parse_iso(
                    row["attempt_terminal_at"] or row["completed_at"]
                )
                if completed is not None and (
                    first_reference_success is None
                    or completed < first_reference_success
                ):
                    first_reference_success = completed
            if row["attempt_id"] is not None:
                attempt_status = str(row["attempt_status"] or "")
                if attempt_status not in {
                    "succeeded",
                    "valid_empty",
                    "actor_failed",
                }:
                    continue
                considered += 1
                if (
                    attempt_status in {"succeeded", "valid_empty"}
                    and str(row["attempt_semantic"])
                    in {"valid_nonempty", "valid_empty"}
                ):
                    successes += 1
            elif validation_success:
                # Compatibility for pre-attempt reference evidence retained by
                # the v15 migration and deterministic unit fixtures.
                considered += 1
                successes += 1

        if first_reference_success is not None:
            natural_attempts = connection.execute(
                """
                SELECT attempt.status, attempt.semantic_outcome,
                       attempt.source_id, attempt.terminal_at,
                       attempt.target_fingerprint
                FROM apify_actor_attempts AS attempt
                WHERE attempt.workspace_id = ?
                  AND attempt.adapter_revision_id = ?
                  AND attempt.source_id IS NOT NULL
                  AND attempt.attempt_group_id NOT LIKE 'canary:%'
                  AND attempt.status IN (
                      'succeeded', 'valid_empty', 'actor_failed'
                  )
                  AND attempt.terminal_at IS NOT NULL
                """,
                (self.workspace_id, revision_id),
            ).fetchall()
            for row in natural_attempts:
                terminal_at = _parse_iso(row["terminal_at"])
                if (
                    terminal_at is None
                    or terminal_at < first_reference_success
                ):
                    continue
                considered += 1
                if (
                    str(row["status"]) in {"succeeded", "valid_empty"}
                    and str(row["semantic_outcome"])
                    in {"valid_nonempty", "valid_empty"}
                ):
                    successes += 1
                    if row["target_fingerprint"]:
                        identities.add(str(row["target_fingerprint"]))
        active_as_backup_2 = connection.execute(
            """
            SELECT 1
            FROM apify_route_active_slots
            WHERE workspace_id = ? AND revision_id = ?
              AND slot_name = 'backup_2'
            LIMIT 1
            """,
            (self.workspace_id, revision_id),
        ).fetchone() is not None
        return {
            "considered": considered,
            "successes": successes,
            "distinct_identities": len(identities),
            "distinct_reference_targets": len(reference_identities),
            "active_as_backup_2": active_as_backup_2,
            "success_rate": successes / considered if considered else 0.0,
            "first_success": first_reference_success,
        }

    def certification_progress(self, revision_id: str) -> dict[str, Any]:
        connection = self.store.connect()
        revision = connection.execute(
            """
            SELECT lifecycle FROM apify_actor_adapter_revisions
            WHERE workspace_id = ? AND revision_id = ?
            """,
            (self.workspace_id, revision_id),
        ).fetchone()
        if revision is None:
            raise ActorOpsError(
                "apify_actor_revision_not_found",
                "Actor adapter revision was not found",
                status_code=404,
            )
        evidence = self._certification_evidence(connection, revision_id)
        first_success = evidence["first_success"]
        eligible_at = (
            first_success + timedelta(hours=48)
            if first_success is not None
            else None
        )
        now = _as_utc(self._now())
        required_references = 1 if bool(evidence["active_as_backup_2"]) else 2
        blockers: list[str] = []
        if int(evidence["distinct_identities"]) < 2:
            blockers.append("independent_identities_incomplete")
        if int(evidence["distinct_reference_targets"]) < required_references:
            blockers.append("reference_targets_incomplete")
        if int(evidence["considered"]) < 2:
            blockers.append("valid_samples_incomplete")
        if float(evidence["success_rate"]) < 0.95:
            blockers.append("success_rate_below_threshold")
        if eligible_at is None or eligible_at > now:
            blockers.append("observation_window_incomplete")
        return {
            "auto_promotes": True,
            "lifecycle": str(revision["lifecycle"]),
            "success_identities": {
                "current": int(evidence["distinct_identities"]),
                "required": 2,
            },
            "reference_targets": {
                "current": int(evidence["distinct_reference_targets"]),
                "required": required_references,
            },
            "valid_samples": {
                "current": int(evidence["considered"]),
                "successful": int(evidence["successes"]),
                "required": 2,
            },
            "success_rate": {
                "current": round(float(evidence["success_rate"]), 6),
                "required": 0.95,
            },
            "observation_started_at": (
                first_success.isoformat() if first_success is not None else None
            ),
            "eligible_at": eligible_at.isoformat() if eligible_at is not None else None,
            "remaining_seconds": (
                max(int((eligible_at - now).total_seconds()), 0)
                if eligible_at is not None
                else None
            ),
            "blockers": blockers,
        }

    def promote_eligible_revisions(
        self,
        *,
        revision_ids: tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> dict[str, int]:
        """Recover successful Canaries and certify without another paid Run."""

        base_parameters: list[Any] = [self.workspace_id]
        predicate = ""
        if revision_ids:
            placeholders = ",".join("?" for _ in revision_ids)
            predicate = f" AND revision.revision_id IN ({placeholders})"
            base_parameters.extend(revision_ids)
        bounded_limit = max(1, min(int(limit), 500))
        recovery_parameters = [*base_parameters, bounded_limit]
        recovery_rows = self.store.connect().execute(
            f"""
            SELECT revision.revision_id
            FROM apify_actor_adapter_revisions AS revision
            WHERE revision.workspace_id = ?
              AND revision.lifecycle = 'static_valid'
              {predicate}
              AND EXISTS (
                  SELECT 1
                  FROM apify_actor_validations AS validation
                  WHERE validation.workspace_id = revision.workspace_id
                    AND validation.revision_id = revision.revision_id
                    AND validation.kind = 'route_reference'
                    AND validation.status = 'succeeded'
                    AND validation.semantic_outcome IN (
                        'valid_nonempty', 'valid_empty'
                    )
              )
            ORDER BY revision.created_at, revision.revision_id
            LIMIT ?
            """,
            tuple(recovery_parameters),
        ).fetchall()
        recovered = 0
        for row in recovery_rows:
            try:
                self.transition_revision(
                    str(row["revision_id"]),
                    expected_lifecycle="static_valid",
                    lifecycle="probationary",
                )
            except ActorOpsError as exc:
                if exc.code in {
                    "apify_actor_revision_canary_incomplete",
                    "apify_actor_revision_generation_conflict",
                }:
                    continue
                raise
            recovered += 1

        parameters = list(base_parameters)
        cutoff = (
            _as_utc(self._now()) - timedelta(hours=48)
        ).isoformat()
        parameters.extend((cutoff, bounded_limit))
        rows = self.store.connect().execute(
            f"""
            SELECT revision.revision_id
            FROM apify_actor_adapter_revisions AS revision
            WHERE revision.workspace_id = ?
              AND revision.lifecycle = 'probationary'
              {predicate}
              AND EXISTS (
                  SELECT 1
                  FROM apify_actor_validations AS validation
                  WHERE validation.workspace_id = revision.workspace_id
                    AND validation.revision_id = revision.revision_id
                    AND validation.kind = 'route_reference'
                    AND validation.status = 'succeeded'
                    AND validation.semantic_outcome IN (
                        'valid_nonempty', 'valid_empty'
                    )
                    AND validation.completed_at <= ?
              )
            ORDER BY revision.canary_passed_at, revision.created_at,
                     revision.revision_id
            LIMIT ?
            """,
            tuple(parameters),
        ).fetchall()
        promoted = 0
        pending = 0
        for row in rows:
            try:
                self.transition_revision(
                    str(row["revision_id"]),
                    expected_lifecycle="probationary",
                    lifecycle="certified",
                )
            except ActorOpsError as exc:
                if exc.code in {
                    "apify_actor_revision_canary_incomplete",
                    "apify_actor_revision_observation_incomplete",
                    "apify_actor_revision_success_rate_low",
                    "apify_actor_revision_generation_conflict",
                }:
                    pending += 1
                    continue
                raise
            promoted += 1
        return {
            "recovered": recovered,
            "promoted": promoted,
            "pending": pending,
        }

    def _count_runnable_slots(
        self,
        connection: sqlite3.Connection,
        route_id: str,
    ) -> int:
        return int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM apify_route_active_slots AS slot
                JOIN apify_actor_candidates AS candidate
                  ON candidate.workspace_id = slot.workspace_id
                 AND candidate.id = slot.candidate_id
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = slot.workspace_id
                 AND revision.revision_id = slot.revision_id
                WHERE slot.workspace_id = ? AND slot.route_id = ?
                  AND candidate.state IN (
                      'closed', 'half_open', 'probationary'
                  )
                  AND revision.lifecycle IN (
                      'certified', 'probationary', 'legacy_builtin'
                  )
                """,
                (self.workspace_id, route_id),
            ).fetchone()[0]
        )

    def reorder_active_pool(
        self,
        route_id: str,
        *,
        candidate_ids: list[str],
        expected_generation: int,
    ) -> dict[str, Any]:
        """Reorder the existing three slots without changing runtime states."""

        if len(candidate_ids) != 3 or len(set(candidate_ids)) != 3:
            raise ActorOpsError(
                "apify_actor_active_pool_incomplete",
                "Active pool order must contain three unique candidates",
                status_code=422,
            )
        now = self._now_iso()
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            self._require_no_active_freshness_check(connection, route_id)
            rows = connection.execute(
                """
                SELECT slot.candidate_id, slot.revision_id,
                       revision.lifecycle
                FROM apify_route_active_slots AS slot
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = slot.workspace_id
                 AND revision.revision_id = slot.revision_id
                WHERE slot.workspace_id = ? AND slot.route_id = ?
                """,
                (self.workspace_id, route_id),
            ).fetchall()
            by_candidate = {
                str(row["candidate_id"]): row
                for row in rows
                if row["candidate_id"] and row["revision_id"]
            }
            if set(candidate_ids) != set(by_candidate):
                raise ActorOpsError(
                    "apify_actor_active_pool_incomplete",
                    "Active pool order must contain every current candidate",
                    status_code=422,
                )
            for slot_name, candidate_id in zip(
                SLOT_NAMES,
                candidate_ids,
                strict=True,
            ):
                lifecycle = str(by_candidate[candidate_id]["lifecycle"])
                allowed = (
                    {"certified", "legacy_builtin"}
                    if slot_name in {"primary", "backup_1"}
                    else {"certified", "probationary", "legacy_builtin"}
                )
                if lifecycle not in allowed:
                    raise ActorOpsError(
                        "apify_actor_active_pool_uncertified",
                        "Reordered pool does not satisfy the 2+1 policy",
                        status_code=422,
                    )
            offset = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(position), 0) + 4
                    FROM apify_actor_candidates
                    WHERE workspace_id = ? AND route_key = ?
                    """,
                    (self.workspace_id, route["route_key"]),
                ).fetchone()[0]
            )
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET position = position + ?, updated_at = ?
                WHERE workspace_id = ? AND route_key = ?
                """,
                (offset, now, self.workspace_id, route["route_key"]),
            )
            for position, (slot_name, candidate_id) in enumerate(
                zip(SLOT_NAMES, candidate_ids, strict=True)
            ):
                connection.execute(
                    """
                    UPDATE apify_route_active_slots
                    SET candidate_id = ?, revision_id = ?, updated_at = ?
                    WHERE workspace_id = ? AND route_id = ? AND slot_name = ?
                    """,
                    (
                        candidate_id,
                        by_candidate[candidate_id]["revision_id"],
                        now,
                        self.workspace_id,
                        route_id,
                        slot_name,
                    ),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET position = ?, updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (position, now, self.workspace_id, candidate_id),
                )
            connection.execute(
                """
                UPDATE apify_actor_route_profiles
                SET generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND route_id = ?
                """,
                (now, self.workspace_id, route_id),
            )
            connection.execute(
                """
                UPDATE apify_actor_routes
                SET generation = generation + 1,
                    last_switch_reason = 'admin_reorder',
                    last_switch_at = ?, updated_at = ?
                WHERE workspace_id = ? AND route_key = ?
                """,
                (now, now, self.workspace_id, route["route_key"]),
            )
            connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET validation_status = 'revalidation_pending',
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND route_id = ?
                """,
                (now, self.workspace_id, route_id),
            )
        return self.get_route(route_id)

    def set_active_candidate_runtime_state(
        self,
        route_id: str,
        candidate_id: str,
        *,
        enabled: bool,
        expected_generation: int,
    ) -> dict[str, Any]:
        """CAS-toggle one active slot while preserving the runtime fail-closed gate."""

        now = self._now_iso()
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            row = connection.execute(
                """
                SELECT slot.slot_name, candidate.state, revision.lifecycle
                FROM apify_route_active_slots AS slot
                JOIN apify_actor_candidates AS candidate
                  ON candidate.workspace_id = slot.workspace_id
                 AND candidate.id = slot.candidate_id
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = slot.workspace_id
                 AND revision.revision_id = slot.revision_id
                WHERE slot.workspace_id = ? AND slot.route_id = ?
                  AND slot.candidate_id = ?
                """,
                (self.workspace_id, route_id, candidate_id),
            ).fetchone()
            if row is None:
                raise ActorOpsError(
                    "apify_actor_candidate_not_found",
                    "Actor candidate is not in the active pool",
                    status_code=404,
                )
            lifecycle = str(row["lifecycle"])
            slot_name = str(row["slot_name"])
            if enabled:
                allowed = {"certified", "probationary", "legacy_builtin"}
                if lifecycle not in allowed:
                    raise ActorOpsError(
                        "apify_actor_candidate_canary_required",
                        "This Actor revision requires v15 Canary approval",
                        status_code=412,
                    )
                new_state = (
                    "probationary" if lifecycle == "probationary" else "closed"
                )
            else:
                new_state = "disabled"
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = ?, probe_claimed_at = NULL, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (new_state, now, self.workspace_id, candidate_id),
            )
            runnable = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM apify_route_active_slots AS slot
                    JOIN apify_actor_candidates AS candidate
                      ON candidate.workspace_id = slot.workspace_id
                     AND candidate.id = slot.candidate_id
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = slot.workspace_id
                     AND revision.revision_id = slot.revision_id
                    WHERE slot.workspace_id = ? AND slot.route_id = ?
                      AND candidate.state IN ('closed', 'half_open', 'probationary')
                      AND revision.lifecycle IN (
                          'certified', 'probationary', 'legacy_builtin'
                      )
                    """,
                    (self.workspace_id, route_id),
                ).fetchone()[0]
            )
            minimum = int(route["min_runtime_healthy"])
            profile_status = (
                "ready" if runnable >= minimum else "candidate_shortfall"
            )
            compatibility_status = (
                "ready" if runnable == 3
                else "degraded" if runnable >= minimum
                else "exhausted"
            )
            active = connection.execute(
                """
                SELECT slot.candidate_id
                FROM apify_route_active_slots AS slot
                JOIN apify_actor_candidates AS candidate
                  ON candidate.workspace_id = slot.workspace_id
                 AND candidate.id = slot.candidate_id
                WHERE slot.workspace_id = ? AND slot.route_id = ?
                  AND candidate.state IN ('closed', 'half_open', 'probationary')
                ORDER BY CASE slot.slot_name
                    WHEN 'primary' THEN 1 WHEN 'backup_1' THEN 2 ELSE 3 END
                LIMIT 1
                """,
                (self.workspace_id, route_id),
            ).fetchone()
            connection.execute(
                """
                UPDATE apify_actor_route_profiles
                SET status = ?, generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND route_id = ?
                """,
                (profile_status, now, self.workspace_id, route_id),
            )
            connection.execute(
                """
                UPDATE apify_actor_routes
                SET status = ?, active_candidate_id = ?,
                    generation = generation + 1,
                    last_switch_reason = ?, last_switch_at = ?,
                    blocked_reason = ?, updated_at = ?
                WHERE workspace_id = ? AND route_key = ?
                """,
                (
                    compatibility_status,
                    str(active["candidate_id"]) if active else None,
                    "admin_enable" if enabled else "admin_disable",
                    now,
                    None if runnable >= minimum else "candidate_shortfall",
                    now,
                    self.workspace_id,
                    route["route_key"],
                ),
            )
        return self.get_route(route_id)

    def schedule_gate(
        self,
        route_id: str,
        *,
        source_id: str | None = None,
    ) -> RouteScheduleGate:
        try:
            snapshot = self.freeze_execution(
                route_id,
                source_id=source_id,
                enforce_gate=False,
            )
        except ActorOpsError as error:
            return RouteScheduleGate(False, "blocked", 0, error.code)
        route = self.store.connect().execute(
            """
            SELECT status, min_runtime_healthy
            FROM apify_actor_route_profiles
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, route_id),
        ).fetchone()
        if route is None:
            return RouteScheduleGate(
                False,
                "blocked",
                0,
                "apify_actor_route_not_found",
            )
        runnable = len(snapshot.slots)
        status = str(route["status"])
        if status in _BLOCKING_ROUTE_STATUSES:
            return RouteScheduleGate(
                False,
                status,
                runnable,
                "apify_actor_route_blocked",
            )
        if runnable < int(route["min_runtime_healthy"]):
            return RouteScheduleGate(
                False,
                "candidate_shortfall",
                runnable,
                "apify_actor_route_candidate_shortfall",
            )
        return RouteScheduleGate(
            True,
            "ready" if runnable == 3 else "degraded",
            runnable,
        )

    def freeze_execution(
        self,
        route_id: str,
        *,
        source_id: str | None = None,
        key_pool_generation: int | None = None,
        enforce_gate: bool = True,
    ) -> RouteExecutionSnapshot:
        connection = self.store.connect()
        route = self._require_route(connection, route_id)
        binding = None
        if source_id is not None:
            binding = connection.execute(
                """
                SELECT * FROM apify_source_route_bindings
                WHERE workspace_id = ? AND source_id = ? AND route_id = ?
                """,
                (self.workspace_id, source_id, route_id),
            ).fetchone()
            if binding is None:
                raise ActorOpsError(
                    "apify_actor_source_binding_not_ready",
                    "Source does not have an Actor route binding",
                    status_code=412,
                )
        rows = connection.execute(
            """
            SELECT slot.slot_name, slot.candidate_id, slot.revision_id,
                   revision.actor_id, revision.publisher, revision.build_id,
                   revision.build_number, revision.manifest_hash,
                   revision.manifest_json, revision.lifecycle,
                   revision.execution_mode, revision.observed_manifest,
                   revision.security_evidence_json,
                   candidate.state AS candidate_state
            FROM apify_route_active_slots AS slot
            LEFT JOIN apify_actor_adapter_revisions AS revision
              ON revision.revision_id = slot.revision_id
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.id = slot.candidate_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
            ORDER BY CASE slot.slot_name
                WHEN 'primary' THEN 1
                WHEN 'backup_1' THEN 2
                ELSE 3 END
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        validated_revision_ids: set[str] | None = None
        source_verified = False
        if binding is not None:
            validation_status = str(binding["validation_status"])
            expected_slots = {str(row["slot_name"]): str(row["revision_id"]) for row in rows if row["revision_id"]}
            if validation_status in _READY_BINDING_STATUSES and str(binding["verified_revision_set_hash"] or "") != revision_set_hash(expected_slots):
                validation_status = "revalidation_pending"
            source_verified = validation_status in _READY_BINDING_STATUSES
            if validation_status not in {
                "ready_1of1",
                "ready_2of2",
                "ready_3of3",
                "legacy_validation_pending",
                "revalidation_pending",
            }:
                raise ActorOpsError(
                    "apify_actor_source_binding_not_ready",
                    "Source Actor validation is not ready",
                    status_code=412,
                )
            if validation_status == "revalidation_pending":
                validated_revision_ids = {
                    str(row["revision_id"])
                    for row in connection.execute(
                        """
                        SELECT revision_id FROM apify_actor_validations
                        WHERE workspace_id = ? AND route_id = ? AND source_id = ?
                          AND kind = 'source_canary' AND status = 'succeeded'
                          AND target_fingerprint = ?
                          AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                        """,
                        (
                            self.workspace_id,
                            route_id,
                            source_id,
                            str(binding["target_fingerprint"]),
                        ),
                    ).fetchall()
                    if row["revision_id"]
                }
                if binding["verified_revision_set_hash"] is None:
                    validated_revision_ids.update(
                        str(row["revision_id"])
                        for row in rows
                        if row["revision_id"]
                        and str(row["lifecycle"]) == "legacy_builtin"
                    )
                source_verified = len(expected_slots) >= int(route["min_runtime_healthy"]) and set(expected_slots.values()) <= validated_revision_ids
        if (
            binding is not None
            and binding["preferred_candidate_id"]
            and binding["preference_suspended_at"] is None
        ):
            preferred_candidate_id = str(binding["preferred_candidate_id"])
            rows = sorted(
                rows,
                key=lambda row: (
                    0
                    if str(row["candidate_id"] or "")
                    == preferred_candidate_id
                    else 1,
                    {"primary": 0, "backup_1": 1, "backup_2": 2}.get(
                        str(row["slot_name"]), 3
                    ),
                ),
            )
        frozen: list[RouteSlotSnapshot] = []
        for row in rows:
            if not row["candidate_id"] or not row["revision_id"]:
                continue
            lifecycle = str(row["lifecycle"])
            slot_name = str(row["slot_name"])
            if str(row["candidate_state"]) not in _RUNNABLE_CANDIDATE_STATES:
                continue
            allowed_lifecycle = {
                "certified",
                "probationary",
                "legacy_builtin",
            }
            if lifecycle not in allowed_lifecycle:
                continue
            if source_id is not None:
                target_health = connection.execute(
                    """
                    SELECT paused_until
                    FROM apify_actor_target_health
                    WHERE workspace_id = ? AND route_key = ?
                      AND candidate_id = ? AND source_id = ?
                    """,
                    (
                        self.workspace_id,
                        route["route_key"],
                        row["candidate_id"],
                        source_id,
                    ),
                ).fetchone()
                paused_until = (
                    _parse_iso(target_health["paused_until"])
                    if target_health is not None
                    else None
                )
                if (
                    paused_until is not None
                    and paused_until > _as_utc(self._now())
                ):
                    continue
            if (
                validated_revision_ids is not None
                and str(row["revision_id"]) not in validated_revision_ids
            ):
                continue
            manifest = (
                None
                if lifecycle == "legacy_builtin"
                or str(row["execution_mode"] or "pinned") == "current"
                or bool(row["observed_manifest"])
                else parse_actor_manifest(str(row["manifest_json"]))
            )
            security_evidence = _safe_json(
                row["security_evidence_json"], {}
            )
            if manifest is not None:
                if (
                    manifest.actor_id != str(row["actor_id"])
                    or manifest.build_number != str(row["build_number"])
                    or actor_manifest_hash(manifest)
                    != str(row["manifest_hash"] or "")
                ):
                    raise ActorOpsError(
                        "apify_actor_revision_integrity_failed",
                        "Actor adapter revision failed its integrity check",
                        status_code=412,
                    )
                _assert_manifest_route_hosts(manifest, str(route["platform"]))
            frozen.append(
                RouteSlotSnapshot(
                    slot_name=slot_name,  # type: ignore[arg-type]
                    candidate_id=str(row["candidate_id"]),
                    revision_id=str(row["revision_id"]),
                    actor_id=str(row["actor_id"]),
                    publisher=str(row["publisher"]),
                    build_id=(
                        str(row["build_id"]) if row["build_id"] is not None else None
                    ),
                    build_number=(
                        str(row["build_number"])
                        if row["build_number"] is not None
                        else None
                    ),
                    manifest_hash=(
                        str(row["manifest_hash"])
                        if row["manifest_hash"] is not None
                        else None
                    ),
                    lifecycle=lifecycle,
                    candidate_state=str(row["candidate_state"]),
                    manifest=manifest,
                    execution_mode=str(row["execution_mode"] or "pinned"),
                    observed_manifest=bool(row["observed_manifest"]),
                    compatibility_input_dialect=str(
                        security_evidence.get("input_dialect")
                        or "controlled_default"
                    ),
                    compatibility_input_count_field=(
                        str(security_evidence["input_count_field"])
                        if security_evidence.get("input_count_field")
                        else None
                    ),
                )
            )
        if key_pool_generation is None:
            key_row = connection.execute(
                """
                SELECT generation FROM apify_key_pool_state
                WHERE workspace_id = ?
                """,
                (self.workspace_id,),
            ).fetchone()
            key_pool_generation = int(key_row["generation"]) if key_row else None
        snapshot = RouteExecutionSnapshot(
            workspace_id=self.workspace_id,
            route_id=route_id,
            route_key=str(route["route_key"]),
            route_generation=int(route["generation"]),
            per_run_cap_usd=float(route["per_run_cap_usd"]),
            slots=tuple(frozen),
            source_id=source_id,
            binding_id=(
                str(binding["binding_id"]) if binding is not None else None
            ),
            binding_generation=(
                int(binding["generation"]) if binding is not None else None
            ),
            binding_revision_set_hash=(
                str(binding["verified_revision_set_hash"])
                if binding is not None
                and binding["verified_revision_set_hash"] is not None
                else None
            ),
            target_fingerprint=(
                str(binding["target_fingerprint"])
                if binding is not None
                else None
            ),
            key_pool_generation=key_pool_generation,
        )
        if enforce_gate:
            if str(route["status"]) in _BLOCKING_ROUTE_STATUSES:
                raise ActorOpsError(
                    "apify_actor_route_blocked",
                    "Actor route is blocked",
                    retryable=True,
                    status_code=503,
                )
            required_slots = 1 if source_verified else int(route["min_runtime_healthy"])
            if len(frozen) < required_slots:
                raise ActorOpsError(
                    "apify_actor_route_candidate_shortfall",
                    "The route does not have its required runnable Actor revisions",
                    retryable=True,
                    status_code=503,
                )
        return snapshot

    def assert_publishable(self, snapshot: RouteExecutionSnapshot) -> None:
        connection = self.store.connect()
        route = self._require_route(connection, snapshot.route_id)
        stale = int(route["generation"]) != snapshot.route_generation
        current_rows = connection.execute(
            """
            SELECT slot.slot_name, slot.revision_id,
                   revision.lifecycle, candidate.state AS candidate_state
            FROM apify_route_active_slots AS slot
            LEFT JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = slot.workspace_id
             AND candidate.id = slot.candidate_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
            """,
            (self.workspace_id, snapshot.route_id),
        ).fetchall()
        current_slots = {
            str(row["slot_name"]): str(row["revision_id"] or "")
            for row in current_rows
        }
        frozen_slots = {
            slot.slot_name: slot.revision_id
            for slot in snapshot.slots
        }
        for name, revision_id in frozen_slots.items():
            stale = stale or current_slots.get(name) != revision_id
        current_by_slot = {
            str(row["slot_name"]): row
            for row in current_rows
        }
        for slot in snapshot.slots:
            row = current_by_slot.get(slot.slot_name)
            allowed_lifecycle = {
                "certified",
                "probationary",
                "legacy_builtin",
            }
            stale = (
                stale
                or row is None
                or str(row["lifecycle"]) not in allowed_lifecycle
            )
        if snapshot.binding_id is not None:
            binding = connection.execute(
                """
                SELECT generation, verified_revision_set_hash
                FROM apify_source_route_bindings
                WHERE workspace_id = ? AND binding_id = ?
                """,
                (self.workspace_id, snapshot.binding_id),
            ).fetchone()
            stale = stale or binding is None
            if binding is not None:
                stale = stale or int(binding["generation"]) != snapshot.binding_generation
                stale = stale or (
                    (
                        str(binding["verified_revision_set_hash"])
                        if binding["verified_revision_set_hash"] is not None
                        else None
                    )
                    != snapshot.binding_revision_set_hash
                )
        if snapshot.key_pool_generation is not None:
            key_row = connection.execute(
                """
                SELECT generation FROM apify_key_pool_state
                WHERE workspace_id = ?
                """,
                (self.workspace_id,),
            ).fetchone()
            stale = stale or key_row is None
            if key_row is not None:
                stale = stale or int(key_row["generation"]) != snapshot.key_pool_generation
        if stale:
            raise ActorOpsError(
                "apify_actor_publication_stale",
                "Actor route changed; discard the stale result",
                retryable=True,
            )

    def bind_source(
        self,
        *,
        source_id: str,
        route_id: str,
        target_fingerprint: str,
        mode: Literal["primary", "fallback"],
        expected_generation: int | None = None,
    ) -> dict[str, Any]:
        if not _HEX_64_RE.fullmatch(str(target_fingerprint)):
            raise ActorOpsError(
                "apify_actor_target_fingerprint_invalid",
                "Source target fingerprint is invalid",
                status_code=422,
            )
        now = self._now_iso()
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            compatibility_ready = bool(
                str(route["admission_mode"]) == "compatibility"
                and self.source_capability_ready(
                    route_id,
                    connection=connection,
                )
            )
            active_digest = None
            if compatibility_ready:
                active_digest = revision_set_hash(
                    {
                        str(row["slot_name"]): str(row["revision_id"])
                        for row in connection.execute(
                            """
                            SELECT slot_name, revision_id
                            FROM apify_route_active_slots
                            WHERE workspace_id = ? AND route_id = ?
                              AND revision_id IS NOT NULL
                            """,
                            (self.workspace_id, route_id),
                        ).fetchall()
                    }
                )
            existing = connection.execute(
                """
                SELECT * FROM apify_source_route_bindings
                WHERE workspace_id = ? AND source_id = ?
                """,
                (self.workspace_id, source_id),
            ).fetchone()
            if existing is None:
                if expected_generation not in (None, 0):
                    raise ActorOpsError(
                        "apify_actor_binding_generation_conflict",
                        "Source Actor binding changed; reload before retrying",
                    )
                binding_id = f"apify-binding-{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO apify_source_route_bindings (
                        binding_id, workspace_id, source_id, route_id,
                        target_fingerprint, mode, validation_status,
                        verified_revision_set_hash, generation, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        binding_id,
                        self.workspace_id,
                        source_id,
                        route_id,
                        target_fingerprint,
                        mode,
                        "ready_1of1" if compatibility_ready else "pending_validation",
                        active_digest,
                        now,
                        now,
                    ),
                )
            else:
                if expected_generation is None or int(existing["generation"]) != int(
                    expected_generation
                ):
                    raise ActorOpsError(
                        "apify_actor_binding_generation_conflict",
                        "Source Actor binding changed; reload before retrying",
                    )
                binding_id = str(existing["binding_id"])
                connection.execute(
                    """
                    UPDATE apify_source_route_bindings
                    SET route_id = ?, target_fingerprint = ?, mode = ?,
                        validation_status = ?,
                        verified_revision_set_hash = ?,
                        generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND binding_id = ? AND generation = ?
                    """,
                    (
                        route_id,
                        target_fingerprint,
                        mode,
                        "ready_1of1" if compatibility_ready else "pending_validation",
                        active_digest,
                        now,
                        self.workspace_id,
                        binding_id,
                        expected_generation,
                    ),
                )
        return self.get_source_binding(source_id)

    def get_source_binding(self, source_id: str) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT binding_id, source_id, route_id, mode, validation_status,
                   verified_revision_set_hash, generation, created_at, updated_at
            FROM apify_source_route_bindings
            WHERE workspace_id = ? AND source_id = ?
            """,
            (self.workspace_id, source_id),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_source_binding_not_found",
                "Source Actor binding was not found",
                status_code=404,
            )
        return dict(row)

    def legacy_actor_ids(self, route_id: str) -> tuple[str, ...]:
        """Return active compatibility Actor slugs for a server-driven upgrade.

        The browser never supplies these identifiers. Discovery looks them up
        directly and still has to freeze a new exact Build and Manifest before
        any paid validation can be approved; another Actor cannot replace one.
        """

        self._require_route(self.store.connect(), route_id)
        rows = self.store.connect().execute(
            """
            SELECT revision.actor_id
            FROM apify_route_active_slots AS slot
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
              AND revision.lifecycle = 'legacy_builtin'
            ORDER BY CASE slot.slot_name
                WHEN 'primary' THEN 1 WHEN 'backup_1' THEN 2 ELSE 3 END
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        return tuple(str(row["actor_id"]) for row in rows)

    def assert_source_target(
        self,
        route_id: str,
        source_id: str,
        target: str,
    ) -> None:
        """Fail before spend if catalog config and binding identity diverge."""

        row = self.store.connect().execute(
            """
            SELECT target_fingerprint
            FROM apify_source_route_bindings
            WHERE workspace_id = ? AND source_id = ? AND route_id = ?
            """,
            (self.workspace_id, source_id, route_id),
        ).fetchone()
        expected = source_target_fingerprint(
            self.workspace_id,
            route_id,
            target,
            platform=str(
                self._require_route(
                    self.store.connect(),
                    route_id,
                )["platform"]
            ),
        )
        if row is None or str(row["target_fingerprint"]) != expected:
            raise ActorOpsError(
                "apify_actor_source_target_stale",
                "Source target changed before Actor execution",
                status_code=412,
            )

    def _list_compatibility_candidates(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
    ) -> dict[str, Any]:
        """Compatibility facade retained for callers outside slot management."""

        return self._project_compatibility_candidates(connection, route)

    def _get_compatibility_canary_plan(
        self,
        run_id: str,
        *,
        candidate_ids: tuple[str, ...],
        max_total_charge_usd: float | None,
        target_slot_count: int | None,
    ) -> dict[str, Any]:
        if (
            len(candidate_ids) != 1
            or len(set(candidate_ids)) != 1
            or (target_slot_count is not None and int(target_slot_count) != 1)
        ):
            raise ActorOpsError(
                "apify_actor_manual_candidate_set_incomplete",
                "Compatibility mode requires exactly one Actor",
                status_code=422,
            )
        connection = self.store.connect()
        run = connection.execute(
            """
            SELECT run.*, profile.route_key, profile.platform,
                   profile.target_type, profile.capability, profile.mode,
                   profile.generation, profile.per_run_cap_usd
            FROM apify_actor_discovery_runs AS run
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = run.workspace_id
             AND profile.route_id = run.route_id
            WHERE run.workspace_id = ? AND run.run_id = ?
            """,
            (self.workspace_id, str(run_id)),
        ).fetchone()
        if run is None:
            raise ActorOpsError(
                "apify_actor_discovery_run_not_found",
                "Actor discovery run was not found",
                status_code=404,
            )
        if str(run["stage"]) not in {
            "awaiting_canary_approval",
            "canary_exhausted",
            "candidate_shortfall",
            "activation_ready",
            "completed",
        }:
            raise ActorOpsError(
                "apify_actor_discovery_not_awaiting_approval",
                "Compatibility mode is available only after strict shortfall",
                status_code=409,
            )
        pool = self._list_compatibility_candidates(
            connection,
            self._require_route(connection, str(run["route_id"])),
        )
        selected = next(
            (
                item
                for item in pool["candidates"]
                if str(item["candidate_id"]) == str(candidate_ids[0])
            ),
            None,
        )
        if selected is None or not bool(selected["selectable"]):
            raise ActorOpsError(
                "apify_actor_candidate_not_selectable",
                "Selected Actor does not satisfy compatibility hard fences",
                status_code=412,
            )
        revision = connection.execute(
            """
            SELECT revision.*, candidate.display_name
            FROM apify_actor_adapter_revisions AS revision
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE revision.workspace_id = ? AND revision.revision_id = ?
            """,
            (self.workspace_id, str(selected["revision_id"])),
        ).fetchone()
        if revision is None:
            raise ActorOpsError(
                "apify_actor_revision_not_found",
                "Selected Actor revision was not found",
                status_code=404,
            )
        cap = min(float(run["per_run_cap_usd"]), 0.02)
        if max_total_charge_usd is not None and not math.isclose(
            _bounded_cost(max_total_charge_usd, maximum=0.02),
            cap,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ActorOpsError(
                "apify_actor_canary_plan_conflict",
                "Compatibility Canary cost cap changed; reload before approval",
                status_code=409,
            )
        validation_profile = {
            "timeout_seconds": VALIDATION_TIMEOUT_SECONDS_DEFAULT,
            "sample_items": 1,
            "max_charge_usd": round(cap, 6),
            "supports_sample_items": True,
            "profile_hash": validation_profile_hash(
                timeout_seconds=VALIDATION_TIMEOUT_SECONDS_DEFAULT,
                sample_items=1,
                max_charge_usd=cap,
            ),
        }
        from .apify_actor_canary import next_reference_fingerprint

        reference_fingerprint = next_reference_fingerprint(
            self.store,
            workspace_id=self.workspace_id,
            platform=str(run["platform"]),
            route_id=str(run["route_id"]),
            revision_id=str(revision["revision_id"]),
        )
        base_rows = connection.execute(
            """
            SELECT slot_name, revision_id FROM apify_route_active_slots
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, str(run["route_id"])),
        ).fetchall()
        base_slots = {
            str(row["slot_name"]): str(row["revision_id"] or "")
            for row in base_rows
        }
        already_validated = bool(selected["already_validated"])
        item = {
            "ordinal": 1,
            "candidate_id": str(revision["candidate_id"]),
            "revision_id": str(revision["revision_id"]),
            "actor_id": str(revision["actor_id"]),
            "actor_public_name": _actor_public_name(
                revision["display_name"],
                revision["publisher"],
                revision["actor_id"],
            ),
            "publisher": str(revision["publisher"]),
            "build_id": str(revision["build_id"] or ""),
            "build_number": str(revision["build_number"] or ""),
            "manifest_hash": str(revision["manifest_hash"] or ""),
            "execution_mode": str(revision["execution_mode"]),
            "already_validated": already_validated,
            "authorized_cap_usd": round(cap, 6),
            "validation_profile": validation_profile,
            "compatibility_warnings": list(
                selected.get("compatibility_warnings") or []
            ),
        }
        payload = {
            "schema_version": 4,
            "goal": "compatibility_single",
            "selection_mode": "manual",
            "target_slot_count": 1,
            "run_id": str(run["run_id"]),
            "route_id": str(run["route_id"]),
            "generation": int(run["generation"]),
            "base_pool_hash": revision_set_hash(base_slots),
            "items": [
                {
                    key: item[key]
                    for key in (
                        "ordinal",
                        "candidate_id",
                        "revision_id",
                        "actor_id",
                        "publisher",
                        "build_id",
                        "build_number",
                        "manifest_hash",
                        "execution_mode",
                        "already_validated",
                        "authorized_cap_usd",
                        "validation_profile",
                    )
                }
            ],
            "required_success_count": 1,
            "required_source_slots": 0,
            "max_total_charge_usd": round(cap, 6),
        }
        plan_hash = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return {
            **payload,
            "route_key": str(run["route_key"]),
            "platform": str(run["platform"]),
            "target_type": str(run["target_type"]),
            "capability": str(run["capability"]),
            "mode": str(run["mode"]),
            "status": "activation_ready" if already_validated else "ready",
            "ready": True,
            "activation_ready": already_validated,
            "plan_hash": plan_hash,
            "max_candidates": 1,
            "route_validation_cap_usd": round(cap, 6),
            "source_validation_cap_usd": 0.0,
            "source_count": 0,
            "source_validation_count": 0,
            "per_candidate_cap_usd": round(cap, 6),
            "successful_actor_count": int(already_validated),
            "successful_publisher_count": int(already_validated),
            "attempts_used": 0,
            "attempts_remaining": 1,
            "budget_remaining_usd": 0.0,
            "items": [item],
            "_eligible_candidate_count": 1,
            "_source_snapshot": [],
            "_reference_fingerprints": {
                str(revision["revision_id"]): reference_fingerprint
            },
        }

    def _get_pool_stage_canary_plan(
        self,
        run_id: str,
        *,
        goal: Literal[
            "initial_pool", "complete_third", "upgrade_legacy",
            "compatibility_single", "add_slot", "replace_slot",
        ],
        max_candidates: int,
        max_total_charge_usd: float | None,
        candidate_ids: tuple[str, ...] | None = None,
        candidate_validation_profiles: Sequence[Mapping[str, Any]] | None = None,
        target_slot_count: int | None = None,
        target_slot: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(max_candidates, bool) or not 1 <= int(max_candidates) <= 3:
            raise ActorOpsError(
                "apify_actor_canary_batch_limit_invalid",
                "A staged Canary batch may contain one to three candidates",
                status_code=422,
            )
        connection = self.store.connect()
        run = connection.execute(
            """
            SELECT run.*, profile.route_key, profile.platform,
                   profile.target_type, profile.capability, profile.mode,
                   profile.generation, profile.per_run_cap_usd,
                   profile.min_publishers, profile.min_runtime_healthy
            FROM apify_actor_discovery_runs AS run
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = run.workspace_id
             AND profile.route_id = run.route_id
            WHERE run.workspace_id = ? AND run.run_id = ?
            """,
            (self.workspace_id, run_id),
        ).fetchone()
        if run is None:
            raise ActorOpsError(
                "apify_actor_discovery_run_not_found",
                "Actor discovery run was not found",
                status_code=404,
            )
        if str(run["stage"]) not in {
            "awaiting_canary_approval",
            "canary_exhausted",
            "candidate_shortfall",
            "activation_ready",
            "completed",
        }:
            raise ActorOpsError(
                "apify_actor_discovery_not_awaiting_approval",
                "Actor discovery run is not ready for staged validation",
                status_code=409,
            )
        manual_selection = candidate_ids is not None
        active_slots, populated, resolved_target_slot_count = self.pool_stage_context(
            connection,
            run=run,
            goal=goal,
            target_slot=target_slot,
            requested_count=target_slot_count,
        )
        if (
            goal in {"complete_third", "upgrade_legacy"}
            and resolved_target_slot_count != 3
        ):
            raise ActorOpsError(
                "apify_actor_pool_target_count_invalid",
                "This Actor pool workflow requires all three slots",
                status_code=422,
            )
        if manual_selection:
            expected_count = (
                1
                if goal in {"complete_third", "add_slot", "replace_slot"}
                else 3
                if goal == "upgrade_legacy"
                else resolved_target_slot_count
            )
            if (
                len(candidate_ids or ()) != expected_count
                or len(set(candidate_ids or ())) != expected_count
                or any(
                    not str(candidate_id).strip()
                    or len(str(candidate_id)) > 128
                    for candidate_id in candidate_ids or ()
                )
            ):
                raise ActorOpsError(
                    "apify_actor_manual_candidate_set_incomplete",
                    "Manual Actor selection must contain the exact required candidate count",
                    status_code=422,
                )
        if goal == "complete_third":
            if (
                len(populated) != 2
                or active_slots.get("backup_2") is None
                or active_slots["backup_2"]["revision_id"] is not None
                or any(
                    active_slots.get(name) is None
                    or str(active_slots[name]["lifecycle"])
                    not in {"probationary", "certified"}
                    or not active_slots[name]["build_id"]
                    or not active_slots[name]["build_number"]
                    or not active_slots[name]["manifest_hash"]
                    for name in ("primary", "backup_1")
                )
            ):
                raise ActorOpsError(
                    "apify_actor_pool_stage_precondition_incomplete",
                    "Third-slot completion requires two runnable exact-Build actors",
                    status_code=412,
                )
            required_successes = 1
            required_source_slots = 3
        elif goal in {"add_slot", "replace_slot"}:
            # The target slot has already been validated against the live
            # fixed pool above. The one new revision is staged without
            # changing any active slot until full source proof is complete.
            required_successes = 1
            required_source_slots = resolved_target_slot_count
        elif goal == "upgrade_legacy":
            if len(populated) != 3 or not all(
                str(row["lifecycle"]) == "legacy_builtin" for row in populated
            ):
                raise ActorOpsError(
                    "apify_actor_pool_stage_precondition_incomplete",
                    "Legacy upgrade requires the existing three-Actor compatibility pool",
                    status_code=412,
                )
            required_successes = resolved_target_slot_count
            required_source_slots = resolved_target_slot_count
        else:
            if len(populated) >= resolved_target_slot_count:
                raise ActorOpsError(
                    "apify_actor_pool_stage_precondition_incomplete",
                    "Initial Actor setup requires an unconfigured Route",
                    status_code=412,
                )
            required_successes = resolved_target_slot_count
            required_source_slots = resolved_target_slot_count

        active_actor_ids = {
            str(row["actor_id"]) for row in populated if row["actor_id"]
        }
        upgradeable_legacy_actor_ids = {
            str(row["actor_id"])
            for row in populated
            if row["actor_id"] and str(row["lifecycle"]) == "legacy_builtin"
        }
        active_revision_ids = {
            str(row["revision_id"]) for row in populated if row["revision_id"]
        }
        candidates = connection.execute(
            """
            SELECT candidate.id AS candidate_id,
                   candidate.display_name AS actor_public_name,
                   revision.revision_id, revision.actor_id,
                   revision.publisher, revision.build_id,
                   revision.build_number, revision.manifest_hash,
                   revision.manifest_json,
                   revision.pricing_json, revision.lifecycle,
                   candidate.position, candidate.state AS candidate_state,
                   candidate.last_error_code AS candidate_error_code,
                   revision.created_at,
                   EXISTS (
                       SELECT 1
                       FROM apify_actor_discovery_run_revisions AS current_link
                       WHERE current_link.workspace_id = revision.workspace_id
                         AND current_link.run_id = ?
                         AND current_link.revision_id = revision.revision_id
                   ) AS in_current_run,
                   EXISTS (
                       SELECT 1 FROM apify_actor_validations AS proof
                       WHERE proof.workspace_id = revision.workspace_id
                         AND proof.route_id = ?
                         AND proof.revision_id = revision.revision_id
                         AND proof.kind = 'route_reference'
                         AND proof.status = 'succeeded'
                         AND proof.cost_final = 1
                         AND proof.semantic_outcome IN (
                             'valid_nonempty', 'valid_empty'
                         )
                   ) AS already_validated
            FROM apify_actor_adapter_revisions AS revision
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE revision.workspace_id = ?
              AND candidate.route_key = ?
              AND revision.lifecycle IN (
                  'static_valid', 'probationary', 'certified'
              )
              AND revision.build_id IS NOT NULL
              AND revision.build_number IS NOT NULL
              AND revision.manifest_hash IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM apify_actor_discovery_run_revisions AS association
                  JOIN apify_actor_discovery_runs AS source_run
                    ON source_run.workspace_id = association.workspace_id
                   AND source_run.run_id = association.run_id
                  WHERE association.workspace_id = revision.workspace_id
                    AND association.revision_id = revision.revision_id
                    AND source_run.route_id = ?
              )
              AND NOT EXISTS (
                  SELECT 1 FROM apify_actor_validations AS active_validation
                  WHERE active_validation.workspace_id = revision.workspace_id
                    AND active_validation.revision_id = revision.revision_id
                    AND active_validation.kind = 'route_reference'
                    AND active_validation.status IN ('queued', 'running')
              )
            ORDER BY already_validated DESC, candidate.position,
                     revision.created_at, revision.revision_id
            """,
            (
                str(run["run_id"]),
                str(run["route_id"]),
                self.workspace_id,
                str(run["route_key"]),
                str(run["route_id"]),
            ),
        ).fetchall()
        candidate_rows: Sequence[sqlite3.Row]
        if manual_selection:
            latest_by_candidate: dict[str, sqlite3.Row] = {}
            for row in candidates:
                if goal != "upgrade_legacy" and not bool(row["in_current_run"]):
                    continue
                candidate_id = str(row["candidate_id"])
                previous = latest_by_candidate.get(candidate_id)
                if previous is None or (
                    int(bool(row["already_validated"])),
                    int(bool(row["in_current_run"])),
                    str(row["created_at"]),
                    str(row["revision_id"]),
                ) > (
                    int(bool(previous["already_validated"])),
                    int(bool(previous["in_current_run"])),
                    str(previous["created_at"]),
                    str(previous["revision_id"]),
                ):
                    latest_by_candidate[candidate_id] = row
            candidate_rows = sorted(
                latest_by_candidate.values(),
                key=lambda row: (
                    int(row["position"] or 0),
                    str(row["candidate_id"]),
                ),
            )
        else:
            candidate_rows = candidates

        distinct: list[sqlite3.Row] = []
        seen_actors = set(active_actor_ids)
        if goal == "upgrade_legacy":
            seen_actors.difference_update(upgradeable_legacy_actor_ids)
        for row in candidate_rows:
            actor_id = str(row["actor_id"])
            if goal == "upgrade_legacy" and actor_id not in active_actor_ids:
                continue
            if actor_id in seen_actors or str(row["revision_id"]) in active_revision_ids:
                continue
            if (
                goal == "upgrade_legacy"
                and _pricing_exceeds_usd_cap(
                    _safe_json(row["pricing_json"], {}),
                    VALIDATION_MAX_CHARGE_USD_DEFAULT,
                )
            ):
                continue
            if self._revision_canary_block_reason(
                connection,
                str(run["route_id"]),
                str(row["revision_id"]),
            ) is not None:
                continue
            if (
                str(row["candidate_state"]) == "disabled"
                and row["candidate_error_code"]
            ):
                continue
            seen_actors.add(actor_id)
            distinct.append(row)

        selected: tuple[sqlite3.Row, ...] = ()
        maximum = min(int(max_candidates), len(distinct))
        if (
            not manual_selection
            and goal == "initial_pool"
            and required_successes == 1
        ):
            # YouTube's public Atom feed is the primary path. One proven
            # fallback Actor restores the capability; extra paid fallback
            # trials are initiated only by an administrator.
            maximum = min(maximum, 1)
        if manual_selection:
            eligible_by_id = {
                str(row["candidate_id"]): row
                for row in distinct
            }
            requested = set(candidate_ids or ())
            if requested != set(eligible_by_id).intersection(requested):
                raise ActorOpsError(
                    "apify_actor_manual_candidate_stale",
                    "One or more selected Actor candidates are no longer available",
                    status_code=409,
                )
            selected = tuple(
                sorted(
                    (eligible_by_id[value] for value in requested),
                    key=lambda row: (
                        int(row["position"] or 0),
                        str(row["candidate_id"]),
                    ),
                )
            )
            if goal == "upgrade_legacy" and {
                str(row["actor_id"]) for row in selected
            } != active_actor_ids:
                raise ActorOpsError(
                    "apify_actor_legacy_upgrade_actor_set_incomplete",
                    "Legacy upgrade must keep the existing three Actors",
                    status_code=422,
                )
            final_publishers = self.pool_final_publishers(
                goal=goal, target_slot=target_slot,
                selected=list(selected), populated=populated,
            )
            if (
                goal in {"initial_pool", "upgrade_legacy"}
                and len(self.pool_selected_publishers(selected))
                < int(run["min_publishers"])
            ) or len(final_publishers) < int(run["min_publishers"]):
                raise ActorOpsError(
                    "apify_actor_manual_candidate_publishers_insufficient",
                    "Selected Actors do not provide enough publisher diversity",
                    status_code=422,
                )
        elif maximum >= required_successes:
            best: tuple[Any, ...] | None = None
            # Freeze every available fallback covered by this approval. The
            # Worker still stops at the first safe target, but a failed first
            # candidate must not force another paid approval when the same
            # plan already disclosed and capped later candidates.
            for option in combinations(distinct, maximum):
                validated = [
                    row for row in option if bool(row["already_validated"])
                ]
                publisher_count = len(
                    {str(row["publisher"]).casefold() for row in option}
                )
                if goal == "upgrade_legacy" and publisher_count < 2:
                    continue
                score = (
                    -len(validated),
                    sum(int(row["position"] or 0) for row in option),
                    *(str(row["revision_id"]) for row in option),
                )
                if best is None or score < best:
                    best = score
                    selected = option

        source_rows = connection.execute(
            """
            SELECT binding.source_id, binding.generation,
                   binding.target_fingerprint
            FROM apify_source_route_bindings AS binding
            JOIN source_catalog AS source
              ON source.workspace_id = binding.workspace_id
             AND source.id = binding.source_id
            WHERE binding.workspace_id = ? AND binding.route_id = ?
              AND source.enabled = 1
            ORDER BY binding.source_id
            LIMIT ?
            """,
            (
                self.workspace_id,
                str(run["route_id"]),
                POOL_STAGE_MAX_SOURCES + 1,
            ),
        ).fetchall()
        if len(source_rows) > POOL_STAGE_MAX_SOURCES:
            raise ActorOpsError(
                "apify_actor_pool_stage_source_limit",
                "Too many enabled sources are attached to this Actor route",
                status_code=412,
            )
        requested_profiles: dict[str, Mapping[str, Any]] = {}
        if candidate_validation_profiles is not None:
            if not manual_selection:
                raise ActorOpsError(
                    "apify_actor_validation_profile_invalid",
                    "Validation controls require explicit candidate selection",
                    status_code=422,
                )
            for profile in candidate_validation_profiles:
                candidate_id = str(profile.get("candidate_id") or "")
                if not candidate_id or candidate_id in requested_profiles:
                    raise ActorOpsError(
                        "apify_actor_validation_profile_invalid",
                        "Each selected candidate requires one validation profile",
                        status_code=422,
                    )
                requested_profiles[candidate_id] = profile
            if set(requested_profiles) != set(candidate_ids or ()):
                raise ActorOpsError(
                    "apify_actor_validation_profile_invalid",
                    "Validation profiles do not match the selected candidates",
                    status_code=422,
                )

        resolved_profiles: dict[str, dict[str, Any]] = {}
        legacy_upgrade_charge_limit = min(
            VALIDATION_MAX_CHARGE_USD_DEFAULT,
            float(run["per_run_cap_usd"]),
        )
        for row in selected:
            candidate_id = str(row["candidate_id"])
            supports_sample_items = _manifest_supports_sample_items(
                row["manifest_json"]
            )
            requested = requested_profiles.get(candidate_id, {})
            try:
                timeout_seconds = int(
                    requested.get(
                        "timeout_seconds", VALIDATION_TIMEOUT_SECONDS_DEFAULT
                    )
                )
                sample_items = int(requested.get("sample_items", 1))
                max_charge = float(
                    requested.get(
                        "max_charge_usd",
                        min(
                            VALIDATION_MAX_CHARGE_USD_DEFAULT,
                            float(run["per_run_cap_usd"]),
                        ),
                    )
                )
            except (TypeError, ValueError):
                raise ActorOpsError(
                    "apify_actor_validation_profile_invalid",
                    "Validation controls are invalid",
                    status_code=422,
                ) from None
            if (
                isinstance(requested.get("timeout_seconds"), bool)
                or isinstance(requested.get("sample_items"), bool)
                or timeout_seconds < VALIDATION_TIMEOUT_SECONDS_MIN
                or timeout_seconds > VALIDATION_TIMEOUT_SECONDS_MAX
                or (
                    goal == "upgrade_legacy"
                    and timeout_seconds != VALIDATION_TIMEOUT_SECONDS_DEFAULT
                )
                or sample_items not in VALIDATION_SAMPLE_ITEMS_ALLOWED
                or (
                    goal == "upgrade_legacy"
                    and sample_items not in {1, 3}
                )
                or (sample_items != 1 and not supports_sample_items)
                or not math.isfinite(max_charge)
                or max_charge <= 0
                or max_charge > VALIDATION_MAX_CHARGE_USD_LIMIT + 1e-9
                or (
                    goal == "upgrade_legacy"
                    and max_charge > legacy_upgrade_charge_limit + 1e-9
                )
            ):
                raise ActorOpsError(
                    "apify_actor_validation_profile_invalid",
                    "Validation controls exceed their safe bounds",
                    status_code=422,
                )
            expected_options_hash = _validation_options_hash(
                route_id=str(run["route_id"]),
                generation=int(run["generation"]),
                candidate_id=candidate_id,
                revision_id=str(row["revision_id"]),
                build_id=str(row["build_id"]),
                build_number=str(row["build_number"]),
                manifest_hash=str(row["manifest_hash"]),
                supports_sample_items=supports_sample_items,
            )
            supplied_options_hash = requested.get("options_hash")
            if requested_profiles and str(supplied_options_hash or "") != (
                expected_options_hash
            ):
                raise ActorOpsError(
                    "apify_actor_validation_options_stale",
                    "Candidate validation options changed; reload before continuing",
                    status_code=409,
                )
            resolved_profiles[candidate_id] = {
                "timeout_seconds": timeout_seconds,
                "sample_items": sample_items,
                "max_charge_usd": round(max_charge, 6),
                "supports_sample_items": supports_sample_items,
                "options_hash": expected_options_hash,
                "profile_hash": validation_profile_hash(
                    timeout_seconds=timeout_seconds,
                    sample_items=sample_items,
                    max_charge_usd=max_charge,
                ),
            }
        plan_items = [
            {
                "ordinal": index,
                "candidate_id": str(row["candidate_id"]),
                "actor_public_name": _actor_public_name(
                    row["actor_public_name"],
                    row["publisher"],
                    row["actor_id"],
                ),
                "revision_id": str(row["revision_id"]),
                "actor_id": str(row["actor_id"]),
                "publisher": str(row["publisher"]),
                "build_id": str(row["build_id"]),
                "build_number": str(row["build_number"]),
                "manifest_hash": str(row["manifest_hash"]),
                "lifecycle": str(row["lifecycle"]),
                "pricing": _safe_json(row["pricing_json"], {}),
                "already_validated": bool(row["already_validated"]),
                "authorized_cap_usd": resolved_profiles[
                    str(row["candidate_id"])
                ]["max_charge_usd"],
                "validation_profile": resolved_profiles[
                    str(row["candidate_id"])
                ],
            }
            for index, row in enumerate(selected, start=1)
        ]
        from .apify_actor_canary import next_reference_fingerprint

        reference_fingerprints = {
            str(item["revision_id"]): next_reference_fingerprint(
                self.store,
                workspace_id=self.workspace_id,
                platform=str(run["platform"]),
                route_id=str(run["route_id"]),
                revision_id=str(item["revision_id"]),
            )
            for item in plan_items
        }

        def require_meaningful_retry(
            *,
            item: Mapping[str, Any],
            target_fingerprint: str,
            kind: Literal["route_reference", "source_canary"],
        ) -> None:
            """Reject paid retries whose changed field cannot address the failure."""

            previous = connection.execute(
                """
                SELECT semantic_outcome, validation_timeout_seconds,
                       validation_sample_items, failure_fingerprint
                FROM apify_actor_validations
                WHERE workspace_id = ? AND route_id = ?
                  AND revision_id = ? AND target_fingerprint = ?
                  AND kind = ? AND status = 'failed'
                ORDER BY completed_at DESC, created_at DESC,
                         validation_id DESC
                LIMIT 1
                """,
                (
                    self.workspace_id,
                    str(run["route_id"]),
                    str(item["revision_id"]),
                    target_fingerprint,
                    kind,
                ),
            ).fetchone()
            if previous is None:
                return
            semantic = str(previous["semantic_outcome"] or "")
            profile = item["validation_profile"]
            if semantic in {
                "apify_run_status_unavailable",
                "apify_actor_run_status_unavailable",
                "apify_run_reconcile_required",
            }:
                raise ActorOpsError(
                    "apify_actor_validation_reconcile_required",
                    "The existing Actor Run must be reconciled without another start",
                    status_code=409,
                )
            meaningful = True
            if goal == "upgrade_legacy":
                meaningful = (
                    semantic
                    in {"suspicious_empty", "apify_actor_suspicious_empty"}
                    and bool(profile["supports_sample_items"])
                    and int(previous["validation_sample_items"] or 1) < 3
                    and int(profile["sample_items"]) == 3
                )
            elif semantic in {
                "apify_actor_run_timed_out",
                "apify_actor_canary_timeout",
            }:
                meaningful = int(profile["timeout_seconds"]) > int(
                    previous["validation_timeout_seconds"] or 300
                )
            elif semantic in {"suspicious_empty", "apify_actor_suspicious_empty"}:
                meaningful = bool(profile["supports_sample_items"]) and int(
                    profile["sample_items"]
                ) > int(previous["validation_sample_items"] or 1)
            elif semantic in {
                "apify_actor_contract_mismatch",
                "apify_actor_identity_mismatch",
                "apify_actor_target_identity_mismatch",
                "apify_actor_metadata_only",
                "apify_actor_placeholder",
                "apify_actor_revision_output_incompatible",
            }:
                meaningful = False
            if not meaningful:
                raise ActorOpsError(
                    "apify_actor_validation_profile_unchanged",
                    "The changed validation setting cannot address the prior failure",
                    status_code=409,
                )

        for item in plan_items:
            if bool(item["already_validated"]):
                continue
            profile = dict(item["validation_profile"])
            require_meaningful_retry(
                item=item,
                target_fingerprint=reference_fingerprints[
                    str(item["revision_id"])
                ],
                kind="route_reference",
            )
            fingerprint = validation_failure_fingerprint(
                route_id=str(run["route_id"]),
                candidate_id=str(item["candidate_id"]),
                revision_id=str(item["revision_id"]),
                build_id=str(item["build_id"]),
                build_number=str(item["build_number"]),
                manifest_hash=str(item["manifest_hash"]),
                target_fingerprint=reference_fingerprints[str(item["revision_id"])],
                kind="route_reference",
                profile_hash=str(profile["profile_hash"]),
            )
            repeated = connection.execute(
                """
                SELECT 1 FROM apify_actor_validations
                WHERE workspace_id = ? AND failure_fingerprint = ?
                  AND status = 'failed'
                LIMIT 1
                """,
                (self.workspace_id, fingerprint),
            ).fetchone()
            if repeated is not None:
                raise ActorOpsError(
                    "apify_actor_validation_profile_unchanged",
                    "The same Actor already failed with these validation settings",
                    status_code=409,
                )
        route_cap = round(sum(float(item["authorized_cap_usd"]) for item in plan_items), 6)
        staged_revision_ids = [str(row["revision_id"]) for row in selected]
        if goal == "complete_third":
            base_revision_ids = [
                str(active_slots["primary"]["revision_id"]),
                str(active_slots["backup_1"]["revision_id"]),
            ]
            possible_target_sets = [
                [*base_revision_ids, revision_id]
                for revision_id in staged_revision_ids
            ]
        elif goal in {"add_slot", "replace_slot"}:
            if target_slot not in SLOT_NAMES:
                raise ActorOpsError(
                    "apify_actor_pool_target_slot_invalid",
                    "A safe target slot is required for this operation",
                    status_code=422,
                )
            possible_target_sets = [
                [
                    *(str(active_slots[name]["revision_id"])
                      for name in SLOT_NAMES
                      if name != target_slot and active_slots[name]["revision_id"]),
                    revision_id,
                ]
                for revision_id in staged_revision_ids
            ]
        elif goal == "upgrade_legacy":
            possible_target_sets = [staged_revision_ids]
        elif manual_selection:
            possible_target_sets = [staged_revision_ids]
        else:
            possible_target_sets = [
                [str(primary["revision_id"]), str(backup["revision_id"])]
                for primary, backup in combinations(selected, 2)
                if str(primary["actor_id"]) != str(backup["actor_id"])
                and str(primary["publisher"]).casefold()
                != str(backup["publisher"]).casefold()
            ]
        source_validation_count = 0
        source_cap = 0.0
        item_by_revision = {
            str(item["revision_id"]): item for item in plan_items
        }
        for source in source_rows:
            missing_by_target: list[int] = []
            cap_by_target: list[float] = []
            for target_revision_ids in possible_target_sets:
                missing = 0
                missing_cap = 0.0
                for revision_id in target_revision_ids:
                    reusable = connection.execute(
                        """
                        SELECT 1 FROM apify_actor_validations
                        WHERE workspace_id = ? AND route_id = ?
                          AND source_id = ? AND revision_id = ?
                          AND kind = 'source_canary'
                          AND status = 'succeeded'
                          AND cost_final = 1
                          AND semantic_outcome IN (
                              'valid_nonempty', 'valid_empty'
                          )
                          AND target_fingerprint = ?
                        LIMIT 1
                        """,
                        (
                            self.workspace_id,
                            str(run["route_id"]),
                            str(source["source_id"]),
                            revision_id,
                            str(source["target_fingerprint"]),
                        ),
                    ).fetchone()
                    if reusable is None:
                        missing += 1
                        item = item_by_revision.get(revision_id)
                        item_cap = float(
                            item["authorized_cap_usd"]
                            if item is not None
                            else VALIDATION_MAX_CHARGE_USD_DEFAULT
                        )
                        missing_cap += item_cap
                        if item is not None:
                            require_meaningful_retry(
                                item=item,
                                target_fingerprint=str(
                                    source["target_fingerprint"]
                                ),
                                kind="source_canary",
                            )
                            fingerprint = validation_failure_fingerprint(
                                route_id=str(run["route_id"]),
                                candidate_id=str(item["candidate_id"]),
                                revision_id=revision_id,
                                build_id=str(item["build_id"]),
                                build_number=str(item["build_number"]),
                                manifest_hash=str(item["manifest_hash"]),
                                target_fingerprint=str(source["target_fingerprint"]),
                                kind="source_canary",
                                profile_hash=str(
                                    item["validation_profile"]["profile_hash"]
                                ),
                            )
                            repeated = connection.execute(
                                """
                                SELECT 1 FROM apify_actor_validations
                                WHERE workspace_id = ?
                                  AND failure_fingerprint = ?
                                  AND status = 'failed'
                                LIMIT 1
                                """,
                                (self.workspace_id, fingerprint),
                            ).fetchone()
                            if repeated is not None:
                                raise ActorOpsError(
                                    "apify_actor_validation_profile_unchanged",
                                    "The same Actor and source already failed with these settings",
                                    status_code=409,
                                )
                missing_by_target.append(missing)
                cap_by_target.append(missing_cap)
            source_validation_count += max(missing_by_target, default=0)
            source_cap += max(cap_by_target, default=0.0)
        source_cap = round(source_cap, 6)
        authorized_total = round(route_cap + source_cap, 6)
        if authorized_total <= 0:
            authorized_total = route_cap
        if authorized_total > POOL_STAGE_MAX_TOTAL_USD + 1e-9:
            raise ActorOpsError(
                "apify_actor_pool_stage_budget_invalid",
                "Staged Actor validation exceeds its hard total cap",
                status_code=412,
            )
        if max_total_charge_usd is not None:
            approved_total = _bounded_cost(
                max_total_charge_usd,
                maximum=POOL_STAGE_MAX_TOTAL_USD,
            )
            if abs(approved_total - authorized_total) > 1e-9:
                raise ActorOpsError(
                    "apify_actor_canary_plan_conflict",
                    "Staged validation cap changed; reload before approving spend",
                    status_code=409,
                )
        base_slots = {
            name: str(active_slots[name]["revision_id"] or "")
            for name in SLOT_NAMES
        }
        source_snapshot = [
            {
                "source_id": str(row["source_id"]),
                "binding_generation": int(row["generation"]),
                "target_fingerprint": str(row["target_fingerprint"]),
            }
            for row in source_rows
        ]
        plan_schema_version = 3 if manual_selection else 2
        plan_payload = {
            "schema_version": plan_schema_version,
            "goal": goal,
            "operation_slot": target_slot,
            "selection_mode": "manual" if manual_selection else "server",
            "target_slot_count": resolved_target_slot_count,
            "run_id": str(run["run_id"]),
            "route_id": str(run["route_id"]),
            "generation": int(run["generation"]),
            "base_pool_hash": revision_set_hash(base_slots),
            "base_slots": base_slots,
            "items": [
                {
                    key: item[key]
                    for key in (
                        "ordinal", "candidate_id", "revision_id",
                        "actor_id", "publisher",
                        "build_id", "build_number", "manifest_hash",
                        "already_validated", "authorized_cap_usd",
                        "validation_profile",
                    )
                }
                for item in plan_items
            ],
            "sources": source_snapshot,
            "required_success_count": required_successes,
            "required_source_slots": required_source_slots,
            "max_total_charge_usd": authorized_total,
        }
        plan_hash = hashlib.sha256(
            json.dumps(
                plan_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        ready = len(selected) >= required_successes and (
            goal != "upgrade_legacy"
            or len({str(row["publisher"]).casefold() for row in selected}) >= 2
        )
        return {
            "schema_version": plan_schema_version,
            "goal": goal,
            "operation_slot": target_slot,
            "selection_mode": "manual" if manual_selection else "server",
            "target_slot_count": resolved_target_slot_count,
            "run_id": str(run["run_id"]),
            "route_id": str(run["route_id"]),
            "route_key": str(run["route_key"]),
            "platform": str(run["platform"]),
            "target_type": str(run["target_type"]),
            "capability": str(run["capability"]),
            "mode": str(run["mode"]),
            "generation": int(run["generation"]),
            "status": "ready" if ready else "insufficient_candidates",
            "ready": ready,
            "activation_ready": False,
            "plan_hash": plan_hash,
            "base_pool_hash": revision_set_hash(base_slots),
            "required_success_count": required_successes,
            "max_candidates": int(max_candidates),
            "max_total_charge_usd": authorized_total,
            "route_validation_cap_usd": route_cap,
            "source_validation_cap_usd": source_cap,
            "source_count": len(source_rows),
            "source_validation_count": source_validation_count,
            "per_candidate_cap_usd": round(
                max(
                    (float(item["authorized_cap_usd"]) for item in plan_items),
                    default=VALIDATION_MAX_CHARGE_USD_DEFAULT,
                ),
                6,
            ),
            "successful_actor_count": sum(
                1 for row in selected if bool(row["already_validated"])
            ),
            "successful_publisher_count": len(
                {
                    str(row["publisher"]).casefold()
                    for row in selected
                    if bool(row["already_validated"])
                }
            ),
            "attempts_used": 0,
            "attempts_remaining": int(max_candidates),
            "budget_remaining_usd": round(
                POOL_STAGE_MAX_TOTAL_USD - authorized_total, 6
            ),
            "items": plan_items,
            "_eligible_candidate_count": len(distinct),
            "_source_snapshot": source_snapshot,
            "_reference_fingerprints": reference_fingerprints,
        }

    def _get_initial_canary_plan(
        self,
        run_id: str,
        *,
        max_candidates: int = BATCH_CANARY_MAX_CANDIDATES,
        max_total_charge_usd: float = BATCH_CANARY_MAX_TOTAL_USD,
    ) -> dict[str, Any]:
        """Return a deterministic server-selected paid validation plan."""

        if isinstance(max_candidates, bool) or not 1 <= int(max_candidates) <= 3:
            raise ActorOpsError(
                "apify_actor_canary_batch_limit_invalid",
                "A Canary batch may contain one to three candidates",
                status_code=422,
            )
        total_cap = _bounded_cost(
            max_total_charge_usd,
            maximum=BATCH_CANARY_MAX_TOTAL_USD,
        )
        connection = self.store.connect()
        run = connection.execute(
            """
            SELECT run.*, profile.route_key, profile.platform,
                   profile.target_type, profile.capability,
                   profile.mode, profile.generation,
                   profile.per_run_cap_usd, profile.min_publishers,
                   profile.min_runtime_healthy
            FROM apify_actor_discovery_runs AS run
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = run.workspace_id
             AND profile.route_id = run.route_id
            WHERE run.workspace_id = ? AND run.run_id = ?
            """,
            (self.workspace_id, run_id),
        ).fetchone()
        if run is None:
            raise ActorOpsError(
                "apify_actor_discovery_run_not_found",
                "Actor discovery run was not found",
                status_code=404,
            )
        if str(run["stage"]) not in {
            "awaiting_canary_approval",
            "canary_exhausted",
            "candidate_shortfall",
            "activation_ready",
        }:
            raise ActorOpsError(
                "apify_actor_discovery_not_awaiting_approval",
                "Actor discovery run is not ready for a paid validation plan",
                status_code=409,
            )
        required_actors = int(run["min_runtime_healthy"])
        required_publishers = int(run["min_publishers"])

        successful = connection.execute(
            """
            SELECT DISTINCT revision.revision_id, revision.actor_id,
                   lower(revision.publisher) AS publisher
            FROM apify_actor_validations AS validation
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = validation.workspace_id
             AND revision.revision_id = validation.revision_id
            WHERE validation.workspace_id = ?
              AND validation.route_id = ?
              AND validation.kind = 'route_reference'
              AND validation.status = 'succeeded'
              AND validation.semantic_outcome IN (
                  'valid_nonempty', 'valid_empty'
              )
              AND revision.lifecycle IN ('probationary', 'certified')
              AND revision.build_id IS NOT NULL
              AND revision.build_number IS NOT NULL
              AND revision.manifest_hash IS NOT NULL
            ORDER BY revision.revision_id
            """,
            (self.workspace_id, str(run["route_id"])),
        ).fetchall()
        proven_actors = {str(row["actor_id"]) for row in successful}
        proven_publishers = {str(row["publisher"]) for row in successful}
        usage = connection.execute(
            """
            SELECT COALESCE(SUM(validation.counts_toward_canary), 0)
                       AS attempts,
                   COALESCE(SUM(CASE
                       WHEN validation.cost_final = 1
                       THEN COALESCE(validation.cost_usd, 0)
                       WHEN validation.status IN ('queued', 'running')
                       THEN COALESCE(validation.approved_max_cost_usd, 0)
                       ELSE 0 END), 0) AS occupied_usd
            FROM apify_actor_validations AS validation
            WHERE validation.workspace_id = ?
              AND validation.route_id = ?
              AND validation.kind = 'route_reference'
            """,
            (self.workspace_id, str(run["route_id"])),
        ).fetchone()
        attempts_used = int(usage["attempts"] or 0)
        attempts_remaining = max(
            ROUTE_CANARY_ATTEMPT_LIMIT - attempts_used,
            0,
        )
        budget_remaining = max(
            min(float(run["budget_usd"]), ROUTE_CANARY_BUDGET_USD)
            - float(usage["occupied_usd"] or 0),
            0.0,
        )
        per_candidate_cap = min(float(run["per_run_cap_usd"]), 0.02)
        authorization_budget = min(total_cap, budget_remaining)
        affordable_candidates = int(
            (authorization_budget + 1e-9) // per_candidate_cap
        )

        raw_candidates = connection.execute(
            """
            SELECT revision.revision_id, revision.actor_id,
                   revision.publisher, revision.build_id,
                   revision.build_number, revision.manifest_hash,
                   revision.pricing_json, revision.lifecycle,
                   candidate.position, revision.created_at
            FROM apify_actor_adapter_revisions AS revision
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE revision.workspace_id = ?
              AND candidate.route_key = ?
              AND revision.lifecycle IN ('static_valid', 'probationary')
              AND revision.build_id IS NOT NULL
              AND revision.build_number IS NOT NULL
              AND revision.manifest_hash IS NOT NULL
              AND NOT (
                  candidate.state = 'disabled'
                  AND COALESCE(candidate.last_error_code, '') =
                      'apify_actor_revision_unavailable'
              )
              AND EXISTS (
                  SELECT 1
                  FROM apify_actor_discovery_run_revisions AS association
                  JOIN apify_actor_discovery_runs AS source_run
                    ON source_run.workspace_id = association.workspace_id
                   AND source_run.run_id = association.run_id
                  WHERE association.workspace_id = revision.workspace_id
                    AND association.revision_id = revision.revision_id
                    AND source_run.route_id = ?
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM apify_actor_validations AS attempted
                  WHERE attempted.workspace_id = revision.workspace_id
                    AND attempted.route_id = ?
                    AND attempted.revision_id = revision.revision_id
                    AND attempted.kind = 'route_reference'
                    AND attempted.counts_toward_canary = 1
              )
            ORDER BY candidate.position, revision.created_at,
                     revision.revision_id
            """,
            (
                self.workspace_id,
                str(run["route_key"]),
                str(run["route_id"]),
                str(run["route_id"]),
            ),
        ).fetchall()
        candidates: list[sqlite3.Row] = []
        seen_actors = set(proven_actors)
        for row in raw_candidates:
            actor_id = str(row["actor_id"])
            if actor_id in seen_actors:
                continue
            if self._revision_canary_block_reason(
                connection,
                str(run["route_id"]),
                str(row["revision_id"]),
            ) is not None:
                continue
            active = connection.execute(
                """
                SELECT 1 FROM apify_actor_validations
                WHERE workspace_id = ? AND revision_id = ?
                  AND kind = 'route_reference'
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (self.workspace_id, str(row["revision_id"])),
            ).fetchone()
            if active is not None:
                continue
            seen_actors.add(actor_id)
            candidates.append(row)

        selected: tuple[sqlite3.Row, ...] = ()
        maximum = min(
            int(max_candidates),
            len(candidates),
            attempts_remaining,
            affordable_candidates,
        )
        prefer_minimum = bool(proven_actors) or required_actors == 1
        best_score: tuple[Any, ...] | None = None
        for size in range(1, maximum + 1):
            for option in combinations(candidates, size):
                actors = proven_actors | {str(row["actor_id"]) for row in option}
                publishers = proven_publishers | {
                    str(row["publisher"]).casefold() for row in option
                }
                reaches_minimum = (
                    len(actors) >= required_actors
                    and len(publishers) >= required_publishers
                )
                score: tuple[Any, ...] = (
                    0 if reaches_minimum else 1,
                    size if reaches_minimum and prefer_minimum else -size,
                    sum(int(row["position"] or 0) for row in option),
                    *(str(row["revision_id"]) for row in option),
                )
                if best_score is None or score < best_score:
                    best_score = score
                    selected = option

        combined_actors = proven_actors | {
            str(row["actor_id"]) for row in selected
        }
        combined_publishers = proven_publishers | {
            str(row["publisher"]).casefold() for row in selected
        }
        activation_ready = (
            len(proven_actors) >= required_actors
            and len(proven_publishers) >= required_publishers
        )
        reachable = activation_ready or (
            len(combined_actors) >= required_actors
            and len(combined_publishers) >= required_publishers
        )
        plan_items = [
            {
                "ordinal": index,
                "revision_id": str(row["revision_id"]),
                "actor_id": str(row["actor_id"]),
                "publisher": str(row["publisher"]),
                "build_id": str(row["build_id"]),
                "build_number": str(row["build_number"]),
                "manifest_hash": str(row["manifest_hash"]),
                "lifecycle": str(row["lifecycle"]),
                "pricing": _safe_json(row["pricing_json"], {}),
                "authorized_cap_usd": round(per_candidate_cap, 6),
            }
            for index, row in enumerate(selected, start=1)
        ]
        authorized_total = round(
            sum(float(item["authorized_cap_usd"]) for item in plan_items),
            6,
        )
        plan_payload = {
            "run_id": str(run["run_id"]),
            "route_id": str(run["route_id"]),
            "generation": int(run["generation"]),
            "target_slot_count": required_actors,
            "required_success_count": required_actors,
            "max_candidates": int(max_candidates),
            "max_total_charge_usd": authorized_total,
            "items": [
                {
                    key: item[key]
                    for key in (
                        "ordinal",
                        "revision_id",
                        "actor_id",
                        "publisher",
                        "build_id",
                        "build_number",
                        "manifest_hash",
                        "authorized_cap_usd",
                    )
                }
                for item in plan_items
            ],
        }
        plan_hash = hashlib.sha256(
            json.dumps(
                plan_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schema_version": 1,
            "run_id": str(run["run_id"]),
            "route_id": str(run["route_id"]),
            "route_key": str(run["route_key"]),
            "platform": str(run["platform"]),
            "target_type": str(run["target_type"]),
            "capability": str(run["capability"]),
            "mode": str(run["mode"]),
            "generation": int(run["generation"]),
            "target_slot_count": required_actors,
            "required_success_count": required_actors,
            "status": (
                "activation_ready"
                if activation_ready
                else "ready"
                if reachable and plan_items
                else "insufficient_candidates"
            ),
            "ready": bool(reachable and plan_items and not activation_ready),
            "activation_ready": activation_ready,
            "plan_hash": plan_hash,
            "max_candidates": int(max_candidates),
            "max_total_charge_usd": authorized_total,
            "per_candidate_cap_usd": round(per_candidate_cap, 6),
            "successful_actor_count": len(proven_actors),
            "successful_publisher_count": len(proven_publishers),
            "attempts_used": attempts_used,
            "attempts_remaining": attempts_remaining,
            "budget_remaining_usd": round(budget_remaining, 6),
            "items": plan_items,
        }

    def _create_pool_stage_canary_batch(
        self,
        run_id: str,
        *,
        goal: Literal[
            "initial_pool", "complete_third", "upgrade_legacy",
            "compatibility_single", "add_slot", "replace_slot",
        ],
        expected_generation: int,
        expected_plan_hash: str,
        approval_id: str,
        confirmation: str,
        max_candidates: int,
        max_total_charge_usd: float,
        created_by_user_id: str,
        reference_fingerprints: Mapping[str, str],
        candidate_ids: tuple[str, ...] | None,
        candidate_validation_profiles: Sequence[Mapping[str, Any]] | None,
        target_slot_count: int | None,
        target_slot: str | None,
    ) -> dict[str, Any]:
        if confirmation != BATCH_CANARY_CONFIRMATION:
            raise ActorOpsError(
                "apify_actor_canary_batch_confirmation_required",
                "Paid Canary batch requires the exact confirmation phrase",
                status_code=422,
            )
        if not _HEX_64_RE.fullmatch(str(expected_plan_hash)):
            raise ActorOpsError(
                "apify_actor_canary_plan_invalid",
                "Canary plan hash is invalid",
                status_code=422,
            )
        approval_hash = _approval_key_hash(approval_id)
        plan = self.get_canary_plan(
            run_id,
            goal=goal,
            max_candidates=max_candidates,
            max_total_charge_usd=max_total_charge_usd,
            candidate_ids=candidate_ids,
            candidate_validation_profiles=candidate_validation_profiles,
            target_slot_count=target_slot_count,
            target_slot=target_slot,
        )
        with self._write() as connection:
            replay = connection.execute(
                """
                SELECT batch.batch_id, batch.approved_generation,
                       batch.plan_hash, batch.max_candidates, batch.goal,
                       batch.pool_stage_id, batch.operation_slot,
                       stage.max_total_charge_usd, stage.target_slot_count,
                       stage.selection_mode, stage.operation_slot AS stage_operation_slot
                FROM apify_actor_canary_batches AS batch
                LEFT JOIN apify_actor_pool_stages AS stage
                  ON stage.workspace_id = batch.workspace_id
                 AND stage.stage_id = batch.pool_stage_id
                WHERE batch.workspace_id = ?
                  AND batch.approval_key_hash = ?
                """,
                (self.workspace_id, approval_hash),
            ).fetchone()
            if replay is not None:
                if int(replay["approved_generation"]) != int(expected_generation) or not self.pool_stage_replay_matches(
                    replay, goal=goal, target_slot=target_slot,
                    expected_plan_hash=expected_plan_hash,
                    max_candidates=max_candidates, plan=plan,
                    max_total_charge_usd=max_total_charge_usd,
                ):
                    raise ActorOpsError(
                        "apify_actor_approval_id_conflict",
                        "Paid approval id was already used for another action",
                        status_code=409,
                    )
                result = self.get_canary_batch(str(replay["batch_id"]))
                result["_approval_replayed"] = True
                return result
            if int(plan["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            if str(plan["plan_hash"]) != str(expected_plan_hash):
                raise ActorOpsError(
                    "apify_actor_canary_plan_conflict",
                    "Canary plan changed; reload before approving spend",
                    status_code=409,
                )
            if not bool(plan["ready"]):
                raise ActorOpsError(
                    "apify_actor_canary_batch_not_ready",
                    "The staged candidates cannot satisfy this Actor pool goal",
                    status_code=412,
                )
            revision_ids = {str(item["revision_id"]) for item in plan["items"]}
            if set(reference_fingerprints) != revision_ids or any(
                not _HEX_64_RE.fullmatch(str(value))
                for value in reference_fingerprints.values()
            ):
                raise ActorOpsError(
                    "apify_actor_reference_fingerprint_required",
                    "Route Canary references do not match the frozen plan",
                    status_code=422,
                )
            active = connection.execute(
                """
                SELECT stage_id, status
                FROM apify_actor_pool_stages
                WHERE workspace_id = ? AND route_id = ?
                  AND status NOT IN ('applied', 'stale', 'failed', 'cancelled')
                LIMIT 1
                """,
                (self.workspace_id, str(plan["route_id"])),
            ).fetchone()
            if active is not None:
                if str(active["status"]) != "replan_required":
                    raise ActorOpsError(
                        "apify_actor_pool_stage_active",
                        "A staged Actor pool workflow is already active",
                        status_code=409,
                    )
                connection.execute(
                    """
                    UPDATE apify_actor_pool_stages
                    SET status = 'stale', updated_at = ?
                    WHERE workspace_id = ? AND stage_id = ?
                      AND status = 'replan_required'
                    """,
                    (self._now_iso(), self.workspace_id, str(active["stage_id"])),
                )
            batch_id = f"apify-canary-batch-{uuid.uuid4().hex}"
            stage_id = f"apify-pool-stage-{uuid.uuid4().hex}"
            now = self._now_iso()
            per_cap = float(plan["per_candidate_cap_usd"])
            route_cap = float(plan["route_validation_cap_usd"])
            connection.execute(
                """
                INSERT INTO apify_actor_canary_batches (
                    batch_id, workspace_id, route_id, discovery_run_id,
                    approval_key_hash, approved_generation, plan_hash,
                    max_candidates, max_total_charge_usd,
                    per_candidate_cap_usd, goal, operation_slot, pool_stage_id,
                    status, planned_count, success_count, publisher_count,
                    actual_cost_usd, cost_final, stop_reason,
                    created_by_user_id, created_at, started_at,
                    completed_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?,
                    0, 0, NULL, 0, NULL, ?, ?, NULL, NULL, ?
                )
                """,
                (
                    batch_id,
                    self.workspace_id,
                    str(plan["route_id"]),
                    run_id,
                    approval_hash,
                    expected_generation,
                    expected_plan_hash,
                    int(max_candidates),
                    route_cap,
                    per_cap,
                    goal,
                    plan.get("operation_slot"),
                    stage_id,
                    len(plan["items"]),
                    created_by_user_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO apify_actor_pool_stages (
                    stage_id, workspace_id, route_id, discovery_run_id,
                    initial_batch_id, goal, operation_slot, target_slot_count,
                    selection_mode, base_generation,
                    base_pool_hash, plan_hash, approval_key_hash,
                    max_total_charge_usd, route_validation_cap_usd,
                    status, created_by_user_id, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued',
                    ?, ?, ?
                )
                """,
                (
                    stage_id,
                    self.workspace_id,
                    str(plan["route_id"]),
                    run_id,
                    batch_id,
                    goal,
                    plan.get("operation_slot"),
                    int(plan["target_slot_count"]),
                    str(plan["selection_mode"]),
                    expected_generation,
                    str(plan["base_pool_hash"]),
                    expected_plan_hash,
                    approval_hash,
                    float(plan["max_total_charge_usd"]),
                    route_cap,
                    created_by_user_id,
                    now,
                    now,
                ),
            )
            for source in plan.get("_source_snapshot", []):
                connection.execute(
                    """
                    INSERT INTO apify_actor_pool_stage_sources (
                        workspace_id, stage_id, source_id,
                        binding_generation, target_fingerprint,
                        required_count, passed_count, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 'snapshotted', ?, ?)
                    """,
                    (
                        self.workspace_id,
                        stage_id,
                        str(source["source_id"]),
                        int(source["binding_generation"]),
                        str(source["target_fingerprint"]),
                        int(plan["target_slot_count"]),
                        now,
                        now,
                    ),
                )
            for item in plan["items"]:
                revision_id = str(item["revision_id"])
                ordinal = int(item["ordinal"])
                evidence_reused = bool(item.get("already_validated"))
                item_cap = float(item["authorized_cap_usd"])
                validation_profile = dict(item["validation_profile"])
                validation_id = f"apify-validation-{uuid.uuid4().hex}"
                validation_approval_hash = hashlib.sha256(
                    f"{approval_hash}:{ordinal}:{revision_id}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO apify_actor_validations (
                        validation_id, workspace_id, route_id, source_id,
                        revision_id, attempt_id, discovery_run_id, kind,
                        approval_key_hash, approved_generation,
                        approved_max_cost_usd, status, semantic_outcome,
                        cost_usd, cost_final, counts_toward_canary,
                        target_fingerprint, validation_timeout_seconds,
                        validation_sample_items, validation_profile_hash,
                        created_at, completed_at
                    ) VALUES (
                        ?, ?, ?, NULL, ?, NULL, ?, 'route_reference',
                        ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        validation_id,
                        self.workspace_id,
                        str(plan["route_id"]),
                        revision_id,
                        run_id,
                        validation_approval_hash,
                        expected_generation,
                        item_cap,
                        "succeeded" if evidence_reused else "queued",
                        "evidence_reused" if evidence_reused else None,
                        0.0 if evidence_reused else None,
                        int(evidence_reused),
                        str(reference_fingerprints[revision_id]),
                        int(validation_profile["timeout_seconds"]),
                        int(validation_profile["sample_items"]),
                        str(validation_profile["profile_hash"]),
                        now,
                        now if evidence_reused else None,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO apify_actor_pool_stage_candidate_settings (
                        workspace_id, stage_id, candidate_id, revision_id,
                        timeout_seconds, sample_items, max_charge_usd,
                        supports_sample_items, profile_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.workspace_id,
                        stage_id,
                        str(item["candidate_id"]),
                        revision_id,
                        int(validation_profile["timeout_seconds"]),
                        int(validation_profile["sample_items"]),
                        item_cap,
                        int(bool(validation_profile["supports_sample_items"])),
                        str(validation_profile["profile_hash"]),
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO apify_actor_canary_batch_items (
                        workspace_id, batch_id, ordinal, revision_id,
                        validation_id, status, semantic_outcome,
                        authorized_cap_usd, actual_cost_usd, cost_final,
                        preflight_checked_at, started_at, completed_at,
                        updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        NULL, ?, ?, ?
                    )
                    """,
                    (
                        self.workspace_id,
                        batch_id,
                        ordinal,
                        revision_id,
                        validation_id,
                        "succeeded" if evidence_reused else "planned",
                        "evidence_reused" if evidence_reused else None,
                        item_cap,
                        0.0 if evidence_reused else None,
                        int(evidence_reused),
                        now if evidence_reused else None,
                        now if evidence_reused else None,
                        now,
                    ),
                )
        result = self.get_canary_batch(batch_id)
        result["_approval_replayed"] = False
        return result

    def _create_initial_canary_batch(
        self,
        run_id: str,
        *,
        expected_generation: int,
        expected_plan_hash: str,
        approval_id: str,
        confirmation: str,
        max_candidates: int,
        max_total_charge_usd: float,
        created_by_user_id: str,
        reference_fingerprints: Mapping[str, str],
    ) -> dict[str, Any]:
        if confirmation != BATCH_CANARY_CONFIRMATION:
            raise ActorOpsError(
                "apify_actor_canary_batch_confirmation_required",
                "Paid Canary batch requires the exact confirmation phrase",
                status_code=422,
            )
        if not _HEX_64_RE.fullmatch(str(expected_plan_hash)):
            raise ActorOpsError(
                "apify_actor_canary_plan_invalid",
                "Canary plan hash is invalid",
                status_code=422,
            )
        approval_hash = _approval_key_hash(approval_id)
        plan = self.get_canary_plan(
            run_id,
            max_candidates=max_candidates,
            max_total_charge_usd=max_total_charge_usd,
        )
        with self._write() as connection:
            replay = connection.execute(
                """
                SELECT batch_id, approved_generation, plan_hash,
                       max_candidates, max_total_charge_usd
                FROM apify_actor_canary_batches
                WHERE workspace_id = ? AND approval_key_hash = ?
                """,
                (self.workspace_id, approval_hash),
            ).fetchone()
            if replay is not None:
                if (
                    int(replay["approved_generation"]) != int(expected_generation)
                    or str(replay["plan_hash"]) != str(expected_plan_hash)
                    or int(replay["max_candidates"]) != int(max_candidates)
                    or abs(
                        float(replay["max_total_charge_usd"])
                        - float(max_total_charge_usd)
                    )
                    > 1e-9
                ):
                    raise ActorOpsError(
                        "apify_actor_approval_id_conflict",
                        "Paid approval id was already used for another action",
                        status_code=409,
                    )
                result = self.get_canary_batch(str(replay["batch_id"]))
                result["_approval_replayed"] = True
                return result
            if int(plan["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            if str(plan["plan_hash"]) != str(expected_plan_hash):
                raise ActorOpsError(
                    "apify_actor_canary_plan_conflict",
                    "Canary plan changed; reload before approving spend",
                    status_code=409,
                )
            if not bool(plan["ready"]):
                raise ActorOpsError(
                    "apify_actor_canary_batch_not_ready",
                    "The current candidates cannot satisfy the Route minimum",
                    status_code=412,
                )
            revision_ids = {
                str(item["revision_id"]) for item in plan["items"]
            }
            if set(reference_fingerprints) != revision_ids or any(
                not _HEX_64_RE.fullmatch(str(value))
                for value in reference_fingerprints.values()
            ):
                raise ActorOpsError(
                    "apify_actor_reference_fingerprint_required",
                    "Route Canary references do not match the frozen plan",
                    status_code=422,
                )
            active = connection.execute(
                """
                SELECT batch_id
                FROM apify_actor_canary_batches
                WHERE workspace_id = ? AND route_id = ?
                  AND status IN ('queued', 'preflighting', 'running')
                LIMIT 1
                """,
                (self.workspace_id, str(plan["route_id"])),
            ).fetchone()
            if active is not None:
                raise ActorOpsError(
                    "apify_actor_canary_batch_active",
                    "A paid Canary batch is already queued or running",
                    status_code=409,
                )
            usage = connection.execute(
                """
                SELECT run.budget_usd,
                       COALESCE(SUM(CASE
                           WHEN validation.cost_final = 1
                           THEN COALESCE(validation.cost_usd, 0)
                           WHEN validation.status IN ('queued', 'running')
                           THEN validation.approved_max_cost_usd
                           ELSE 0 END), 0) AS occupied_usd
                FROM apify_actor_discovery_runs AS run
                LEFT JOIN apify_actor_validations AS validation
                  ON validation.workspace_id = run.workspace_id
                 AND validation.route_id = run.route_id
                 AND validation.kind = 'route_reference'
                WHERE run.workspace_id = ? AND run.run_id = ?
                GROUP BY run.run_id
                """,
                (self.workspace_id, run_id),
            ).fetchone()
            occupied_cap = sum(
                float(item["authorized_cap_usd"])
                for item in plan["items"]
            )
            if (
                usage is None
                or float(usage["occupied_usd"] or 0)
                + occupied_cap
                > min(float(usage["budget_usd"]), ROUTE_CANARY_BUDGET_USD)
                + 1e-9
            ):
                raise ActorOpsError(
                    "apify_actor_canary_budget_exhausted",
                    "Route certification Canary budget is exhausted",
                    status_code=412,
                )
            batch_id = f"apify-canary-batch-{uuid.uuid4().hex}"
            now = self._now_iso()
            per_cap = float(plan["per_candidate_cap_usd"])
            connection.execute(
                """
                INSERT INTO apify_actor_canary_batches (
                    batch_id, workspace_id, route_id, discovery_run_id,
                    approval_key_hash, approved_generation, plan_hash,
                    max_candidates, max_total_charge_usd,
                    per_candidate_cap_usd, status, planned_count,
                    success_count, publisher_count, actual_cost_usd,
                    cost_final, stop_reason, created_by_user_id,
                    created_at, started_at, completed_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?,
                    0, 0, NULL, 0, NULL, ?, ?, NULL, NULL, ?
                )
                """,
                (
                    batch_id,
                    self.workspace_id,
                    str(plan["route_id"]),
                    run_id,
                    approval_hash,
                    expected_generation,
                    expected_plan_hash,
                    int(max_candidates),
                    float(plan["max_total_charge_usd"]),
                    per_cap,
                    len(plan["items"]),
                    created_by_user_id,
                    now,
                    now,
                ),
            )
            for item in plan["items"]:
                revision_id = str(item["revision_id"])
                ordinal = int(item["ordinal"])
                validation_id = f"apify-validation-{uuid.uuid4().hex}"
                validation_approval_hash = hashlib.sha256(
                    f"{approval_hash}:{ordinal}:{revision_id}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO apify_actor_validations (
                        validation_id, workspace_id, route_id, source_id,
                        revision_id, attempt_id, discovery_run_id, kind,
                        approval_key_hash, approved_generation,
                        approved_max_cost_usd, status, semantic_outcome,
                        cost_usd, cost_final, counts_toward_canary,
                        target_fingerprint, created_at, completed_at
                    ) VALUES (
                        ?, ?, ?, NULL, ?, NULL, ?, 'route_reference',
                        ?, ?, ?, 'queued', NULL, NULL, 0, 0, ?, ?, NULL
                    )
                    """,
                    (
                        validation_id,
                        self.workspace_id,
                        str(plan["route_id"]),
                        revision_id,
                        run_id,
                        validation_approval_hash,
                        expected_generation,
                        per_cap,
                        str(reference_fingerprints[revision_id]),
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO apify_actor_canary_batch_items (
                        workspace_id, batch_id, ordinal, revision_id,
                        validation_id, status, semantic_outcome,
                        authorized_cap_usd, actual_cost_usd, cost_final,
                        preflight_checked_at, started_at, completed_at,
                        updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, 'planned', NULL, ?, NULL, 0,
                        NULL, NULL, NULL, ?
                    )
                    """,
                    (
                        self.workspace_id,
                        batch_id,
                        ordinal,
                        revision_id,
                        validation_id,
                        per_cap,
                        now,
                    ),
                )
        result = self.get_canary_batch(batch_id)
        result["_approval_replayed"] = False
        return result

    def get_canary_batch(self, batch_id: str) -> dict[str, Any]:
        connection = self.store.connect()
        batch = connection.execute(
            """
            SELECT batch_id, route_id, discovery_run_id,
                   approved_generation, plan_hash, max_candidates,
                   max_total_charge_usd, per_candidate_cap_usd,
                   goal, operation_slot, pool_stage_id,
                   status, planned_count, success_count, publisher_count,
                   actual_cost_usd, cost_final, stop_reason,
                   created_at, started_at, completed_at, updated_at
            FROM apify_actor_canary_batches
            WHERE workspace_id = ? AND batch_id = ?
            """,
            (self.workspace_id, batch_id),
        ).fetchone()
        if batch is None:
            raise ActorOpsError(
                "apify_actor_canary_batch_not_found",
                "Actor Canary batch was not found",
                status_code=404,
            )
        items = connection.execute(
            """
            SELECT item.ordinal, item.revision_id, item.validation_id,
                   item.status, item.semantic_outcome,
                   item.authorized_cap_usd, item.actual_cost_usd,
                   item.cost_final, item.preflight_checked_at,
                   item.started_at, item.completed_at,
                   revision.actor_id, revision.publisher,
                   revision.build_id, revision.build_number,
                   revision.lifecycle, revision.pricing_json
            FROM apify_actor_canary_batch_items AS item
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = item.workspace_id
             AND revision.revision_id = item.revision_id
            WHERE item.workspace_id = ? AND item.batch_id = ?
            ORDER BY item.ordinal
            """,
            (self.workspace_id, batch_id),
        ).fetchall()
        result = dict(batch)
        result["cost_final"] = bool(result["cost_final"])
        result["items"] = [
            {
                **{
                    key: row[key]
                    for key in (
                        "ordinal",
                        "revision_id",
                        "validation_id",
                        "status",
                        "semantic_outcome",
                        "authorized_cap_usd",
                        "actual_cost_usd",
                        "preflight_checked_at",
                        "started_at",
                        "completed_at",
                        "actor_id",
                        "publisher",
                        "build_id",
                        "build_number",
                        "lifecycle",
                    )
                },
                "cost_final": bool(row["cost_final"]),
                "pricing": _safe_json(row["pricing_json"], {}),
            }
            for row in items
        ]
        if result.get("pool_stage_id"):
            stage = self.get_pool_stage(
                str(result["pool_stage_id"])
            )
            result["route_validation_cap_usd"] = float(
                result["max_total_charge_usd"]
            )
            result["max_total_charge_usd"] = float(
                stage["max_total_charge_usd"]
            )
            result["pool_stage"] = stage
        return result

    def get_pool_stage(self, stage_id: str) -> dict[str, Any]:
        return load_pool_stage(self, stage_id)

    def set_pool_stage_status(
        self,
        stage_id: str,
        *,
        expected_statuses: tuple[str, ...],
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        allowed = {
            "queued", "validating_route", "validating_sources",
            "apply_ready", "applied", "replan_required",
            "blocked_unknown_start", "stale", "failed", "cancelled",
        }
        if status not in allowed or not expected_statuses or any(
            value not in allowed for value in expected_statuses
        ):
            raise ActorOpsError(
                "apify_actor_pool_stage_status_invalid",
                "Actor pool stage status transition is invalid",
                status_code=422,
            )
        placeholders = ",".join("?" for _value in expected_statuses)
        with self._write() as connection:
            cursor = connection.execute(
                f"""
                UPDATE apify_actor_pool_stages
                SET status = ?, last_error_code = ?, updated_at = ?
                WHERE workspace_id = ? AND stage_id = ?
                  AND status IN ({placeholders})
                """,
                (
                    status,
                    _optional_label(error_code, 128),
                    self._now_iso(),
                    self.workspace_id,
                    stage_id,
                    *expected_statuses,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_pool_stage_conflict",
                    "Actor pool stage changed; reload before retrying",
                    status_code=409,
                )
        return self.get_pool_stage(stage_id)

    def active_pool_stage(self, route_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT stage_id
            FROM apify_actor_pool_stages
            WHERE workspace_id = ? AND route_id = ?
              AND status NOT IN ('applied', 'stale', 'failed', 'cancelled')
            ORDER BY created_at DESC, stage_id DESC
            LIMIT 1
            """,
            (self.workspace_id, route_id),
        ).fetchone()
        return self.get_pool_stage(str(row["stage_id"])) if row is not None else None

    def _pool_stage_last_failure(self, stage_id: str) -> dict[str, Any] | None:
        """Return the latest safe terminal failure for a replan projection.

        A guided replan must explain why the prior bounded approval stopped, but
        it must not expose a candidate, source target, remote run, or raw
        upstream error.  The workflow projection therefore carries only a
        normalized outcome code, its phase, and final-or-pending spend.
        """

        connection = self.store.connect()

        def summary(
            row: sqlite3.Row,
            *,
            phase: Literal["route_validation", "source_validation"],
            code: Any,
        ) -> dict[str, Any]:
            normalized = str(code or "").strip().casefold()
            if not _SAFE_ACTOROPS_ERROR_CODE_RE.fullmatch(normalized):
                normalized = "apify_actor_validation_failed"
            raw_cost = row["actual_cost_usd"]
            try:
                actual_cost = float(raw_cost) if raw_cost is not None else None
            except (TypeError, ValueError):
                actual_cost = None
            if actual_cost is not None and (
                not math.isfinite(actual_cost) or actual_cost < 0
            ):
                actual_cost = None
            return {
                "phase": phase,
                "code": normalized,
                "actor_public_name": _actor_public_name(
                    row["display_name"],
                    row["publisher"],
                    row["actor_id"],
                ),
                "actual_cost_usd": (
                    round(actual_cost, 6) if actual_cost is not None else None
                ),
                "cost_final": bool(int(row["cost_final"] or 0)),
                "duration_seconds": (
                    int(row["duration_seconds"])
                    if row["duration_seconds"] is not None
                    else None
                ),
                "dataset_row_count": (
                    int(row["dataset_row_count"])
                    if row["dataset_row_count"] is not None
                    else None
                ),
                "mapped_item_count": (
                    int(row["mapped_item_count"])
                    if row["mapped_item_count"] is not None
                    else None
                ),
                "validation_profile": {
                    "timeout_seconds": int(
                        row["validation_timeout_seconds"] or 300
                    ),
                    "sample_items": int(row["validation_sample_items"] or 1),
                    "max_charge_usd": round(
                        float(row["approved_max_cost_usd"] or 0.02), 6
                    ),
                    "supports_sample_items": bool(
                        row["supports_sample_items"] or 0
                    ),
                    "options_hash": str(row["options_hash"] or "") or None,
                },
                "recommended_action": (
                    "reconcile_status"
                    if normalized in {
                        "apify_run_status_unavailable",
                        "apify_run_reconcile_required",
                    }
                    else "adjust_timeout"
                    if normalized == "apify_actor_run_timed_out"
                    else "increase_sample"
                    if normalized == "suspicious_empty"
                    and bool(row["supports_sample_items"])
                    and int(row["validation_sample_items"] or 1) < 5
                    else "rematch_fields"
                    if normalized in {
                        "apify_actor_contract_mismatch",
                        "apify_actor_identity_mismatch",
                    }
                    else "replace_candidate"
                ),
            }

        route_failure = connection.execute(
            """
            SELECT item.semantic_outcome, item.actual_cost_usd, item.cost_final,
                   validation.duration_seconds, validation.dataset_row_count,
                   validation.mapped_item_count,
                   validation.validation_timeout_seconds,
                   validation.validation_sample_items,
                   validation.approved_max_cost_usd,
                   revision.actor_id, revision.publisher,
                   candidate.display_name,
                   COALESCE(settings.supports_sample_items, 0)
                       AS supports_sample_items,
                   NULL AS options_hash
            FROM apify_actor_pool_stages AS stage
            JOIN apify_actor_canary_batches AS batch
              ON batch.workspace_id = stage.workspace_id
             AND batch.batch_id = stage.initial_batch_id
            JOIN apify_actor_canary_batch_items AS item
              ON item.workspace_id = batch.workspace_id
             AND item.batch_id = batch.batch_id
            JOIN apify_actor_validations AS validation
              ON validation.workspace_id = item.workspace_id
             AND validation.validation_id = item.validation_id
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = item.workspace_id
             AND revision.revision_id = item.revision_id
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            LEFT JOIN apify_actor_pool_stage_candidate_settings AS settings
              ON settings.workspace_id = stage.workspace_id
             AND settings.stage_id = stage.stage_id
             AND settings.revision_id = item.revision_id
            WHERE stage.workspace_id = ? AND stage.stage_id = ?
              AND item.status IN (
                  'failed', 'preflight_failed', 'blocked_unknown_start'
              )
            ORDER BY COALESCE(item.completed_at, item.updated_at) DESC,
                     item.ordinal DESC
            LIMIT 1
            """,
            (self.workspace_id, stage_id),
        ).fetchone()
        if route_failure is not None:
            return summary(
                route_failure,
                phase="route_validation",
                code=route_failure["semantic_outcome"],
            )

        source_failure = connection.execute(
            """
            SELECT source.last_error_code, source.updated_at,
                   validation.status AS validation_status,
                   validation.semantic_outcome,
                   validation.cost_usd AS actual_cost_usd,
                   validation.cost_final, validation.duration_seconds,
                   validation.dataset_row_count, validation.mapped_item_count,
                   validation.validation_timeout_seconds,
                   validation.validation_sample_items,
                   validation.approved_max_cost_usd,
                   revision.actor_id, revision.publisher,
                   candidate.display_name,
                   COALESCE(settings.supports_sample_items, 0)
                       AS supports_sample_items,
                   NULL AS options_hash
            FROM apify_actor_pool_stage_sources AS source
            LEFT JOIN apify_actor_validations AS validation
              ON validation.workspace_id = source.workspace_id
             AND validation.validation_id IN (
                 source.primary_validation_id,
                 source.backup_1_validation_id,
                 source.backup_2_validation_id
             )
            LEFT JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = validation.workspace_id
             AND revision.revision_id = validation.revision_id
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            LEFT JOIN apify_actor_pool_stage_candidate_settings AS settings
              ON settings.workspace_id = source.workspace_id
             AND settings.stage_id = source.stage_id
             AND settings.revision_id = validation.revision_id
            WHERE source.workspace_id = ? AND source.stage_id = ?
              AND source.status = 'failed'
            ORDER BY CASE
                         WHEN validation.status IN (
                             'failed', 'cancelled', 'blocked'
                         ) THEN 0
                         ELSE 1
                     END,
                     COALESCE(validation.completed_at, source.updated_at) DESC,
                     source.source_id ASC
            LIMIT 1
            """,
            (self.workspace_id, stage_id),
        ).fetchone()
        if source_failure is None:
            return None
        validation_failed = str(source_failure["validation_status"] or "") in {
            "failed", "cancelled", "blocked",
        }
        return summary(
            source_failure,
            phase="source_validation",
            code=(
                source_failure["semantic_outcome"]
                if validation_failed
                else source_failure["last_error_code"]
            ),
        )

    def workflow_state(self, route_id: str) -> dict[str, Any]:
        """Project the single authoritative action for the guided UI."""

        route = self.get_route(route_id)
        gate = self.schedule_gate(route_id)
        stage = self.active_pool_stage(route_id)
        # A prior worker version could mark a stage with no frozen target as
        # apply_ready when its enabled-source snapshot was empty. Repair that
        # recoverable state on read before projecting a misleading activation
        # action. This never starts a run or changes the active pool.
        if (
            stage is not None
            and str(stage["status"]) in {"validating_sources", "apply_ready"}
            and self._frozen_pool_stage_target(stage) is None
        ):
            self.refresh_pool_stage_sources(str(stage["stage_id"]))
            stage = self.active_pool_stage(route_id)
        slots = [slot for slot in route.get("slots", []) if slot.get("revision_id")]
        lifecycles = {str(slot.get("lifecycle") or "") for slot in slots}
        source_rows = self.store.connect().execute(
            """
            SELECT binding.validation_status, COUNT(*) AS count
            FROM apify_source_route_bindings AS binding
            JOIN source_catalog AS source
              ON source.workspace_id = binding.workspace_id
             AND source.id = binding.source_id
            WHERE binding.workspace_id = ? AND binding.route_id = ?
              AND source.enabled = 1
            GROUP BY binding.validation_status
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        source_pending = sum(
            int(row["count"] or 0)
            for row in source_rows
            if str(row["validation_status"]) not in _READY_BINDING_STATUSES
        )

        def candidate_selection_progress(
            goal: Literal[
                "initial_pool", "complete_third", "upgrade_legacy",
                "compatibility_single", "add_slot", "replace_slot",
            ],
            target_slot: str | None = None,
        ) -> tuple[dict[str, int], list[str]]:
            result = self.list_pool_candidates(
                route_id, goal=goal, target_slot=target_slot
            )
            eligible = sum(
                bool(item.get("selectable"))
                for item in result.get("candidates", [])
            )
            required = int(result["required_selection_count"])
            return (
                {
                    "eligible_candidate_count": eligible,
                    "required_selection_count": required,
                },
                list(result.get("blockers") or []),
            )

        if str(route.get("status")) == "blocked_unknown_start" or str(
            gate.error_code or ""
        ) in {
            "start_outcome_unknown",
            "apify_start_outcome_unknown",
            "apify_run_reconcile_required",
        }:
            return {
                "kind": "blocked_unknown_start",
                "goal": stage.get("goal") if stage else None,
                "stage_id": stage.get("stage_id") if stage else None,
                "progress": stage.get("source_summary") if stage else {},
                "blockers": ["apify_start_outcome_unknown"],
            }
        if str(gate.status) == "budget_blocked":
            return {
                "kind": "budget_blocked",
                "goal": stage.get("goal") if stage else None,
                "stage_id": stage.get("stage_id") if stage else None,
                "progress": {},
                "blockers": [str(gate.error_code or "budget_blocked")],
            }
        if stage is not None:
            return project_active_pool_stage_workflow(
                self,
                stage,
                candidate_selection_progress=candidate_selection_progress,
            )
        latest = self.store.connect().execute(
            """
            SELECT run_id, stage
            FROM apify_actor_discovery_runs
            WHERE workspace_id = ? AND route_id = ?
              AND COALESCE(error_code, '') != 'superseded_duplicate_refresh'
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (self.workspace_id, route_id),
        ).fetchone()
        discovery_stage = str(latest["stage"]) if latest is not None else ""
        active_initial_batch = self.store.connect().execute(
            """
            SELECT batch_id, status
            FROM apify_actor_canary_batches
            WHERE workspace_id = ? AND route_id = ?
              AND goal = 'initial_pool'
              AND status IN ('queued', 'preflighting', 'running')
            ORDER BY created_at DESC, batch_id DESC
            LIMIT 1
            """,
            (self.workspace_id, route_id),
        ).fetchone()
        running_discovery = discovery_stage in {
            "queued", "searching", "metadata", "ranking",
            "static_validation", "input_validation",
        }
        approval_discovery = discovery_stage in {
            "awaiting_canary_approval", "candidate_shortfall",
            "canary_exhausted", "activation_ready", "completed",
        }
        run_id = str(latest["run_id"]) if latest is not None else None
        compatibility_operational = (
            str(route.get("admission_mode") or "standard") == "compatibility"
            and len(slots) >= 1
        )
        if "legacy_builtin" in lifecycles and not compatibility_operational:
            plan_progress, plan_blockers = (
                candidate_selection_progress("upgrade_legacy")
                if approval_discovery
                else ({}, [])
            )
            if approval_discovery and "candidate_shortfall" in plan_blockers:
                compatibility_progress, compatibility_blockers = (
                    candidate_selection_progress("compatibility_single")
                )
                if not compatibility_blockers:
                    return {
                        "kind": "compatibility_candidate_selection_available",
                        "goal": "compatibility_single",
                        "run_id": run_id,
                        "progress": {
                            **compatibility_progress,
                            "strict_blockers": plan_blockers,
                        },
                        "blockers": [],
                    }
            kind = (
                "legacy_discovery_running"
                if running_discovery
                else "legacy_candidate_selection_required"
                if approval_discovery and not plan_blockers
                else "legacy_discovery_required"
            )
            return {
                "kind": kind,
                "goal": "upgrade_legacy",
                "run_id": run_id,
                "progress": plan_progress,
                "blockers": plan_blockers,
            }
        youtube_fallback_operational = (
            str(route.get("platform") or "") == "youtube"
            and str(route.get("mode") or "") == "fallback"
            and len(slots) >= 1
        )
        if source_pending:
            return {
                "kind": "source_validation_required",
                "goal": None,
                "run_id": run_id,
                "progress": {"pending_sources": source_pending},
                "blockers": [],
            }
        if compatibility_operational:
            plan_progress, plan_blockers = (
                candidate_selection_progress("initial_pool")
                if approval_discovery
                else ({}, [])
            )
            return {
                "kind": (
                    "compatibility_standard_discovery_running"
                    if running_discovery
                    else "compatibility_standard_candidate_selection_required"
                    if approval_discovery and not plan_blockers
                    else "compatibility_operational"
                ),
                "goal": "initial_pool",
                "run_id": run_id,
                "progress": plan_progress,
                "blockers": plan_blockers,
            }
        if len(slots) == 2 and not youtube_fallback_operational:
            plan_progress, plan_blockers = (
                candidate_selection_progress("complete_third")
                if approval_discovery
                else ({}, [])
            )
            kind = (
                "backup_2_discovery_running"
                if running_discovery
                else "backup_2_candidate_selection_required"
                if approval_discovery and not plan_blockers
                else "backup_2_discovery_required"
            )
            return {
                "kind": kind,
                "goal": "complete_third",
                "run_id": run_id,
                "progress": plan_progress,
                "blockers": plan_blockers,
            }
        if len(slots) < 2 and not compatibility_operational and not youtube_fallback_operational:
            plan_progress, plan_blockers = (
                candidate_selection_progress("initial_pool")
                if approval_discovery
                else ({}, [])
            )
            if approval_discovery and "candidate_shortfall" in plan_blockers:
                compatibility_progress, compatibility_blockers = (
                    candidate_selection_progress("compatibility_single")
                )
                if not compatibility_blockers:
                    return {
                        "kind": "compatibility_candidate_selection_available",
                        "goal": "compatibility_single",
                        "run_id": run_id,
                        "progress": {
                            **compatibility_progress,
                            "strict_blockers": plan_blockers,
                        },
                        "blockers": [],
                    }
            kind = (
                "setup_canary_running"
                if active_initial_batch is not None
                else "setup_discovery_running"
                if running_discovery
                else "setup_candidate_selection_required"
                if approval_discovery and not plan_blockers
                else "setup_discovery_required"
            )
            return {
                "kind": kind,
                "goal": "initial_pool",
                "run_id": run_id,
                "progress": plan_progress,
                "blockers": plan_blockers,
            }
        probationary = [
            slot for slot in slots if str(slot.get("lifecycle")) == "probationary"
        ]
        if probationary:
            return {
                "kind": "probation_observing",
                "goal": None,
                "run_id": run_id,
                "progress": {
                    "revisions": [
                        self.certification_progress(str(slot["revision_id"]))
                        for slot in probationary
                    ]
                },
                "blockers": [],
            }
        if str(route.get("runtime", {}).get("status") or "") == "degraded":
            return {
                "kind": "runtime_degraded_monitoring",
                "goal": None,
                "run_id": run_id,
                "progress": {},
                "blockers": [],
            }
        return {
            "kind": "complete",
            "goal": None,
            "run_id": run_id,
            "progress": {},
            "blockers": [],
        }

    def _frozen_pool_stage_target(
        self,
        stage: Mapping[str, Any],
    ) -> dict[str, str | None] | None:
        """Return a persisted stage target only when all frozen proof is intact."""

        target_slot_count = int(stage["target_slot_count"] or 0)
        if target_slot_count not in {1, 2, 3}:
            return None
        if (
            str(stage["goal"]) == "complete_third"
            and target_slot_count != 3
        ):
            return None
        target = {
            "primary": (
                str(stage["target_primary_revision_id"])
                if stage["target_primary_revision_id"]
                else None
            ),
            "backup_1": (
                str(stage["target_backup_1_revision_id"])
                if stage["target_backup_1_revision_id"]
                else None
            ),
            "backup_2": (
                str(stage["target_backup_2_revision_id"])
                if stage["target_backup_2_revision_id"]
                else None
            ),
        }
        required_slots = SLOT_NAMES[:target_slot_count]
        if any(target[slot_name] is None for slot_name in required_slots):
            return None
        if any(
            target[slot_name] is not None
            for slot_name in SLOT_NAMES[target_slot_count:]
        ):
            return None
        revision_ids = [
            str(target[slot_name])
            for slot_name in required_slots
            if target[slot_name] is not None
        ]
        if len(set(revision_ids)) != len(revision_ids):
            return None
        target_hash = revision_set_hash(
            {slot_name: target[slot_name] or "" for slot_name in SLOT_NAMES}
        )
        if str(stage["target_pool_hash"] or "") != target_hash:
            return None
        return target

    def pool_stage_route_ready(self, stage_id: str) -> bool:
        return self._pool_stage_target_slots(self.store.connect(), stage_id) is not None

    def prepare_compatibility_stage_activation(self, stage_id: str) -> dict[str, Any]:
        """Freeze one nonempty compatibility proof for final human activation."""

        with self._write() as connection:
            stage = connection.execute(
                """
                SELECT * FROM apify_actor_pool_stages
                WHERE workspace_id = ? AND stage_id = ?
                """,
                (self.workspace_id, str(stage_id)),
            ).fetchone()
            if stage is None:
                raise ActorOpsError(
                    "apify_actor_pool_stage_not_found",
                    "Actor pool stage was not found",
                    status_code=404,
                )
            if str(stage["goal"]) != "compatibility_single":
                raise ActorOpsError(
                    "apify_actor_pool_stage_goal_invalid",
                    "Actor pool stage is not a compatibility workflow",
                    status_code=422,
                )
            target = self._pool_stage_target_slots(connection, stage_id)
            if target is None:
                pending_cost = connection.execute(
                    """
                    SELECT 1
                    FROM apify_actor_canary_batch_items AS item
                    JOIN apify_actor_canary_batches AS batch
                      ON batch.workspace_id = item.workspace_id
                     AND batch.batch_id = item.batch_id
                    JOIN apify_actor_validations AS validation
                      ON validation.workspace_id = item.workspace_id
                     AND validation.validation_id = item.validation_id
                    WHERE item.workspace_id = ?
                      AND batch.pool_stage_id = ?
                      AND batch.goal = 'compatibility_single'
                      AND item.status = 'succeeded'
                      AND validation.status = 'succeeded'
                      AND validation.semantic_outcome = 'valid_nonempty'
                      AND validation.cost_final = 0
                    LIMIT 1
                    """,
                    (self.workspace_id, str(stage_id)),
                ).fetchone()
                if pending_cost is not None:
                    connection.execute(
                        """
                        UPDATE apify_actor_pool_stages
                        SET status = 'validating_route',
                            last_error_code =
                                'apify_actor_cost_reconciliation_required',
                            updated_at = ?
                        WHERE workspace_id = ? AND stage_id = ?
                          AND status IN (
                              'queued', 'validating_route', 'replan_required'
                          )
                        """,
                        (self._now_iso(), self.workspace_id, str(stage_id)),
                    )
                    return self.get_pool_stage(stage_id)
                connection.execute(
                    """
                    UPDATE apify_actor_pool_stages
                    SET status = 'replan_required',
                        last_error_code = 'compatibility_canary_failed',
                        updated_at = ?
                    WHERE workspace_id = ? AND stage_id = ?
                    """,
                    (self._now_iso(), self.workspace_id, str(stage_id)),
                )
                return self.get_pool_stage(stage_id)
            target_hash = revision_set_hash(
                {name: str(target.get(name) or "") for name in SLOT_NAMES}
            )
            connection.execute(
                """
                UPDATE apify_actor_pool_stages
                SET target_primary_revision_id = ?,
                    target_backup_1_revision_id = NULL,
                    target_backup_2_revision_id = NULL,
                    target_pool_hash = ?, status = 'apply_ready',
                    last_error_code = NULL, updated_at = ?
                WHERE workspace_id = ? AND stage_id = ?
                  AND status IN (
                      'queued', 'validating_route', 'replan_required'
                  )
                """,
                (
                    target["primary"],
                    target_hash,
                    self._now_iso(),
                    self.workspace_id,
                    str(stage_id),
                ),
            )
        return self.get_pool_stage(stage_id)

    def _refresh_pool_stage_sources_locked(
        self,
        connection: sqlite3.Connection,
        stage_id: str,
    ) -> dict[str, int]:
        now = self._now_iso()
        totals = {"succeeded": 0, "failed": 0, "active": 0}
        stage = connection.execute(
            """
            SELECT goal, target_slot_count, target_primary_revision_id,
                   target_backup_1_revision_id, target_backup_2_revision_id,
                   target_pool_hash, status
            FROM apify_actor_pool_stages
            WHERE workspace_id = ? AND stage_id = ?
            """,
            (self.workspace_id, stage_id),
        ).fetchone()
        if stage is None:
            raise ActorOpsError(
                "apify_actor_pool_stage_not_found",
                "Actor pool stage was not found",
                status_code=404,
            )
        stage_status = str(stage["status"])
        if stage_status == "replan_required":
            return totals
        target = self._frozen_pool_stage_target(stage)
        if target is None:
            # A target can only be absent while Route validation is still in
            # flight, or after it exhausted its approved candidate list. It
            # must never be treated as an empty source set that is ready to
            # apply. Persisted historical corruption is repaired here too.
            if stage_status in {"validating_sources", "apply_ready"}:
                connection.execute(
                    """
                    UPDATE apify_actor_pool_stages
                    SET status = 'replan_required',
                        last_error_code = 'candidate_shortfall', updated_at = ?
                    WHERE workspace_id = ? AND stage_id = ?
                      AND status IN ('validating_sources', 'apply_ready')
                    """,
                    (now, self.workspace_id, stage_id),
                )
            return totals
        target_revision_ids = [
            str(target[slot_name])
            for slot_name in SLOT_NAMES
            if target[slot_name] is not None
        ]
        rows = connection.execute(
            """
            SELECT * FROM apify_actor_pool_stage_sources
            WHERE workspace_id = ? AND stage_id = ?
            ORDER BY source_id
            """,
            (self.workspace_id, stage_id),
        ).fetchall()
        for source in rows:
            if str(source["status"]) == "skipped":
                continue
            validation_ids = [
                str(source[column])
                for column in (
                    "primary_validation_id",
                    "backup_1_validation_id",
                    "backup_2_validation_id",
                )
                if source[column]
            ]
            statuses: list[sqlite3.Row] = []
            if validation_ids:
                placeholders = ",".join("?" for _ in validation_ids)
                statuses = connection.execute(
                    f"""
                    SELECT status, semantic_outcome
                    FROM apify_actor_validations
                    WHERE workspace_id = ?
                      AND validation_id IN ({placeholders})
                    """,
                    (self.workspace_id, *validation_ids),
                ).fetchall()
            passed = 0
            if target_revision_ids:
                placeholders = ",".join("?" for _ in target_revision_ids)
                passed = int(
                    connection.execute(
                        f"""
                        SELECT COUNT(DISTINCT revision_id)
                        FROM apify_actor_validations
                        WHERE workspace_id = ? AND source_id = ?
                          AND revision_id IN ({placeholders})
                          AND kind = 'source_canary'
                          AND status = 'succeeded'
                          AND cost_final = 1
                          AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                          AND target_fingerprint = ?
                        """,
                        (
                            self.workspace_id,
                            str(source["source_id"]),
                            *target_revision_ids,
                            str(source["target_fingerprint"]),
                        ),
                    ).fetchone()[0]
                )
            failed = any(str(row["status"]) in {"failed", "cancelled"} for row in statuses)
            active = any(str(row["status"]) in {"queued", "running"} for row in statuses)
            status = (
                "succeeded"
                if passed >= int(source["required_count"])
                else "failed"
                if failed and not active
                else "running"
                if active
                else "failed"
            )
            connection.execute(
                """
                UPDATE apify_actor_pool_stage_sources
                SET passed_count = ?, status = ?,
                    last_error_code = CASE WHEN ? = 'failed'
                        THEN COALESCE(last_error_code, 'source_validation_failed')
                        ELSE NULL END,
                    updated_at = ?
                WHERE workspace_id = ? AND stage_id = ? AND source_id = ?
                """,
                (
                    passed,
                    status,
                    status,
                    now,
                    self.workspace_id,
                    stage_id,
                    str(source["source_id"]),
                ),
            )
            totals["succeeded" if status == "succeeded" else "failed" if status == "failed" else "active"] += 1
        current_sources = connection.execute(
            """
            SELECT binding.source_id, binding.generation,
                   binding.target_fingerprint
            FROM apify_actor_pool_stages AS stage
            JOIN apify_source_route_bindings AS binding
              ON binding.workspace_id = stage.workspace_id
             AND binding.route_id = stage.route_id
            JOIN source_catalog AS source
              ON source.workspace_id = binding.workspace_id
             AND source.id = binding.source_id
            WHERE stage.workspace_id = ? AND stage.stage_id = ?
              AND source.enabled = 1
            ORDER BY binding.source_id
            """,
            (self.workspace_id, stage_id),
        ).fetchall()
        snapshot = {
            str(row["source_id"]): (
                int(row["binding_generation"]),
                str(row["target_fingerprint"]),
                str(row["status"]),
            )
            for row in connection.execute(
                """
                SELECT source_id, binding_generation, target_fingerprint, status
                FROM apify_actor_pool_stage_sources
                WHERE workspace_id = ? AND stage_id = ? AND status != 'skipped'
                """,
                (self.workspace_id, stage_id),
            ).fetchall()
        }
        current = {
            str(row["source_id"]): (
                int(row["generation"]), str(row["target_fingerprint"])
            )
            for row in current_sources
        }
        snapshot_identity = {
            source_id: (values[0], values[1])
            for source_id, values in snapshot.items()
        }
        all_succeeded = all(values[2] == "succeeded" for values in snapshot.values())
        next_status = (
            "replan_required"
            if current != snapshot_identity or totals["failed"]
            else "apply_ready"
            if all_succeeded and totals["active"] == 0
            else "validating_sources"
        )
        connection.execute(
            """
            UPDATE apify_actor_pool_stages
            SET status = ?, last_error_code = CASE
                    WHEN ? = 'replan_required'
                    THEN 'source_snapshot_changed_or_failed'
                    ELSE NULL END,
                updated_at = ?
            WHERE workspace_id = ? AND stage_id = ?
              AND status NOT IN ('applied', 'stale', 'cancelled')
            """,
            (
                next_status,
                next_status,
                now,
                self.workspace_id,
                stage_id,
            ),
        )
        return totals

    def refresh_pool_stage_sources(self, stage_id: str) -> dict[str, int]:
        with self._write() as connection:
            return self._refresh_pool_stage_sources_locked(connection, stage_id)

    def block_pool_stage_unknown_start(self, stage_id: str) -> None:
        with self._write() as connection:
            connection.execute(
                """
                UPDATE apify_actor_pool_stages
                SET status = 'blocked_unknown_start',
                    last_error_code = 'apify_start_outcome_unknown',
                    updated_at = ?
                WHERE workspace_id = ? AND stage_id = ?
                  AND status NOT IN ('applied', 'stale', 'cancelled')
                """,
                (self._now_iso(), self.workspace_id, stage_id),
            )

    def set_canary_batch_status(
        self,
        batch_id: str,
        *,
        expected_statuses: tuple[str, ...],
        status: str,
        stop_reason: str | None = None,
    ) -> dict[str, Any]:
        allowed = {
            "queued", "preflighting", "running", "activation_ready",
            "partial", "blocked_unknown_start", "failed", "cancelled",
        }
        if status not in allowed or not expected_statuses or any(
            value not in allowed for value in expected_statuses
        ):
            raise ActorOpsError(
                "apify_actor_canary_batch_status_invalid",
                "Actor Canary batch status transition is invalid",
                status_code=422,
            )
        now = self._now_iso()
        placeholders = ",".join("?" for _value in expected_statuses)
        terminal = status in {
            "activation_ready", "partial", "blocked_unknown_start",
            "failed", "cancelled",
        }
        with self._write() as connection:
            cursor = connection.execute(
                f"""
                UPDATE apify_actor_canary_batches
                SET status = ?, stop_reason = ?,
                    started_at = CASE
                        WHEN ? IN ('preflighting', 'running')
                        THEN COALESCE(started_at, ?) ELSE started_at END,
                    completed_at = CASE WHEN ? THEN ? ELSE completed_at END,
                    updated_at = ?
                WHERE workspace_id = ? AND batch_id = ?
                  AND status IN ({placeholders})
                """,
                (
                    status,
                    _optional_label(stop_reason, 128),
                    status,
                    now,
                    int(terminal),
                    now,
                    now,
                    self.workspace_id,
                    batch_id,
                    *expected_statuses,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_canary_batch_conflict",
                    "Actor Canary batch changed; reload before retrying",
                    status_code=409,
                )
        return self.get_canary_batch(batch_id)

    def update_canary_batch_item(
        self,
        batch_id: str,
        ordinal: int,
        *,
        status: str,
        semantic_outcome: str | None = None,
        actual_cost_usd: float | None = None,
        cost_final: bool = False,
    ) -> dict[str, Any]:
        allowed = {
            "planned", "preflight_passed", "preflight_failed", "queued",
            "running", "succeeded", "failed", "not_needed_no_charge",
            "blocked_unknown_start",
        }
        if status not in allowed:
            raise ActorOpsError(
                "apify_actor_canary_batch_item_status_invalid",
                "Actor Canary batch item status is invalid",
                status_code=422,
            )
        if actual_cost_usd is not None:
            _bounded_actual_cost(
                actual_cost_usd,
                maximum=VALIDATION_MAX_CHARGE_USD_LIMIT,
            )
        if cost_final and actual_cost_usd is None:
            raise ActorOpsError(
                "apify_actor_cost_invalid",
                "A finalized Actor cost requires an explicit amount",
                status_code=422,
            )
        now = self._now_iso()
        terminal = status in {
            "preflight_failed", "succeeded", "failed",
            "not_needed_no_charge", "blocked_unknown_start",
        }
        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE apify_actor_canary_batch_items
                SET status = ?, semantic_outcome = ?,
                    actual_cost_usd = ?, cost_final = ?,
                    preflight_checked_at = CASE
                        WHEN ? IN ('preflight_passed', 'preflight_failed')
                        THEN COALESCE(preflight_checked_at, ?)
                        ELSE preflight_checked_at END,
                    started_at = CASE
                        WHEN ? IN ('running', 'succeeded', 'failed',
                                   'blocked_unknown_start')
                        THEN COALESCE(started_at, ?) ELSE started_at END,
                    completed_at = CASE WHEN ? THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE workspace_id = ? AND batch_id = ? AND ordinal = ?
                """,
                (
                    status,
                    _optional_label(semantic_outcome, 128),
                    actual_cost_usd,
                    int(cost_final),
                    status,
                    now,
                    status,
                    now,
                    int(terminal),
                    now,
                    now,
                    self.workspace_id,
                    batch_id,
                    int(ordinal),
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_canary_batch_item_not_found",
                    "Actor Canary batch item was not found",
                    status_code=404,
                )
        return self.get_canary_batch(batch_id)

    def finalize_canary_batch(
        self,
        batch_id: str,
        *,
        stop_reason: str | None = None,
    ) -> dict[str, Any]:
        now = self._now_iso()
        with self._write() as connection:
            batch = connection.execute(
                """
                SELECT * FROM apify_actor_canary_batches
                WHERE workspace_id = ? AND batch_id = ?
                """,
                (self.workspace_id, batch_id),
            ).fetchone()
            if batch is None:
                raise ActorOpsError(
                    "apify_actor_canary_batch_not_found",
                    "Actor Canary batch was not found",
                    status_code=404,
                )
            route_minimum = connection.execute(
                """
                SELECT min_runtime_healthy, min_publishers
                FROM apify_actor_route_profiles
                WHERE workspace_id = ? AND route_id = ?
                """,
                (self.workspace_id, str(batch["route_id"])),
            ).fetchone()
            if route_minimum is None:
                raise ActorOpsError(
                    "apify_actor_route_not_found",
                    "Actor route was not found",
                    status_code=404,
                )
            evidence = connection.execute(
                """
                SELECT COUNT(DISTINCT CASE WHEN item.status = 'succeeded'
                           THEN revision.actor_id END) AS actors,
                       COUNT(DISTINCT CASE WHEN item.status = 'succeeded'
                           THEN lower(revision.publisher) END) AS publishers,
                       COALESCE(SUM(CASE WHEN item.cost_final = 1
                           THEN COALESCE(item.actual_cost_usd, 0)
                           ELSE 0 END), 0) AS actual_cost,
                       COUNT(*) AS item_count,
                       SUM(item.cost_final) AS final_count
                FROM apify_actor_canary_batch_items AS item
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = item.workspace_id
                 AND revision.revision_id = item.revision_id
                WHERE item.workspace_id = ? AND item.batch_id = ?
                """,
                (self.workspace_id, batch_id),
            ).fetchone()
            prior = connection.execute(
                """
                SELECT COUNT(DISTINCT revision.actor_id) AS actors,
                       COUNT(DISTINCT lower(revision.publisher)) AS publishers
                FROM apify_actor_validations AS validation
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = validation.workspace_id
                 AND revision.revision_id = validation.revision_id
                WHERE validation.workspace_id = ?
                  AND validation.route_id = ?
                  AND validation.kind = 'route_reference'
                  AND validation.status = 'succeeded'
                  AND validation.semantic_outcome IN (
                      'valid_nonempty', 'valid_empty'
                  )
                """,
                (self.workspace_id, str(batch["route_id"])),
            ).fetchone()
            actor_count = int(prior["actors"] or 0)
            publisher_count = int(prior["publishers"] or 0)
            source_evidence = None
            if batch["pool_stage_id"] is not None:
                source_evidence = connection.execute(
                    """
                    SELECT COALESCE(SUM(CASE
                               WHEN validation.cost_final = 1
                               THEN COALESCE(validation.cost_usd, 0)
                               ELSE 0 END), 0) AS actual_cost,
                           COUNT(validation.validation_id) AS item_count,
                           COALESCE(SUM(validation.cost_final), 0)
                               AS final_count
                    FROM apify_actor_pool_stage_sources AS source
                    LEFT JOIN apify_actor_validations AS validation
                      ON validation.workspace_id = source.workspace_id
                     AND validation.validation_id IN (
                         source.primary_validation_id,
                         source.backup_1_validation_id,
                         source.backup_2_validation_id
                     )
                    WHERE source.workspace_id = ? AND source.stage_id = ?
                    """,
                    (self.workspace_id, str(batch["pool_stage_id"])),
                ).fetchone()
            if batch["pool_stage_id"] is not None:
                pool_stage = connection.execute(
                    """
                    SELECT status FROM apify_actor_pool_stages
                    WHERE workspace_id = ? AND stage_id = ?
                    """,
                    (self.workspace_id, str(batch["pool_stage_id"])),
                ).fetchone()
                ready = pool_stage is not None and str(pool_stage["status"]) == (
                    "apply_ready"
                )
            else:
                ready = (
                    actor_count >= int(route_minimum["min_runtime_healthy"])
                    and publisher_count >= int(route_minimum["min_publishers"])
                )
            batch_status = "activation_ready" if ready else "partial"
            # Batch counters are bounded by the three-item batch schema even
            # when older Route evidence contains more historical Actors.
            stored_actor_count = min(actor_count, BATCH_CANARY_MAX_CANDIDATES)
            stored_publisher_count = min(
                publisher_count,
                BATCH_CANARY_MAX_CANDIDATES,
            )
            final_cost = float(evidence["actual_cost"] or 0) + float(
                source_evidence["actual_cost"]
                if source_evidence is not None
                else 0
            )
            all_final = int(evidence["final_count"] or 0) == int(
                evidence["item_count"] or 0
            )
            if source_evidence is not None:
                all_final = all_final and int(
                    source_evidence["final_count"] or 0
                ) == int(source_evidence["item_count"] or 0)
            connection.execute(
                """
                UPDATE apify_actor_canary_batches
                SET status = ?, success_count = ?, publisher_count = ?,
                    actual_cost_usd = ?, cost_final = ?, stop_reason = ?,
                    completed_at = ?, updated_at = ?
                WHERE workspace_id = ? AND batch_id = ?
                """,
                (
                    batch_status,
                    stored_actor_count,
                    stored_publisher_count,
                    final_cost,
                    int(all_final),
                    _optional_label(
                        stop_reason or (
                            "staged_pool_apply_ready"
                            if batch["pool_stage_id"] is not None and ready
                            else "route_minimum_ready"
                            if ready
                            else "candidate_replenishment_required"
                        ),
                        128,
                    ),
                    now,
                    now,
                    self.workspace_id,
                    batch_id,
                ),
            )
            if ready:
                connection.execute(
                    """
                    UPDATE apify_actor_discovery_runs
                    SET stage = 'activation_ready', error_code = NULL,
                        failure_phase = NULL, updated_at = ?
                    WHERE workspace_id = ? AND run_id = ?
                    """,
                    (
                        now,
                        self.workspace_id,
                        str(batch["discovery_run_id"]),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE apify_actor_discovery_runs
                    SET stage = 'candidate_shortfall',
                        error_code = 'canary_batch_candidates_exhausted',
                        failure_phase = NULL, updated_at = ?
                    WHERE workspace_id = ? AND run_id = ?
                    """,
                    (
                        now,
                        self.workspace_id,
                        str(batch["discovery_run_id"]),
                    ),
                )
        return self.get_canary_batch(batch_id)

    def approve_revision_canary(
        self,
        route_id: str,
        revision_id: str,
        *,
        expected_generation: int,
        approval_id: str,
        confirmation: str,
        max_cost_usd: float,
        reference_fingerprint: str,
        discovery_run_id: str | None = None,
    ) -> dict[str, Any]:
        if confirmation != PAID_CANARY_CONFIRMATION:
            raise ActorOpsError(
                "apify_actor_canary_confirmation_required",
                "Paid Canary requires the exact confirmation phrase",
                status_code=422,
            )
        if (
            not _HEX_64_RE.fullmatch(str(reference_fingerprint))
        ):
            raise ActorOpsError(
                "apify_actor_reference_fingerprint_required",
                "Route Canary requires an opaque public-reference fingerprint",
                status_code=422,
            )
        cap = _bounded_cost(max_cost_usd, maximum=ROUTE_CANARY_BUDGET_USD)
        approval_hash = _approval_key_hash(approval_id)
        with self._write() as connection:
            replay = self._approved_validation_replay(
                connection,
                approval_key_hash=approval_hash,
                route_id=route_id,
                source_id=None,
                revision_id=revision_id,
                kind="route_reference",
                expected_generation=expected_generation,
                max_cost_usd=cap,
                discovery_run_id=discovery_run_id,
            )
            if replay is not None:
                replay["_approval_replayed"] = True
                return replay
            route = self._require_route(connection, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            if cap > float(route["per_run_cap_usd"]):
                raise ActorOpsError(
                    "apify_actor_budget_invalid",
                    "Canary budget exceeds the Route per-run cap",
                    status_code=422,
                )
            if discovery_run_id is not None:
                discovery = connection.execute(
                    """
                    SELECT run.stage
                    FROM apify_actor_discovery_runs AS run
                    JOIN apify_actor_discovery_run_revisions AS association
                      ON association.workspace_id = run.workspace_id
                     AND association.run_id = run.run_id
                    WHERE run.workspace_id = ? AND run.route_id = ?
                      AND run.run_id = ?
                      AND association.revision_id = ?
                    """,
                    (
                        self.workspace_id,
                        route_id,
                        discovery_run_id,
                        revision_id,
                    ),
                ).fetchone()
                if discovery is None:
                    raise ActorOpsError(
                        "apify_actor_revision_discovery_mismatch",
                        "Actor revision does not belong to this discovery run",
                        status_code=404,
                    )
                if str(discovery["stage"]) != "awaiting_canary_approval":
                    raise ActorOpsError(
                        "apify_actor_discovery_not_awaiting_approval",
                        "Actor discovery run is not awaiting Canary approval",
                        status_code=409,
                    )
            revision = connection.execute(
                """
                SELECT revision.revision_id, revision.discovery_run_id
                FROM apify_actor_adapter_revisions AS revision
                JOIN apify_actor_candidates AS candidate
                  ON candidate.id = revision.candidate_id
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = candidate.workspace_id
                 AND profile.route_key = candidate.route_key
                WHERE revision.workspace_id = ? AND revision.revision_id = ?
                  AND profile.route_id = ?
                  AND revision.lifecycle IN ('static_valid', 'probationary')
                """,
                (self.workspace_id, revision_id, route_id),
            ).fetchone()
            if revision is None:
                raise ActorOpsError(
                    "apify_actor_revision_not_canary_ready",
                    "Actor adapter revision is not ready for Canary",
                    status_code=412,
                )
            block_reason = self._revision_canary_block_reason(
                connection,
                route_id,
                revision_id,
            )
            if block_reason is not None:
                raise ActorOpsError(
                    block_reason,
                    "Actor revision does not prove the Route item capability",
                    status_code=412,
                )
            effective_discovery_run_id = (
                discovery_run_id
                if discovery_run_id is not None
                else revision["discovery_run_id"]
            )
            cycle = (
                connection.execute(
                    """
                    SELECT budget_usd
                    FROM apify_actor_discovery_runs
                    WHERE workspace_id = ? AND route_id = ? AND run_id = ?
                    """,
                    (
                        self.workspace_id,
                        route_id,
                        effective_discovery_run_id,
                    ),
                ).fetchone()
                if effective_discovery_run_id is not None
                else None
            )
            cycle_budget = (
                min(float(cycle["budget_usd"]), ROUTE_CANARY_BUDGET_USD)
                if cycle is not None
                else ROUTE_CANARY_BUDGET_USD
            )
            if effective_discovery_run_id is not None:
                usage = connection.execute(
                    """
                    SELECT COALESCE(SUM(
                               validation.counts_toward_canary
                           ), 0) AS attempts,
                           COALESCE(SUM(CASE
                               WHEN validation.cost_final = 1
                               THEN COALESCE(validation.cost_usd, 0)
                               WHEN validation.status IN ('queued', 'running')
                               THEN validation.approved_max_cost_usd
                               ELSE 0 END), 0) AS cost
                    FROM apify_actor_validations AS validation
                    WHERE validation.workspace_id = ?
                      AND validation.route_id = ?
                      AND validation.kind = 'route_reference'
                      AND validation.discovery_run_id = ?
                    """,
                    (
                        self.workspace_id,
                        route_id,
                        effective_discovery_run_id,
                    ),
                ).fetchone()
            else:
                usage = connection.execute(
                    """
                    SELECT COALESCE(SUM(
                               validation.counts_toward_canary
                           ), 0) AS attempts,
                           COALESCE(SUM(CASE
                               WHEN validation.cost_final = 1
                               THEN COALESCE(validation.cost_usd, 0)
                               WHEN validation.status IN ('queued', 'running')
                               THEN validation.approved_max_cost_usd
                               ELSE 0 END), 0) AS cost
                    FROM apify_actor_validations AS validation
                    JOIN apify_actor_adapter_revisions AS used_revision
                      ON used_revision.workspace_id = validation.workspace_id
                     AND used_revision.revision_id = validation.revision_id
                    WHERE validation.workspace_id = ?
                      AND validation.route_id = ?
                      AND validation.kind = 'route_reference'
                      AND validation.discovery_run_id IS NULL
                      AND used_revision.discovery_run_id IS NULL
                    """,
                    (self.workspace_id, route_id),
                ).fetchone()
            inflight = connection.execute(
                """
                SELECT 1
                FROM apify_actor_validations
                WHERE workspace_id = ? AND route_id = ?
                  AND revision_id = ? AND kind = 'route_reference'
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (self.workspace_id, route_id, revision_id),
            ).fetchone()
            if inflight is not None:
                raise ActorOpsError(
                    "apify_actor_revision_canary_active",
                    "A Route Canary is already queued or running",
                    status_code=409,
                )
            if (
                int(usage["attempts"]) >= ROUTE_CANARY_ATTEMPT_LIMIT
                or float(usage["cost"]) + cap > cycle_budget + 1e-9
            ):
                raise ActorOpsError(
                    "apify_actor_canary_budget_exhausted",
                    "Route certification Canary budget is exhausted",
                    status_code=412,
                )
            validation_id = f"apify-validation-{uuid.uuid4().hex}"
            now = self._now_iso()
            connection.execute(
                """
                INSERT INTO apify_actor_validations (
                    validation_id, workspace_id, route_id, source_id,
                    revision_id, attempt_id, discovery_run_id, kind,
                    approval_key_hash,
                    approved_generation, approved_max_cost_usd, status,
                    semantic_outcome, cost_usd, cost_final,
                    counts_toward_canary, target_fingerprint,
                    created_at, completed_at
                ) VALUES (?, ?, ?, NULL, ?, NULL, ?, 'route_reference', ?, ?, ?,
                          'queued', NULL, NULL, 0, 0, ?, ?, NULL)
                """,
                (
                    validation_id,
                    self.workspace_id,
                    route_id,
                    revision_id,
                    effective_discovery_run_id,
                    approval_hash,
                    expected_generation,
                    cap,
                    reference_fingerprint,
                    now,
                ),
            )
        result = self.get_validation(validation_id)
        result["_approval_replayed"] = False
        return result

    def approve_source_canary(
        self,
        source_id: str,
        revision_id: str,
        *,
        expected_generation: int,
        approval_id: str,
        confirmation: str,
        max_cost_usd: float,
    ) -> dict[str, Any]:
        if confirmation != PAID_CANARY_CONFIRMATION:
            raise ActorOpsError(
                "apify_actor_canary_confirmation_required",
                "Paid Canary requires the exact confirmation phrase",
                status_code=422,
            )
        cap = _bounded_cost(max_cost_usd, maximum=SOURCE_CANARY_BUDGET_USD)
        approval_hash = _approval_key_hash(approval_id)
        with self._write() as connection:
            replay = self._approved_validation_replay(
                connection,
                approval_key_hash=approval_hash,
                route_id=None,
                source_id=source_id,
                revision_id=revision_id,
                kind="source_canary",
                expected_generation=expected_generation,
                max_cost_usd=cap,
                discovery_run_id=None,
            )
            if replay is not None:
                replay["_approval_replayed"] = True
                return replay
            binding = connection.execute(
                """
                SELECT * FROM apify_source_route_bindings
                WHERE workspace_id = ? AND source_id = ?
                """,
                (self.workspace_id, source_id),
            ).fetchone()
            if binding is None:
                raise ActorOpsError(
                    "apify_actor_source_binding_not_found",
                    "Source Actor binding was not found",
                    status_code=404,
                )
            if int(binding["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_binding_generation_conflict",
                    "Source Actor binding changed; reload before retrying",
                )
            route = self._require_route(connection, str(binding["route_id"]))
            revision = connection.execute(
                """
                SELECT lifecycle, build_id, build_number, manifest_hash
                FROM apify_actor_adapter_revisions
                WHERE workspace_id = ? AND revision_id = ?
                """,
                (self.workspace_id, revision_id),
            ).fetchone()
            if (
                revision is None
                or str(revision["lifecycle"]) == "legacy_builtin"
                or not revision["build_id"]
                or not revision["build_number"]
                or not revision["manifest_hash"]
            ):
                raise ActorOpsError(
                    "apify_actor_source_requires_pool_upgrade",
                    "Compatibility Actor revisions must be upgraded before source validation",
                    status_code=412,
                )
            if block_reason := self._revision_canary_block_reason(connection, str(binding["route_id"]), revision_id):
                raise ActorOpsError(block_reason, "Actor revision does not prove the source item contract", status_code=412)
            if cap > float(route["per_run_cap_usd"]):
                raise ActorOpsError(
                    "apify_actor_budget_invalid",
                    "Canary budget exceeds the Route per-run cap",
                    status_code=422,
                )
            usage = connection.execute(
                """
                SELECT COALESCE(SUM(CASE
                           WHEN cost_final = 1 THEN COALESCE(cost_usd, 0)
                           WHEN status IN ('queued', 'running')
                           THEN approved_max_cost_usd
                           ELSE 0 END), 0) AS cost
                FROM apify_actor_validations
                WHERE workspace_id = ? AND source_id = ?
                  AND kind = 'source_canary' AND created_at >= ?
                """,
                (
                    self.workspace_id,
                    source_id,
                    str(binding["updated_at"]),
                ),
            ).fetchone()
            if float(usage["cost"]) + cap > SOURCE_CANARY_BUDGET_USD + 1e-9:
                raise ActorOpsError(
                    "apify_actor_canary_budget_exhausted",
                    "Source validation Canary budget is exhausted",
                    status_code=412,
                )
            active = connection.execute(
                """
                SELECT 1 FROM apify_route_active_slots
                WHERE workspace_id = ? AND route_id = ? AND revision_id = ?
                """,
                (self.workspace_id, binding["route_id"], revision_id),
            ).fetchone()
            if active is None:
                raise ActorOpsError(
                    "apify_actor_revision_not_active",
                    "Actor adapter revision is not in the active pool",
                    status_code=412,
                )
            inflight = connection.execute(
                """
                SELECT 1 FROM apify_actor_validations
                WHERE workspace_id = ? AND route_id = ? AND source_id = ?
                  AND kind = 'source_canary'
                  AND target_fingerprint = ?
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (
                    self.workspace_id,
                    binding["route_id"],
                    source_id,
                    binding["target_fingerprint"],
                ),
            ).fetchone()
            if inflight is not None:
                raise ActorOpsError(
                    "apify_actor_source_canary_active",
                    "A source Canary is already queued or running",
                    status_code=409,
                )
            active_rows = connection.execute(
                """
                SELECT slot_name, revision_id
                FROM apify_route_active_slots
                WHERE workspace_id = ? AND route_id = ?
                  AND revision_id IS NOT NULL
                ORDER BY CASE slot_name
                    WHEN 'primary' THEN 1
                    WHEN 'backup_1' THEN 2
                    ELSE 3 END
                """,
                (self.workspace_id, binding["route_id"]),
            ).fetchall()
            succeeded = {
                str(row["revision_id"])
                for row in connection.execute(
                    """
                    SELECT revision_id FROM apify_actor_validations
                    WHERE workspace_id = ? AND route_id = ? AND source_id = ?
                      AND kind = 'source_canary' AND status = 'succeeded'
                      AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                      AND target_fingerprint = ?
                    """,
                    (
                        self.workspace_id,
                        binding["route_id"],
                        source_id,
                        binding["target_fingerprint"],
                    ),
                ).fetchall()
            }
            pending = [
                str(row["revision_id"])
                for row in active_rows
                if str(row["revision_id"]) not in succeeded
            ]
            if not pending or revision_id != pending[0]:
                raise ActorOpsError(
                    "apify_actor_source_canary_order_invalid",
                    "Source Canaries must run serially in active-slot order",
                    status_code=412,
                )
            validation_id = f"apify-validation-{uuid.uuid4().hex}"
            now = self._now_iso()
            connection.execute(
                """
                INSERT INTO apify_actor_validations (
                    validation_id, workspace_id, route_id, source_id,
                    revision_id, attempt_id, kind, approval_key_hash,
                    approved_generation, approved_max_cost_usd, status,
                    semantic_outcome, cost_usd, cost_final,
                    counts_toward_canary, target_fingerprint,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, NULL, 'source_canary', ?, ?, ?,
                          'queued', NULL, NULL, 0, 0, ?, ?, NULL)
                """,
                (
                    validation_id,
                    self.workspace_id,
                    binding["route_id"],
                    source_id,
                    revision_id,
                    approval_hash,
                    expected_generation,
                    cap,
                    binding["target_fingerprint"],
                    now,
                ),
            )
        result = self.get_validation(validation_id)
        result["_approval_replayed"] = False
        return result

    def _approved_validation_replay(
        self,
        connection: sqlite3.Connection,
        *,
        approval_key_hash: str,
        route_id: str | None,
        source_id: str | None,
        revision_id: str,
        kind: Literal["route_reference", "source_canary"],
        expected_generation: int,
        max_cost_usd: float,
        discovery_run_id: str | None,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT validation_id, route_id, source_id, revision_id, kind,
                   approved_generation, status, semantic_outcome, cost_usd,
                   cost_final, counts_toward_canary,
                   approved_max_cost_usd, discovery_run_id,
                   created_at, completed_at
            FROM apify_actor_validations
            WHERE workspace_id = ? AND approval_key_hash = ?
            """,
            (self.workspace_id, approval_key_hash),
        ).fetchone()
        if row is None:
            return None
        same_action = (
            str(row["route_id"]) == str(route_id or row["route_id"])
            and (
                (row["source_id"] is None and source_id is None)
                or str(row["source_id"]) == str(source_id)
            )
            and str(row["revision_id"]) == str(revision_id)
            and str(row["kind"]) == kind
            and (
                (row["discovery_run_id"] is None and discovery_run_id is None)
                or str(row["discovery_run_id"]) == str(discovery_run_id)
            )
            and int(row["approved_generation"] or 0)
            == int(expected_generation)
            and abs(
                float(row["approved_max_cost_usd"] or 0) - max_cost_usd
            )
            <= 1e-9
        )
        if not same_action:
            raise ActorOpsError(
                "apify_actor_approval_id_conflict",
                "Paid approval id was already used for another action",
                status_code=409,
            )
        return {
            key: row[key]
            for key in (
                "validation_id",
                "route_id",
                "source_id",
                "revision_id",
                "kind",
                "status",
                "semantic_outcome",
                "cost_usd",
                "cost_final",
                "counts_toward_canary",
                "created_at",
                "completed_at",
            )
        }

    def record_validation(
        self,
        validation_id: str,
        *,
        status: Literal["running", "succeeded", "failed", "cancelled"],
        semantic_outcome: str | None = None,
        attempt_id: str | None = None,
        cost_usd: float | None = None,
        cost_final: bool | None = None,
        counts_toward_canary: bool | None = None,
        duration_seconds: int | None = None,
        dataset_row_count: int | None = None,
        mapped_item_count: int | None = None,
    ) -> dict[str, Any]:
        if cost_usd is not None:
            _bounded_actual_cost(
                cost_usd,
                maximum=ROUTE_CANARY_BUDGET_USD,
            )
        if semantic_outcome is not None:
            semantic_outcome = _safe_label(semantic_outcome, 128)
        if cost_final is True and cost_usd is None:
            raise ActorOpsError(
                "apify_actor_cost_invalid",
                "A finalized Actor cost requires an explicit amount",
                status_code=422,
            )
        resolved_cost_final = (
            bool(cost_usd is not None)
            if cost_final is None
            else bool(cost_final)
        )
        resolved_counts = (
            bool(attempt_id is not None)
            if counts_toward_canary is None
            else bool(counts_toward_canary)
        )
        terminal = status in {"succeeded", "failed", "cancelled"}
        for value in (duration_seconds, dataset_row_count, mapped_item_count):
            if value is not None and (
                isinstance(value, bool) or int(value) < 0
            ):
                raise ActorOpsError(
                    "apify_actor_validation_metrics_invalid",
                    "Actor validation metrics are invalid",
                    status_code=422,
                )
        now = self._now_iso()
        with self._write() as connection:
            current = connection.execute(
                """
                SELECT validation.status, validation.kind,
                       validation.discovery_run_id, validation.route_id,
                       validation.revision_id,
                       validation.approved_max_cost_usd,
                       validation.target_fingerprint,
                       validation.validation_profile_hash,
                       revision.candidate_id, revision.actor_id,
                       revision.build_id, revision.build_number,
                       revision.manifest_hash, revision.input_schema_hash,
                       revision.output_schema_hash, revision.pricing_json,
                       profile.admission_mode, profile.min_runtime_healthy,
                       profile.min_publishers,
                       EXISTS (
                           SELECT 1
                           FROM apify_actor_canary_batch_items AS batch_item
                           JOIN apify_actor_canary_batches AS batch
                             ON batch.workspace_id = batch_item.workspace_id
                            AND batch.batch_id = batch_item.batch_id
                           WHERE batch_item.workspace_id = validation.workspace_id
                             AND batch_item.validation_id = validation.validation_id
                             AND batch.goal = 'compatibility_single'
                       ) AS compatibility_trial
                FROM apify_actor_validations AS validation
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = validation.workspace_id
                 AND revision.revision_id = validation.revision_id
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = validation.workspace_id
                 AND profile.route_id = validation.route_id
                WHERE validation.workspace_id = ?
                  AND validation.validation_id = ?
                """,
                (self.workspace_id, validation_id),
            ).fetchone()
            if current is None:
                raise ActorOpsError(
                    "apify_actor_validation_not_found",
                    "Actor validation was not found",
                    status_code=404,
                )
            if str(current["status"]) not in {"queued", "running"}:
                raise ActorOpsError(
                    "apify_actor_validation_terminal",
                    "Actor validation is already terminal",
                )
            if (
                cost_usd is not None
                and float(cost_usd)
                > float(current["approved_max_cost_usd"] or 0) + 1e-9
            ):
                raise ActorOpsError(
                    "apify_actor_cost_invalid",
                    "Actor validation cost exceeds its approved limit",
                    status_code=422,
                )
            if attempt_id is not None:
                attempt = connection.execute(
                    """
                    SELECT attempt.adapter_revision_id, validation.revision_id
                    FROM apify_actor_attempts AS attempt
                    JOIN apify_actor_validations AS validation
                      ON validation.validation_id = ?
                    WHERE attempt.workspace_id = ? AND attempt.id = ?
                    """,
                    (validation_id, self.workspace_id, attempt_id),
                ).fetchone()
                if (
                    attempt is None
                    or str(attempt["adapter_revision_id"] or "")
                    != str(attempt["revision_id"])
                ):
                    raise ActorOpsError(
                        "apify_actor_validation_attempt_mismatch",
                        "Actor validation attempt does not match its frozen revision",
                        status_code=422,
                    )
            connection.execute(
                """
                UPDATE apify_actor_validations
                SET status = ?, semantic_outcome = ?, attempt_id = ?,
                    cost_usd = COALESCE(?, cost_usd),
                    cost_final = ?, counts_toward_canary = ?,
                    duration_seconds = COALESCE(?, duration_seconds),
                    dataset_row_count = COALESCE(?, dataset_row_count),
                    mapped_item_count = COALESCE(?, mapped_item_count),
                    failure_fingerprint = ?,
                    completed_at = CASE WHEN ? THEN ? ELSE NULL END
                WHERE workspace_id = ? AND validation_id = ?
                """,
                (
                    status,
                    semantic_outcome,
                    attempt_id,
                    cost_usd,
                    int(resolved_cost_final),
                    int(resolved_counts),
                    duration_seconds,
                    dataset_row_count,
                    mapped_item_count,
                    (
                        validation_failure_fingerprint(
                            route_id=str(current["route_id"]),
                            candidate_id=str(current["candidate_id"]),
                            revision_id=str(current["revision_id"]),
                            build_id=str(current["build_id"] or ""),
                            build_number=str(current["build_number"] or ""),
                            manifest_hash=str(current["manifest_hash"] or ""),
                            target_fingerprint=str(
                                current["target_fingerprint"] or ""
                            ),
                            kind=str(current["kind"]),
                            profile_hash=str(
                                current["validation_profile_hash"] or ""
                            ),
                        )
                        if terminal
                        and status == "failed"
                        and current["validation_profile_hash"]
                        else None
                    ),
                    int(terminal),
                    now,
                    self.workspace_id,
                    validation_id,
                ),
            )
            if (
                terminal
                and str(current["kind"]) == "route_reference"
                and current["discovery_run_id"] is not None
            ):
                cycle = connection.execute(
                    """
                    SELECT COALESCE(SUM(
                               validation.counts_toward_canary
                           ), 0) AS attempts,
                           COUNT(DISTINCT CASE
                               WHEN validation.status = 'succeeded'
                               THEN revision.actor_id END
                           ) AS succeeded_actors,
                           COUNT(DISTINCT CASE
                               WHEN validation.status = 'succeeded'
                               THEN lower(revision.publisher) END
                           ) AS succeeded_publishers
                    FROM apify_actor_validations AS validation
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = validation.workspace_id
                     AND revision.revision_id = validation.revision_id
                    WHERE validation.workspace_id = ?
                      AND validation.discovery_run_id = ?
                      AND validation.kind = 'route_reference'
                    """,
                    (self.workspace_id, str(current["discovery_run_id"])),
                ).fetchone()
                if (
                    cycle is not None
                    and int(cycle["succeeded_actors"] or 0)
                    >= int(current["min_runtime_healthy"])
                    and int(cycle["succeeded_publishers"] or 0)
                    >= int(current["min_publishers"])
                ):
                    connection.execute(
                        """
                        UPDATE apify_actor_discovery_runs
                        SET stage = 'activation_ready', error_code = NULL,
                            failure_phase = NULL, updated_at = ?
                        WHERE workspace_id = ? AND run_id = ?
                          AND stage IN (
                              'awaiting_canary_approval',
                              'canary_exhausted'
                          )
                        """,
                        (
                            now,
                            self.workspace_id,
                            str(current["discovery_run_id"]),
                        ),
                    )
                elif (
                    cycle is not None
                    and int(cycle["attempts"] or 0)
                    >= ROUTE_CANARY_ATTEMPT_LIMIT
                    and (
                        int(cycle["succeeded_actors"] or 0)
                        < int(current["min_runtime_healthy"])
                        or int(cycle["succeeded_publishers"] or 0)
                        < int(current["min_publishers"])
                    )
                ):
                    connection.execute(
                        """
                        UPDATE apify_actor_discovery_runs
                        SET stage = 'canary_exhausted',
                            error_code = 'route_canary_attempts_exhausted',
                            failure_phase = NULL,
                            updated_at = ?
                        WHERE workspace_id = ? AND run_id = ?
                          AND stage = 'awaiting_canary_approval'
                        """,
                        (
                            now,
                            self.workspace_id,
                            str(current["discovery_run_id"]),
                        ),
                    )
        result = self.get_validation(validation_id)
        if terminal:
            try:
                from .apify_actor_resilience import ApifyActorResilienceService

                reason = str(semantic_outcome or status)
                deterministic = status == "failed" and reason in {
                    "apify_actor_contract_mismatch",
                    "apify_actor_identity_mismatch",
                    "apify_actor_target_identity_mismatch",
                    "apify_actor_metadata_only",
                    "apify_actor_input_schema_unmappable",
                    "apify_manifest_output_pointer_unverifiable",
                    "apify_manifest_item_identity_invalid",
                    "apify_manifest_source_identity_invalid",
                    "actor_requires_full_permissions",
                }
                resilience = ApifyActorResilienceService(
                    self.store,
                    workspace_id=self.workspace_id,
                )
                resilience.record_evaluation(
                    route_id=str(current["route_id"]),
                    candidate_id=str(current["candidate_id"]),
                    revision_id=str(current["revision_id"]),
                    evidence_fingerprint=actor_evidence_fingerprint(
                        route_id=str(current["route_id"]),
                        candidate_id=str(current["candidate_id"]),
                        actor_id=str(current["actor_id"]),
                        build_id=str(current["build_id"] or ""),
                        build_number=str(current["build_number"] or ""),
                        manifest_hash=str(current["manifest_hash"] or ""),
                        pricing=_safe_json(current["pricing_json"], {}),
                        input_schema_hash=str(
                            current["input_schema_hash"] or ""
                        ),
                        output_schema_hash=str(
                            current["output_schema_hash"] or ""
                        ),
                    ),
                    policy_mode=(
                        "compatibility"
                        if bool(current["compatibility_trial"])
                        or str(current["admission_mode"]) == "compatibility"
                        else "standard"
                    ),
                    stage="canary",
                    outcome="passed" if status == "succeeded" else "failed",
                    reason_code=reason,
                    deterministic=deterministic,
                )
                resilience.emit_event(
                    route_id=str(current["route_id"]),
                    candidate_id=str(current["candidate_id"]),
                    phase="canary",
                    outcome="succeeded" if status == "succeeded" else "failed",
                    reason_code=reason,
                    final_cost_usd=cost_usd if resolved_cost_final else None,
                )
            except Exception:
                # Diagnostics and failure memory are explicitly best effort.
                pass
        return result

    def get_validation(self, validation_id: str) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT validation_id, route_id, source_id, revision_id, kind,
                   status, semantic_outcome, cost_usd, cost_final,
                   counts_toward_canary, validation_timeout_seconds,
                   validation_sample_items, validation_profile_hash,
                   duration_seconds, dataset_row_count, mapped_item_count,
                   created_at, completed_at
            FROM apify_actor_validations
            WHERE workspace_id = ? AND validation_id = ?
            """,
            (self.workspace_id, validation_id),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_validation_not_found",
                "Actor validation was not found",
                status_code=404,
            )
        return dict(row)

    def reconcile_validation_result(
        self,
        validation_id: str,
        *,
        semantic_outcome: str,
        cost_usd: float | None,
        cost_final: bool,
        duration_seconds: int,
        dataset_row_count: int,
        mapped_item_count: int,
    ) -> dict[str, Any]:
        """Replace only a status-read failure after a no-POST reconciliation."""

        semantic = _safe_label(semantic_outcome, 128)
        succeeded = semantic in {"valid_nonempty", "valid_empty"}
        if succeeded and (not cost_final or cost_usd is None):
            raise ActorOpsError(
                "apify_run_status_unavailable",
                "The reconciled Actor Run cost is not final yet",
                retryable=True,
                status_code=503,
            )
        if cost_final and cost_usd is None:
            raise ActorOpsError(
                "apify_actor_cost_invalid",
                "Final reconciliation cost is missing",
                status_code=422,
            )
        if cost_usd is not None:
            _bounded_actual_cost(cost_usd, maximum=VALIDATION_MAX_CHARGE_USD_LIMIT)
        now = self._now_iso()
        with self._write() as connection:
            row = connection.execute(
                """
                SELECT validation.status, validation.semantic_outcome,
                       validation.approved_max_cost_usd,
                       validation.attempt_id, validation.kind,
                       validation.route_id, validation.revision_id,
                       validation.target_fingerprint,
                       validation.validation_profile_hash,
                       revision.candidate_id, revision.build_id,
                       revision.build_number, revision.manifest_hash
                FROM apify_actor_validations AS validation
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = validation.workspace_id
                 AND revision.revision_id = validation.revision_id
                WHERE validation.workspace_id = ?
                  AND validation.validation_id = ?
                """,
                (self.workspace_id, validation_id),
            ).fetchone()
            if row is None:
                raise ActorOpsError(
                    "apify_actor_validation_not_found",
                    "Actor validation was not found",
                    status_code=404,
                )
            if str(row["status"]) not in {"failed", "cancelled"} or str(
                row["semantic_outcome"] or ""
            ) not in {
                "apify_run_status_unavailable",
                "apify_actor_run_status_unavailable",
                "apify_run_reconcile_required",
            }:
                raise ActorOpsError(
                    "apify_actor_validation_reconcile_not_allowed",
                    "Only an unresolved status read can be reconciled",
                    status_code=409,
                )
            if row["attempt_id"] is None:
                raise ActorOpsError(
                    "apify_actor_validation_reconcile_unavailable",
                    "The validation has no durable Run to reconcile",
                    status_code=412,
                )
            if (
                cost_usd is not None
                and float(cost_usd)
                > float(row["approved_max_cost_usd"] or 0) + 1e-9
            ):
                raise ActorOpsError(
                    "apify_actor_cost_invalid",
                    "Reconciled cost exceeds its approved limit",
                    status_code=422,
                )
            failure_fingerprint = None
            if not succeeded and row["validation_profile_hash"]:
                failure_fingerprint = validation_failure_fingerprint(
                    route_id=str(row["route_id"]),
                    candidate_id=str(row["candidate_id"]),
                    revision_id=str(row["revision_id"]),
                    build_id=str(row["build_id"] or ""),
                    build_number=str(row["build_number"] or ""),
                    manifest_hash=str(row["manifest_hash"] or ""),
                    target_fingerprint=str(row["target_fingerprint"] or ""),
                    kind=str(row["kind"]),
                    profile_hash=str(row["validation_profile_hash"]),
                )
            connection.execute(
                """
                UPDATE apify_actor_validations
                SET status = ?, semantic_outcome = ?, cost_usd = ?,
                    cost_final = ?, counts_toward_canary = 1,
                    duration_seconds = ?, dataset_row_count = ?,
                    mapped_item_count = ?, failure_fingerprint = ?,
                    completed_at = ?
                WHERE workspace_id = ? AND validation_id = ?
                """,
                (
                    "succeeded" if succeeded else "failed",
                    semantic,
                    cost_usd,
                    int(cost_final),
                    max(0, int(duration_seconds)),
                    max(0, int(dataset_row_count)),
                    max(0, int(mapped_item_count)),
                    failure_fingerprint,
                    now,
                    self.workspace_id,
                    validation_id,
                ),
            )
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET status = ?, semantic_outcome = ?, actual_cost_usd = ?,
                    cost_final = ?, last_error_code = ?, terminal_at = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (
                    "succeeded" if semantic == "valid_nonempty" else
                    "valid_empty" if semantic == "valid_empty" else
                    "actor_failed",
                    semantic,
                    cost_usd,
                    int(cost_final),
                    None if succeeded else semantic,
                    now,
                    now,
                    self.workspace_id,
                    str(row["attempt_id"]),
                ),
            )
            connection.execute(
                """
                UPDATE apify_actor_canary_batch_items
                SET status = ?, semantic_outcome = ?, actual_cost_usd = ?,
                    cost_final = ?, completed_at = ?, updated_at = ?
                WHERE workspace_id = ? AND validation_id = ?
                """,
                (
                    "succeeded" if succeeded else "failed",
                    semantic,
                    cost_usd,
                    int(cost_final),
                    now,
                    now,
                    self.workspace_id,
                    validation_id,
                ),
            )
        return self.get_validation(validation_id)

    def resume_reconciled_validation(
        self,
        validation_id: str,
    ) -> dict[str, Any]:
        """Resume only work already covered by the original paid approval.

        Re-reading a known Run is free.  When that read proves a Route Canary
        succeeded, the old batch may continue with its already-approved source
        checks; the candidate Actor itself is never started again.  A source
        read can likewise move its frozen stage to apply-ready without another
        paid request.
        """

        with self._write() as connection:
            row = connection.execute(
                """
                SELECT validation.status, validation.semantic_outcome,
                       validation.kind, validation.cost_usd,
                       validation.cost_final,
                       item.batch_id, batch.pool_stage_id,
                       source.stage_id AS source_stage_id,
                       source_stage.initial_batch_id AS source_batch_id
                FROM apify_actor_validations AS validation
                LEFT JOIN apify_actor_canary_batch_items AS item
                  ON item.workspace_id = validation.workspace_id
                 AND item.validation_id = validation.validation_id
                LEFT JOIN apify_actor_canary_batches AS batch
                  ON batch.workspace_id = item.workspace_id
                 AND batch.batch_id = item.batch_id
                LEFT JOIN apify_actor_pool_stage_sources AS source
                  ON source.workspace_id = validation.workspace_id
                 AND validation.validation_id IN (
                     source.primary_validation_id,
                     source.backup_1_validation_id,
                     source.backup_2_validation_id
                 )
                LEFT JOIN apify_actor_pool_stages AS source_stage
                  ON source_stage.workspace_id = source.workspace_id
                 AND source_stage.stage_id = source.stage_id
                WHERE validation.workspace_id = ?
                  AND validation.validation_id = ?
                """,
                (self.workspace_id, validation_id),
            ).fetchone()
            if row is None:
                raise ActorOpsError(
                    "apify_actor_validation_not_found",
                    "Actor validation was not found",
                    status_code=404,
                )
            if (
                str(row["status"]) != "succeeded"
                or str(row["semantic_outcome"] or "")
                not in {"valid_nonempty", "valid_empty"}
                or not bool(row["cost_final"])
            ):
                return {
                    "resumed": False,
                    "batch_id": row["batch_id"] or row["source_batch_id"],
                    "stage_id": row["pool_stage_id"] or row["source_stage_id"],
                    "enqueue_batch": False,
                }
            if str(row["kind"]) == "route_reference" and row["batch_id"]:
                batch_id = str(row["batch_id"])
                stage_id = (
                    str(row["pool_stage_id"])
                    if row["pool_stage_id"]
                    else None
                )
                if stage_id is not None:
                    connection.execute(
                        """
                        UPDATE apify_actor_pool_stages
                        SET status = 'queued', last_error_code = NULL,
                            target_primary_revision_id = NULL,
                            target_backup_1_revision_id = NULL,
                            target_backup_2_revision_id = NULL,
                            target_pool_hash = NULL, updated_at = ?
                        WHERE workspace_id = ? AND stage_id = ?
                          AND status = 'replan_required'
                        """,
                        (self._now_iso(), self.workspace_id, stage_id),
                    )
                connection.execute(
                    """
                    UPDATE apify_actor_canary_batches
                    SET status = 'queued', stop_reason = NULL,
                        completed_at = NULL, updated_at = ?
                    WHERE workspace_id = ? AND batch_id = ?
                      AND status IN ('partial', 'failed')
                    """,
                    (self._now_iso(), self.workspace_id, batch_id),
                )
                return {
                    "resumed": True,
                    "batch_id": batch_id,
                    "stage_id": stage_id,
                    "enqueue_batch": True,
                }
            stage_id = (
                str(row["source_stage_id"])
                if row["source_stage_id"]
                else None
            )
            batch_id = (
                str(row["source_batch_id"])
                if row["source_batch_id"]
                else None
            )
            if stage_id is not None:
                connection.execute(
                    """
                    UPDATE apify_actor_pool_stages
                    SET status = 'validating_sources', last_error_code = NULL,
                        updated_at = ?
                    WHERE workspace_id = ? AND stage_id = ?
                      AND status = 'replan_required'
                    """,
                    (self._now_iso(), self.workspace_id, stage_id),
                )
        if stage_id is not None:
            self.refresh_pool_stage_sources(stage_id)
            if batch_id is not None:
                self.finalize_canary_batch(batch_id)
            return {
                "resumed": True,
                "batch_id": batch_id,
                "stage_id": stage_id,
                "enqueue_batch": False,
            }
        return {
            "resumed": False,
            "batch_id": None,
            "stage_id": None,
            "enqueue_batch": False,
        }

    def activate_binding(
        self,
        source_id: str,
        *,
        expected_generation: int,
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != FIRST_ACTIVATION_CONFIRMATION:
            raise ActorOpsError(
                "apify_actor_activation_confirmation_required",
                "First Actor route activation requires the exact confirmation phrase",
                status_code=422,
            )
        now = self._now_iso()
        with self._write() as connection:
            binding = connection.execute(
                """
                SELECT * FROM apify_source_route_bindings
                WHERE workspace_id = ? AND source_id = ?
                """,
                (self.workspace_id, source_id),
            ).fetchone()
            if binding is None:
                raise ActorOpsError(
                    "apify_actor_source_binding_not_found",
                    "Source Actor binding was not found",
                    status_code=404,
                )
            rows = connection.execute(
                """
                SELECT revision_id FROM apify_route_active_slots
                WHERE workspace_id = ? AND route_id = ? AND revision_id IS NOT NULL
                """,
                (self.workspace_id, binding["route_id"]),
            ).fetchall()
            revision_ids = {str(row["revision_id"]) for row in rows}
            route = self._require_route(connection, str(binding["route_id"]))
            if len(revision_ids) < int(route["min_runtime_healthy"]):
                raise ActorOpsError(
                    "apify_actor_source_validation_incomplete",
                    "The route does not have its required active Actor revisions",
                    status_code=412,
                )
            succeeded = {
                str(row["revision_id"])
                for row in connection.execute(
                    """
                    SELECT revision_id FROM apify_actor_validations
                    WHERE workspace_id = ? AND route_id = ? AND source_id = ?
                      AND kind = 'source_canary' AND status = 'succeeded'
                      AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                      AND target_fingerprint = ?
                    """,
                    (
                        self.workspace_id,
                        binding["route_id"],
                        source_id,
                        binding["target_fingerprint"],
                    ),
                ).fetchall()
            }
            if str(route["admission_mode"]) == "compatibility":
                succeeded = {
                    str(row["revision_id"])
                    for row in connection.execute(
                        """
                        SELECT revision_id FROM apify_actor_validations
                        WHERE workspace_id = ? AND route_id = ?
                          AND kind = 'route_reference'
                          AND status = 'succeeded' AND cost_final = 1
                          AND semantic_outcome = 'valid_nonempty'
                        """,
                        (self.workspace_id, binding["route_id"]),
                    ).fetchall()
                }
            if not revision_ids <= succeeded:
                raise ActorOpsError(
                    "apify_actor_source_validation_incomplete",
                    "Every active Actor source Canary must succeed before activation",
                    status_code=412,
                )
            digest = revision_set_hash(
                {
                    str(row["slot_name"]): str(row["revision_id"])
                    for row in connection.execute(
                        """
                        SELECT slot_name, revision_id
                        FROM apify_route_active_slots
                        WHERE workspace_id = ? AND route_id = ?
                        """,
                        (self.workspace_id, binding["route_id"]),
                    ).fetchall()
                    if row["revision_id"]
                }
            )
            ready_status = (
                "ready_1of1"
                if len(revision_ids) == 1
                else "ready_3of3"
                if len(revision_ids) == 3
                else "ready_2of2"
            )
            if str(binding["validation_status"]) in _READY_BINDING_STATUSES:
                if str(binding["verified_revision_set_hash"] or "") != digest:
                    raise ActorOpsError(
                        "apify_actor_binding_generation_conflict",
                        "Source Actor binding changed; reload before retrying",
                    )
                replay = dict(binding)
                replay["_activation_replayed"] = True
                return replay
            if int(binding["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_binding_generation_conflict",
                    "Source Actor binding changed; reload before retrying",
                )
            cursor = connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET validation_status = ?,
                    verified_revision_set_hash = ?,
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND binding_id = ? AND generation = ?
                """,
                (
                    ready_status,
                    digest,
                    now,
                    self.workspace_id,
                    binding["binding_id"],
                    expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_binding_generation_conflict",
                    "Source Actor binding changed; reload before retrying",
                )
        result = self.get_source_binding(source_id)
        result["_activation_replayed"] = False
        return result

    def request_support_check(
        self,
        *,
        platform: str,
        target_type: str,
        capability: str,
        trigger_reason: str,
        expected_generation: int = 0,
        mode: Literal["primary", "fallback"] | None = None,
        budget_usd: float = ROUTE_CANARY_BUDGET_USD,
        max_recent_runs: int | None = None,
        max_pending_routes: int | None = None,
        force_discovery: bool = False,
    ) -> dict[str, Any]:
        platform = _capability_part(platform)
        target_type = _capability_part(target_type)
        capability = _capability_part(capability)
        supported_profile = _supported_route_profile(
            platform,
            target_type,
            capability,
        )
        route_key = supported_profile["route_key"]
        if mode is not None and mode != supported_profile["mode"]:
            raise ActorOpsError(
                "apify_actor_route_profile_unsupported",
                "This Actor Route mode does not match the supported profile",
                status_code=422,
            )
        reason = _safe_label(trigger_reason, 128)
        if not reason:
            raise ActorOpsError(
                "apify_actor_discovery_reason_invalid",
                "Discovery trigger reason is required",
                status_code=422,
            )
        budget = _bounded_cost(budget_usd, maximum=ROUTE_CANARY_BUDGET_USD)
        with self._write() as connection:
            if expected_generation != self.catalog_generation(
                connection=connection
            ):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor Route catalog changed; reload before retrying",
                )

            def assert_request_capacity(*, creates_route: bool) -> None:
                if max_recent_runs is not None:
                    cutoff = (
                        _as_utc(self._now()) - timedelta(days=1)
                    ).isoformat()
                    recent = int(
                        connection.execute(
                            """
                            SELECT COUNT(*)
                            FROM apify_actor_discovery_runs
                            WHERE workspace_id = ?
                              AND trigger_reason = 'member_support_check'
                              AND created_at >= ?
                            """,
                            (self.workspace_id, cutoff),
                        ).fetchone()[0]
                    )
                    if recent >= max(1, int(max_recent_runs)):
                        raise ActorOpsError(
                            "apify_actor_support_check_rate_limited",
                            "Daily Actor support-check limit reached",
                            retryable=True,
                            status_code=429,
                        )
                if creates_route and max_pending_routes is not None:
                    pending = sum(
                        1
                        for row in connection.execute(
                            """
                            SELECT route_id
                            FROM apify_actor_route_profiles
                            WHERE workspace_id = ?
                            """,
                            (self.workspace_id,),
                        ).fetchall()
                        if not self.source_capability_ready(
                            str(row["route_id"]),
                            connection=connection,
                        )
                    )
                    if pending >= max(1, int(max_pending_routes)):
                        raise ActorOpsError(
                            "apify_actor_support_check_capacity_reached",
                            "Pending Actor support-check capacity reached",
                            retryable=True,
                            status_code=429,
                        )
            existing = connection.execute(
                """
                SELECT route_id, generation
                FROM apify_actor_route_profiles
                WHERE workspace_id = ?
                  AND platform = ? AND target_type = ? AND capability = ?
                """,
                (self.workspace_id, platform, target_type, capability),
            ).fetchone()
            if existing is not None:
                public_route = self._safe_route_row(
                    self._require_route(connection, str(existing["route_id"]))
                )
                source_ready = self.source_capability_ready(
                    str(existing["route_id"]),
                    connection=connection,
                )
                if not source_ready or force_discovery:
                    pending = connection.execute(
                        """
                        SELECT run_id FROM apify_actor_discovery_runs
                        WHERE workspace_id = ? AND route_id = ?
                          AND stage IN (
                              'queued', 'searching', 'metadata', 'ranking',
                              'static_validation', 'input_validation',
                              'awaiting_canary_approval'
                          )
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (self.workspace_id, public_route["route_id"]),
                    ).fetchone()
                    if pending is None:
                        assert_request_capacity(creates_route=False)
                        run_id = f"apify-discovery-{uuid.uuid4().hex}"
                        now = self._now_iso()
                        connection.execute(
                            """
                            INSERT INTO apify_actor_discovery_runs (
                                run_id, workspace_id, route_id, stage,
                                trigger_reason, budget_usd, error_code,
                                query_count, ai_max_output_tokens,
                                created_at, updated_at
                            ) VALUES (
                                ?, ?, ?, 'queued', ?, ?, NULL, 0,
                                (SELECT max_output_tokens
                                 FROM apify_actor_discovery_settings
                                 WHERE workspace_id = ?), ?, ?
                            )
                            """,
                            (
                                run_id,
                                self.workspace_id,
                                public_route["route_id"],
                                reason,
                                budget,
                                self.workspace_id,
                                now,
                                now,
                            ),
                        )
                    else:
                        run_id = str(pending["run_id"])
                    return {
                        "kind": "discovery",
                        "route_id": public_route["route_id"],
                        "generation": public_route["generation"],
                        "support_status": public_route["status"],
                        "discovery_run_id": run_id,
                        "route": public_route,
                    }
                return {
                    "kind": "route",
                    "route_id": public_route["route_id"],
                    "generation": public_route["generation"],
                    "support_status": public_route["status"],
                    "discovery_run_id": None,
                    "route": public_route,
                }
            assert_request_capacity(creates_route=True)
            route_id = f"apify-route-{uuid.uuid4().hex}"
            run_id = f"apify-discovery-{uuid.uuid4().hex}"
            now = self._now_iso()
            connection.execute(
                """
                INSERT OR IGNORE INTO apify_actor_routes (
                    workspace_id, route_key, generation, status,
                    active_candidate_id, last_switch_reason, last_switch_at,
                    budget_blocked_until, blocked_reason, created_at, updated_at
                ) VALUES (?, ?, 1, 'blocked', NULL, 'support_check', ?,
                          NULL, 'discovery_required', ?, ?)
                """,
                (self.workspace_id, route_key, now, now, now),
            )
            connection.execute(
                """
                INSERT INTO apify_actor_route_profiles (
                    route_id, workspace_id, route_key, platform, target_type,
                    capability, mode, required_slots, min_runtime_healthy,
                    min_publishers, per_run_cap_usd, status,
                    metadata_check_interval_seconds, policy_version,
                    generation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 3, 2, 2, 0.02,
                          'discovery_required', 604800, 'actor_ops_v1', 1, ?, ?)
                """,
                (
                    route_id,
                    self.workspace_id,
                    route_key,
                    platform,
                    target_type,
                    capability,
                    supported_profile["mode"],
                    now,
                    now,
                ),
            )
            for slot_name in SLOT_NAMES:
                connection.execute(
                    """
                    INSERT INTO apify_route_active_slots (
                        workspace_id, route_id, slot_name, candidate_id,
                        revision_id, updated_at
                    ) VALUES (?, ?, ?, NULL, NULL, ?)
                    """,
                    (self.workspace_id, route_id, slot_name, now),
                )
            connection.execute(
                """
                INSERT INTO apify_actor_discovery_runs (
                    run_id, workspace_id, route_id, stage, trigger_reason,
                    budget_usd, error_code, query_count, ai_max_output_tokens,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, 'queued', ?, ?, NULL, 0,
                    (SELECT max_output_tokens
                     FROM apify_actor_discovery_settings
                     WHERE workspace_id = ?), ?, ?
                )
                """,
                (
                    run_id,
                    self.workspace_id,
                    route_id,
                    reason,
                    budget,
                    self.workspace_id,
                    now,
                    now,
                ),
            )
        public_route = self.get_route(route_id)
        discovery_run = self.get_discovery_run(run_id)
        return {
            "kind": "discovery",
            "route_id": route_id,
            "generation": int(public_route["generation"]),
            "support_status": str(public_route["status"]),
            "discovery_run_id": run_id,
            "route": public_route,
            "discovery_run": discovery_run,
        }

    def create_discovery_run(
        self,
        route_id: str,
        *,
        trigger_reason: str,
        expected_generation: int,
        budget_usd: float = ROUTE_CANARY_BUDGET_USD,
    ) -> dict[str, Any]:
        reason = _safe_label(trigger_reason, 128)
        budget = _bounded_cost(budget_usd, maximum=ROUTE_CANARY_BUDGET_USD)
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            run_id = f"apify-discovery-{uuid.uuid4().hex}"
            now = self._now_iso()
            connection.execute(
                """
                INSERT INTO apify_actor_discovery_runs (
                    run_id, workspace_id, route_id, stage, trigger_reason,
                    budget_usd, error_code, query_count, ai_max_output_tokens,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, 'queued', ?, ?, NULL, 0,
                    (SELECT max_output_tokens
                     FROM apify_actor_discovery_settings
                     WHERE workspace_id = ?), ?, ?
                )
                """,
                (
                    run_id,
                    self.workspace_id,
                    route_id,
                    reason,
                    budget,
                    self.workspace_id,
                    now,
                    now,
                ),
            )
        result = self.get_discovery_run(run_id)
        try:
            from .apify_actor_resilience import ApifyActorResilienceService

            ApifyActorResilienceService(
                self.store,
                workspace_id=self.workspace_id,
            ).emit_event(
                route_id=str(result["route_id"]),
                phase="discovery",
                outcome="queued",
                reason_code=reason,
            )
        except Exception:
            pass
        return result

    def create_discovery_measurements(
        self,
        *,
        expected_generation: int,
        max_output_tokens: int,
        route_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        if max_output_tokens not in {32768, 65536}:
            raise ActorOpsError(
                "apify_actor_discovery_measurement_limit_invalid",
                "AI capacity tests support only 32768 or 65536 output tokens",
                status_code=422,
            )
        allowed = {"youtube/channel/items", "instagram/profile/items"}
        normalized = tuple(dict.fromkeys(_safe_label(value, 128) for value in route_keys))
        if not normalized or set(normalized) - allowed:
            raise ActorOpsError(
                "apify_actor_route_profile_unsupported",
                "AI capacity tests support YouTube Channel and Instagram Profile only",
                status_code=422,
            )
        run_ids: list[str] = []
        with self._write() as connection:
            settings = connection.execute(
                """
                SELECT generation FROM apify_actor_discovery_settings
                WHERE workspace_id = ?
                """,
                (self.workspace_id,),
            ).fetchone()
            if settings is None or int(settings["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_discovery_settings_conflict",
                    "Actor discovery settings changed; reload before retrying",
                )
            for route_key in normalized:
                route = connection.execute(
                    """
                    SELECT route_id FROM apify_actor_route_profiles
                    WHERE workspace_id = ? AND route_key = ?
                    """,
                    (self.workspace_id, route_key),
                ).fetchone()
                if route is None:
                    raise ActorOpsError(
                        "apify_actor_route_not_found",
                        "Actor route was not found",
                        status_code=404,
                    )
                if max_output_tokens == 65536:
                    clipped = connection.execute(
                        """
                        SELECT 1 FROM apify_actor_discovery_runs
                        WHERE workspace_id = ? AND route_id = ?
                          AND measurement_mode = 1
                          AND ai_max_output_tokens = 32768
                          AND ai_finish_reason = 'length'
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (self.workspace_id, route["route_id"]),
                    ).fetchone()
                    if clipped is None:
                        raise ActorOpsError(
                            "apify_actor_discovery_measurement_retry_not_allowed",
                            "64K retry requires a clipped 32K measurement",
                            status_code=409,
                        )
                active = connection.execute(
                    """
                    SELECT 1 FROM apify_actor_discovery_runs
                    WHERE workspace_id = ? AND route_id = ?
                      AND stage IN ('queued','searching','metadata','ranking',
                                    'static_validation','input_validation')
                    LIMIT 1
                    """,
                    (self.workspace_id, route["route_id"]),
                ).fetchone()
                if active:
                    raise ActorOpsError(
                        "apify_actor_discovery_already_running",
                        "Actor discovery is already running for this route",
                        status_code=409,
                    )
                run_id = f"apify-discovery-{uuid.uuid4().hex}"
                now = self._now_iso()
                connection.execute(
                    """
                    INSERT INTO apify_actor_discovery_runs (
                        run_id, workspace_id, route_id, stage, trigger_reason,
                        budget_usd, query_count, measurement_mode,
                        ai_max_output_tokens, ai_json_status,
                        ai_manifest_status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'queued', 'admin_ai_measurement', 0,
                              0, 1, ?, 'unknown', 'not_run', ?, ?)
                    """,
                    (
                        run_id,
                        self.workspace_id,
                        route["route_id"],
                        max_output_tokens,
                        now,
                        now,
                    ),
                )
                run_ids.append(run_id)
        return [self.get_discovery_run(run_id) for run_id in run_ids]

    def apply_metadata_check(
        self,
        route_id: str,
        *,
        expected_generation: int,
        expected_revision_ids: tuple[str, ...],
        observed_fingerprints: Mapping[str, str],
        changes: Mapping[str, tuple[str, ...]],
        unsafe_revision_ids: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """Apply a bounded metadata fingerprint result after a CAS recheck."""

        expected = {str(value) for value in expected_revision_ids if value}
        if (
            not expected
            or set(observed_fingerprints) != expected
            or set(changes) - expected
            or set(unsafe_revision_ids) - expected
            or set(unsafe_revision_ids) - set(changes)
        ):
            raise ActorOpsError(
                "apify_actor_metadata_result_invalid",
                "Actor metadata result does not match its frozen Route",
                status_code=422,
            )
        if any(
            not _HEX_64_RE.fullmatch(str(value))
            for value in observed_fingerprints.values()
        ):
            raise ActorOpsError(
                "apify_actor_metadata_result_invalid",
                "Actor metadata fingerprint is invalid",
                status_code=422,
            )
        safe_changes: dict[str, tuple[str, ...]] = {}
        for revision_id, raw_codes in changes.items():
            codes = tuple(
                code
                for code in (
                    _safe_label(value, 128) for value in raw_codes
                )
                if code
            )
            if not codes:
                raise ActorOpsError(
                    "apify_actor_metadata_result_invalid",
                    "Actor metadata change requires a stable reason",
                    status_code=422,
                )
            safe_changes[str(revision_id)] = codes
        now = self._now_iso()
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            current = {
                str(row["revision_id"])
                for row in connection.execute(
                    """
                    SELECT slot.revision_id
                    FROM apify_route_active_slots AS slot
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = slot.workspace_id
                     AND revision.revision_id = slot.revision_id
                    WHERE slot.workspace_id = ? AND slot.route_id = ?
                      AND revision.lifecycle != 'legacy_builtin'
                    """,
                    (self.workspace_id, route_id),
                ).fetchall()
            }
            if (
                int(route["generation"]) != int(expected_generation)
                or current != expected
            ):
                return {
                    "status": "stale",
                    "proposal_run_id": None,
                    "runnable_count": None,
                }
            previous = {
                str(row["revision_id"]): str(row["fingerprint"])
                for row in connection.execute(
                    """
                    SELECT revision_id, fingerprint
                    FROM apify_actor_metadata_observations
                    WHERE workspace_id = ? AND route_id = ?
                    """,
                    (self.workspace_id, route_id),
                ).fetchall()
            }
            changed_fingerprints = {
                revision_id
                for revision_id, fingerprint in observed_fingerprints.items()
                if previous.get(revision_id) != str(fingerprint)
            }
            effective_changes = {
                revision_id: codes
                for revision_id, codes in safe_changes.items()
                if revision_id in changed_fingerprints
            }
            effective_unsafe = frozenset(unsafe_revision_ids).intersection(
                changed_fingerprints
            )
            for revision_id, fingerprint in observed_fingerprints.items():
                connection.execute(
                    """
                    INSERT INTO apify_actor_metadata_observations (
                        workspace_id, route_id, revision_id, fingerprint,
                        last_checked_at, last_changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, route_id, revision_id)
                    DO UPDATE SET
                        fingerprint = excluded.fingerprint,
                        last_checked_at = excluded.last_checked_at,
                        last_changed_at = CASE
                            WHEN fingerprint != excluded.fingerprint
                            THEN excluded.last_changed_at
                            ELSE last_changed_at END
                    """,
                    (
                        self.workspace_id,
                        route_id,
                        revision_id,
                        str(fingerprint),
                        now,
                        now,
                    ),
                )
            if not effective_changes:
                return {
                    "status": "unchanged",
                    "proposal_run_id": None,
                    "runnable_count": None,
                }

            newly_quarantined = 0
            for revision_id in effective_unsafe:
                revision = connection.execute(
                    """
                    SELECT candidate_id, lifecycle
                    FROM apify_actor_adapter_revisions
                    WHERE workspace_id = ? AND revision_id = ?
                    """,
                    (self.workspace_id, revision_id),
                ).fetchone()
                if revision is None:
                    continue
                if str(revision["lifecycle"]) != "quarantined":
                    cursor = connection.execute(
                        """
                        UPDATE apify_actor_adapter_revisions
                        SET lifecycle = 'quarantined'
                        WHERE workspace_id = ? AND revision_id = ?
                          AND lifecycle IN (
                              'static_valid', 'probationary', 'certified'
                          )
                        """,
                        (self.workspace_id, revision_id),
                    )
                    newly_quarantined += int(cursor.rowcount)
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET state = 'open', opened_at = COALESCE(opened_at, ?),
                        last_failure_at = ?, last_error_code = ?,
                        updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (
                        now,
                        now,
                        effective_changes.get(
                            revision_id,
                            ("apify_actor_metadata_unsafe",),
                        )[0],
                        now,
                        self.workspace_id,
                        revision["candidate_id"],
                    ),
                )

            runnable = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM apify_route_active_slots AS slot
                    JOIN apify_actor_candidates AS candidate
                      ON candidate.workspace_id = slot.workspace_id
                     AND candidate.id = slot.candidate_id
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = slot.workspace_id
                     AND revision.revision_id = slot.revision_id
                    WHERE slot.workspace_id = ? AND slot.route_id = ?
                      AND candidate.state IN (
                          'closed', 'half_open', 'probationary'
                      )
                      AND revision.lifecycle IN (
                          'certified', 'probationary', 'legacy_builtin'
                      )
                    """,
                    (self.workspace_id, route_id),
                ).fetchone()[0]
            )
            if newly_quarantined:
                profile_status = (
                    "ready"
                    if runnable >= int(route["min_runtime_healthy"])
                    else "candidate_shortfall"
                )
                compatibility_status = (
                    "ready"
                    if runnable == 3
                    else "degraded"
                    if runnable >= int(route["min_runtime_healthy"])
                    else "exhausted"
                )
                connection.execute(
                    """
                    UPDATE apify_actor_route_profiles
                    SET status = ?, generation = generation + 1,
                        updated_at = ?
                    WHERE workspace_id = ? AND route_id = ?
                    """,
                    (profile_status, now, self.workspace_id, route_id),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_routes
                    SET status = ?, generation = generation + 1,
                        blocked_reason = ?, updated_at = ?
                    WHERE workspace_id = ? AND route_key = ?
                    """,
                    (
                        compatibility_status,
                        (
                            None
                            if runnable >= int(route["min_runtime_healthy"])
                            else "candidate_shortfall"
                        ),
                        now,
                        self.workspace_id,
                        route["route_key"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE apify_source_route_bindings
                    SET validation_status = 'revalidation_pending',
                        generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND route_id = ?
                      AND validation_status IN ('ready_2of2', 'ready_3of3')
                    """,
                    (now, self.workspace_id, route_id),
                )

            pending = connection.execute(
                """
                SELECT run_id
                FROM apify_actor_discovery_runs
                WHERE workspace_id = ? AND route_id = ?
                  AND stage IN (
                      'queued', 'searching', 'metadata', 'ranking',
                      'static_validation', 'input_validation',
                      'awaiting_canary_approval'
                  )
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (self.workspace_id, route_id),
            ).fetchone()
            proposal_run_id = (
                str(pending["run_id"]) if pending is not None else None
            )
            if proposal_run_id is None:
                proposal_run_id = f"apify-discovery-{uuid.uuid4().hex}"
                first_code = sorted(
                    {
                        code
                        for codes in effective_changes.values()
                        for code in codes
                    }
                )[0]
                connection.execute(
                    """
                    INSERT INTO apify_actor_discovery_runs (
                        run_id, workspace_id, route_id, stage,
                        trigger_reason, budget_usd, error_code,
                        query_count, ai_max_output_tokens, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, 'queued', ?, 0.10, NULL, 0,
                        (SELECT max_output_tokens
                         FROM apify_actor_discovery_settings
                         WHERE workspace_id = ?), ?, ?
                    )
                    """,
                    (
                        proposal_run_id,
                        self.workspace_id,
                        route_id,
                        f"metadata:{first_code}"[:128],
                        self.workspace_id,
                        now,
                        now,
                    ),
                )
        return {
            "status": (
                "quarantined" if effective_unsafe else "proposal_created"
            ),
            "proposal_run_id": proposal_run_id,
            "runnable_count": runnable,
        }

    def get_discovery_run(self, run_id: str) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT run_id, route_id, stage, trigger_reason, budget_usd,
                   error_code, query_count, candidate_count,
                   rejection_summary_json, measurement_mode,
                   ai_max_output_tokens, ai_input_tokens,
                   ai_completion_tokens, ai_reasoning_tokens,
                   ai_content_tokens, ai_finish_reason, ai_latency_ms,
                   ai_response_bytes, ai_json_status, ai_manifest_status,
                   failure_phase, created_at, updated_at
            FROM apify_actor_discovery_runs
            WHERE workspace_id = ? AND run_id = ?
            """,
            (self.workspace_id, run_id),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_discovery_run_not_found",
                "Actor discovery run was not found",
                status_code=404,
            )
        result = dict(row)
        try:
            summary = json.loads(str(result.pop("rejection_summary_json") or "[]"))
        except (TypeError, json.JSONDecodeError):
            summary = []
        result["rejection_summary"] = (
            summary if isinstance(summary, list) else []
        )
        result["measurement_mode"] = bool(result["measurement_mode"])
        return result

    def record_discovery_ai_metrics(
        self,
        run_id: str,
        *,
        input_tokens: int | None = None,
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        content_tokens: int | None = None,
        finish_reason: str | None = None,
        latency_ms: int | None = None,
        response_bytes: int | None = None,
        json_status: str | None = None,
        manifest_status: str | None = None,
    ) -> dict[str, Any]:
        for value in (
            input_tokens,
            completion_tokens,
            reasoning_tokens,
            content_tokens,
            latency_ms,
            response_bytes,
        ):
            if value is not None and int(value) < 0:
                raise ActorOpsError(
                    "apify_actor_discovery_metrics_invalid",
                    "Actor discovery measurement metrics are invalid",
                    status_code=422,
                )
        if json_status not in {None, "valid", "empty", "invalid", "truncated", "unknown"}:
            raise ActorOpsError("apify_actor_discovery_metrics_invalid", "Invalid JSON status", status_code=422)
        if manifest_status not in {None, "valid", "invalid", "not_run", "unknown"}:
            raise ActorOpsError("apify_actor_discovery_metrics_invalid", "Invalid Manifest status", status_code=422)
        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE apify_actor_discovery_runs
                SET ai_input_tokens = COALESCE(?, ai_input_tokens),
                    ai_completion_tokens = COALESCE(?, ai_completion_tokens),
                    ai_reasoning_tokens = COALESCE(?, ai_reasoning_tokens),
                    ai_content_tokens = COALESCE(?, ai_content_tokens),
                    ai_finish_reason = COALESCE(?, ai_finish_reason),
                    ai_latency_ms = COALESCE(?, ai_latency_ms),
                    ai_response_bytes = COALESCE(?, ai_response_bytes),
                    ai_json_status = COALESCE(?, ai_json_status),
                    ai_manifest_status = COALESCE(?, ai_manifest_status),
                    updated_at = ?
                WHERE workspace_id = ? AND run_id = ?
                """,
                (
                    input_tokens, completion_tokens, reasoning_tokens,
                    content_tokens, _optional_label(finish_reason, 64),
                    latency_ms, response_bytes, json_status, manifest_status,
                    self._now_iso(), self.workspace_id, run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError("apify_actor_discovery_run_not_found", "Actor discovery run was not found", status_code=404)
        return self.get_discovery_run(run_id)

    def update_discovery_run(
        self,
        run_id: str,
        *,
        expected_stage: str,
        stage: str,
        query_count: int | None = None,
        error_code: str | None = None,
        candidate_count: int | None = None,
        rejections: tuple[Mapping[str, Any], ...] | None = None,
        failure_phase: str | None = None,
    ) -> dict[str, Any]:
        safe_stages = {
            "queued",
            "searching",
            "metadata",
            "ranking",
            "static_validation",
            "input_validation",
            "awaiting_canary_approval",
            "activation_ready",
            "canary_exhausted",
            "candidate_shortfall",
            "blocked_ai_unavailable",
            "failed",
        }
        if stage not in safe_stages or expected_stage not in safe_stages:
            raise ActorOpsError(
                "apify_actor_discovery_stage_invalid",
                "Actor discovery stage is invalid",
                status_code=422,
            )
        if query_count is not None and not 0 <= int(query_count) <= 3:
            raise ActorOpsError(
                "apify_actor_discovery_query_limit",
                "Actor discovery supports at most three searches",
                status_code=422,
            )
        if candidate_count is not None and not 0 <= int(candidate_count) <= 30:
            raise ActorOpsError(
                "apify_actor_discovery_candidate_count_invalid",
                "Actor discovery candidate count is invalid",
                status_code=422,
            )
        rejection_json: str | None = None
        if rejections is not None:
            counts: dict[str, int] = {}
            for row in rejections[:100]:
                reason = _optional_label(row.get("reason"), 128)
                if reason:
                    counts[reason] = counts.get(reason, 0) + 1
            rejection_json = json.dumps(
                [
                    {"reason": reason, "count": counts[reason]}
                    for reason in sorted(counts)
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        safe_error = _optional_label(error_code, 128)
        if failure_phase not in {None, "store", "metadata", "ai_generation", "static_validation", "input_validation"}:
            raise ActorOpsError("apify_actor_discovery_failure_phase_invalid", "Actor discovery failure phase is invalid", status_code=422)
        now = self._now_iso()
        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE apify_actor_discovery_runs
                SET stage = ?, query_count = COALESCE(?, query_count),
                    error_code = ?,
                    candidate_count = COALESCE(?, candidate_count),
                    rejection_summary_json = COALESCE(
                        ?, rejection_summary_json
                    ),
                    failure_phase = COALESCE(?, failure_phase),
                    updated_at = ?
                WHERE workspace_id = ? AND run_id = ? AND stage = ?
                """,
                (
                    stage,
                    query_count,
                    safe_error,
                    candidate_count,
                    rejection_json,
                    failure_phase,
                    now,
                    self.workspace_id,
                    run_id,
                    expected_stage,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_discovery_generation_conflict",
                    "Actor discovery run changed; reload before retrying",
                )
        result = self.get_discovery_run(run_id)
        try:
            from .apify_actor_resilience import ApifyActorResilienceService

            terminal_failure = stage in {
                "candidate_shortfall",
                "blocked_ai_unavailable",
                "canary_exhausted",
                "failed",
            }
            ApifyActorResilienceService(
                self.store,
                workspace_id=self.workspace_id,
            ).emit_event(
                route_id=str(result["route_id"]),
                phase=(
                    stage
                    if stage in {"static_validation", "input_validation"}
                    else "discovery"
                ),
                outcome="failed" if terminal_failure else "succeeded",
                reason_code=safe_error or stage,
                occurrence_count=max(int(candidate_count or 1), 1),
            )
        except Exception:
            pass
        return result

    def get_discovery_settings(self) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT enabled, secret_ref_id, call_limit, max_candidates,
                   max_output_tokens, generation, created_at, updated_at
            FROM apify_actor_discovery_settings
            WHERE workspace_id = ?
            """,
            (self.workspace_id,),
        ).fetchone()
        if row is None:
            raise ActorOpsError(
                "apify_actor_discovery_settings_not_found",
                "Actor discovery settings were not found",
                status_code=404,
            )
        return {
            "enabled": bool(row["enabled"]),
            "secret_ref_id": row["secret_ref_id"],
            "call_limit": int(row["call_limit"]),
            "max_candidates": int(row["max_candidates"]),
            "max_output_tokens": int(row["max_output_tokens"]),
            "generation": int(row["generation"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def patch_discovery_settings(
        self,
        *,
        expected_generation: int,
        enabled: bool | None = None,
        selected_secret_ref_id: str | None = None,
        call_limit: int | None = None,
        max_candidates: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        if call_limit is not None and not 1 <= int(call_limit) <= 3:
            raise ActorOpsError(
                "apify_actor_discovery_call_limit_invalid",
                "Actor discovery call limit must be between one and three",
                status_code=422,
            )
        if max_candidates is not None and not 3 <= int(max_candidates) <= 30:
            raise ActorOpsError(
                "apify_actor_discovery_candidate_limit_invalid",
                "Actor discovery candidate limit must be between 3 and 30",
                status_code=422,
            )
        if max_output_tokens is not None and not 4096 <= int(max_output_tokens) <= 65536:
            raise ActorOpsError(
                "apify_actor_discovery_output_limit_invalid",
                "Actor discovery output limit must be between 4096 and 65536",
                status_code=422,
            )
        now = self._now_iso()
        with self._write() as connection:
            current = connection.execute(
                """
                SELECT * FROM apify_actor_discovery_settings
                WHERE workspace_id = ?
                """,
                (self.workspace_id,),
            ).fetchone()
            if current is None or int(current["generation"]) != int(
                expected_generation
            ):
                raise ActorOpsError(
                    "apify_actor_discovery_settings_conflict",
                    "Actor discovery settings changed; reload before retrying",
                )
            selected_enabled = (
                int(enabled) if enabled is not None else int(current["enabled"])
            )
            selected_secret = (
                str(selected_secret_ref_id)
                if selected_secret_ref_id is not None
                else current["secret_ref_id"]
            )
            selected_limit = (
                int(call_limit) if call_limit is not None else int(current["call_limit"])
            )
            selected_candidates = (
                int(max_candidates)
                if max_candidates is not None
                else int(current["max_candidates"])
            )
            selected_output_tokens = (
                int(max_output_tokens)
                if max_output_tokens is not None
                else int(current["max_output_tokens"])
            )
            cursor = connection.execute(
                """
                UPDATE apify_actor_discovery_settings
                SET enabled = ?, ai_provider = '', ai_model = '',
                    secret_ref_id = ?, call_limit = ?, max_candidates = ?,
                    max_output_tokens = ?,
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND generation = ?
                """,
                (
                    selected_enabled,
                    selected_secret,
                    selected_limit,
                    selected_candidates,
                    selected_output_tokens,
                    now,
                    self.workspace_id,
                    expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_discovery_settings_conflict",
                    "Actor discovery settings changed; reload before retrying",
                )
        return self.get_discovery_settings()

    def discovery_measurement_summary(self) -> dict[str, Any]:
        connection = self.store.connect()
        profiles = (
            ("youtube/channel/items", "youtube"),
            ("instagram/profile/items", "instagram"),
        )
        latest: dict[str, Any] = {}
        successful_tokens: list[int] = []
        for route_key, label in profiles:
            row = connection.execute(
                """
                SELECT run.* FROM apify_actor_discovery_runs AS run
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = run.workspace_id
                 AND profile.route_id = run.route_id
                WHERE run.workspace_id = ? AND profile.route_key = ?
                  AND run.measurement_mode = 1
                ORDER BY run.created_at DESC LIMIT 1
                """,
                (self.workspace_id, route_key),
            ).fetchone()
            if row is None:
                latest[label] = None
                continue
            result = self.get_discovery_run(str(row["run_id"]))
            latest[label] = result
            if (
                result["stage"] == "awaiting_canary_approval"
                and result["ai_finish_reason"] != "length"
                and result["ai_completion_tokens"] is not None
                and result["ai_json_status"] == "valid"
                and result["ai_manifest_status"] == "valid"
            ):
                successful_tokens.append(int(result["ai_completion_tokens"]))
        recommended = None
        if len(successful_tokens) == 2:
            import math

            recommended = min(
                65536,
                max(8192, int(math.ceil(max(successful_tokens) * 1.5 / 1024) * 1024)),
            )
        return {
            "recommended_max_output_tokens": recommended,
            "measurements": latest,
        }

    def begin_attempt(
        self,
        snapshot: RouteExecutionSnapshot,
        slot: RouteSlotSnapshot,
        *,
        attempt_group_id: str,
        attempt_index: int,
        source_id: str | None = None,
        job_id: str | None = None,
    ) -> str:
        if slot not in snapshot.slots or not 1 <= int(attempt_index) <= 3:
            raise ActorOpsError(
                "apify_actor_attempt_invalid",
                "Actor attempt does not belong to the frozen route",
                status_code=422,
            )
        attempt_id = f"apify-attempt-{uuid.uuid4().hex}"
        now = self._now_iso()
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO apify_actor_attempts (
                    id, workspace_id, route_key, route_generation,
                    candidate_id, source_id, job_id, attempt_group_id,
                    attempt_index, status, semantic_outcome, reserved_usd,
                    actual_cost_usd, cost_final, last_error_code, created_at,
                    started_at, terminal_at, updated_at, adapter_revision_id,
                    build_id, build_number, manifest_hash, target_fingerprint
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', NULL, ?,
                    NULL, 0, NULL, ?, ?, NULL, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    attempt_id,
                    self.workspace_id,
                    snapshot.route_key,
                    snapshot.route_generation,
                    slot.candidate_id,
                    source_id or snapshot.source_id,
                    job_id,
                    _safe_label(attempt_group_id, 128),
                    attempt_index,
                    snapshot.per_run_cap_usd,
                    now,
                    now,
                    now,
                    slot.revision_id,
                    slot.build_id,
                    slot.build_number,
                    slot.manifest_hash,
                    snapshot.target_fingerprint,
                ),
            )
        return attempt_id

    def finish_attempt(
        self,
        attempt_id: str,
        *,
        status: Literal[
            "succeeded",
            "valid_empty",
            "actor_failed",
            "target_failed",
            "start_outcome_unknown",
            "cancelled",
        ],
        semantic_outcome: str,
        actual_cost_usd: float | None = None,
        error_code: str | None = None,
    ) -> None:
        if actual_cost_usd is not None:
            _bounded_actual_cost(actual_cost_usd, maximum=10_000.0)
        now = self._now_iso()
        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE apify_actor_attempts
                SET status = ?, semantic_outcome = ?, actual_cost_usd = ?,
                    cost_final = ?, last_error_code = ?, terminal_at = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND id = ? AND status = 'running'
                """,
                (
                    status,
                    _safe_label(semantic_outcome, 128),
                    actual_cost_usd,
                    int(actual_cost_usd is not None),
                    _optional_label(error_code, 128),
                    now,
                    now,
                    self.workspace_id,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ActorOpsError(
                    "apify_actor_attempt_conflict",
                    "Actor attempt is not running",
                )

    def finalized_actor_run_cost(self, attempt_id: str) -> float | None:
        """Return a terminal remote charge for one frozen logical attempt."""

        row = self.store.connect().execute(
            """
            SELECT charge_actual_usd
            FROM apify_actor_runs
            WHERE workspace_id = ? AND logical_run_id = ?
              AND charge_final = 1
              AND status IN (
                  'succeeded', 'failed', 'aborted', 'timed_out',
                  'start_rejected', 'cancelled'
              )
            ORDER BY terminal_at DESC, updated_at DESC, id DESC
            LIMIT 1
            """,
            (self.workspace_id, attempt_id),
        ).fetchone()
        if row is None or row["charge_actual_usd"] is None:
            return None
        return _bounded_actual_cost(
            float(row["charge_actual_usd"]),
            maximum=10_000.0,
        )

    def reconcile_proven_no_start_attempts(self) -> dict[str, int]:
        """Release ActorOps barriers after Apify proves no Run was created.

        The remote proof and Key-pool ledger transition happen in
        :class:`ApifyKeyPoolService`.  This idempotent local phase restores the
        Canary budget and Route state; it never contacts Apify and never queues
        a paid retry.
        """

        now = self._now_iso()
        attempts = 0
        validations = 0
        batches: set[str] = set()
        discovery_runs: set[str] = set()
        routes: set[tuple[str, str, int]] = set()
        with self._write() as connection:
            rows = connection.execute(
                """
                SELECT attempt.id AS attempt_id, attempt.job_id,
                       attempt.route_key, profile.route_id,
                       profile.min_runtime_healthy,
                       validation.validation_id,
                       validation.discovery_run_id,
                       item.batch_id
                FROM apify_actor_runs AS run
                JOIN apify_actor_attempts AS attempt
                  ON attempt.workspace_id = run.workspace_id
                 AND attempt.id = run.logical_run_id
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = attempt.workspace_id
                 AND profile.route_key = attempt.route_key
                LEFT JOIN apify_actor_validations AS validation
                  ON validation.workspace_id = attempt.workspace_id
                 AND validation.attempt_id = attempt.id
                LEFT JOIN apify_actor_canary_batch_items AS item
                  ON item.workspace_id = validation.workspace_id
                 AND item.validation_id = validation.validation_id
                WHERE run.workspace_id = ?
                  AND run.status = 'start_rejected'
                  AND run.last_error_code = 'apify_start_not_created'
                  AND run.charge_final = 1
                  AND run.charge_actual_usd = 0
                  AND attempt.status = 'start_outcome_unknown'
                ORDER BY run.terminal_at, run.id
                LIMIT 100
                """,
                (self.workspace_id,),
            ).fetchall()
            for row in rows:
                attempt_cursor = connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET status = 'cancelled',
                        semantic_outcome = 'apify_start_not_created',
                        actual_cost_usd = 0, cost_final = 1,
                        last_error_code = 'apify_start_not_created',
                        terminal_at = COALESCE(terminal_at, ?), updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                      AND status = 'start_outcome_unknown'
                    """,
                    (now, now, self.workspace_id, str(row["attempt_id"])),
                )
                attempts += int(attempt_cursor.rowcount)
                if row["validation_id"] is not None:
                    validation_cursor = connection.execute(
                        """
                        UPDATE apify_actor_validations
                        SET status = 'failed',
                            semantic_outcome = 'apify_start_not_created',
                            cost_usd = 0, cost_final = 1,
                            counts_toward_canary = 0,
                            completed_at = COALESCE(completed_at, ?)
                        WHERE workspace_id = ? AND validation_id = ?
                        """,
                        (now, self.workspace_id, str(row["validation_id"])),
                    )
                    validations += int(validation_cursor.rowcount)
                if row["batch_id"] is not None:
                    batch_id = str(row["batch_id"])
                    batches.add(batch_id)
                    connection.execute(
                        """
                        UPDATE apify_actor_canary_batch_items
                        SET status = 'failed',
                            semantic_outcome = 'apify_start_not_created',
                            actual_cost_usd = 0, cost_final = 1,
                            completed_at = COALESCE(completed_at, ?),
                            updated_at = ?
                        WHERE workspace_id = ? AND batch_id = ?
                          AND validation_id = ?
                          AND status = 'blocked_unknown_start'
                        """,
                        (
                            now,
                            now,
                            self.workspace_id,
                            batch_id,
                            str(row["validation_id"]),
                        ),
                    )
                if row["discovery_run_id"] is not None:
                    discovery_runs.add(str(row["discovery_run_id"]))
                if row["job_id"] is not None:
                    connection.execute(
                        """
                        UPDATE fetch_jobs
                        SET status = 'failed',
                            error_code = 'apify_start_not_created',
                            error_message = 'Apify confirmed that the Run was not created',
                            updated_at = ?
                        WHERE workspace_id = ? AND id = ?
                          AND status = 'succeeded'
                        """,
                        (now, self.workspace_id, str(row["job_id"])),
                    )
                routes.add(
                    (
                        str(row["route_id"]),
                        str(row["route_key"]),
                        int(row["min_runtime_healthy"]),
                    )
                )

            for batch_id in batches:
                batch = connection.execute(
                    """
                    SELECT batch.route_id, profile.min_runtime_healthy,
                           profile.min_publishers,
                           COALESCE(SUM(CASE WHEN item.cost_final = 1
                               THEN COALESCE(item.actual_cost_usd, 0)
                               ELSE 0 END), 0) AS actual_cost,
                           COUNT(*) AS item_count,
                           COALESCE(SUM(item.cost_final), 0) AS final_count
                    FROM apify_actor_canary_batches AS batch
                    JOIN apify_actor_canary_batch_items AS item
                      ON item.workspace_id = batch.workspace_id
                     AND item.batch_id = batch.batch_id
                    JOIN apify_actor_route_profiles AS profile
                      ON profile.workspace_id = batch.workspace_id
                     AND profile.route_id = batch.route_id
                    WHERE batch.workspace_id = ? AND batch.batch_id = ?
                    GROUP BY batch.route_id, profile.min_runtime_healthy,
                             profile.min_publishers
                    """,
                    (self.workspace_id, batch_id),
                ).fetchone()
                if batch is None:
                    continue
                proof = connection.execute(
                    """
                    SELECT COUNT(DISTINCT revision.actor_id) AS actors,
                           COUNT(DISTINCT lower(revision.publisher)) AS publishers
                    FROM apify_actor_validations AS validation
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = validation.workspace_id
                     AND revision.revision_id = validation.revision_id
                    WHERE validation.workspace_id = ?
                      AND validation.route_id = ?
                      AND validation.kind = 'route_reference'
                      AND validation.status = 'succeeded'
                      AND validation.semantic_outcome IN (
                          'valid_nonempty', 'valid_empty'
                      )
                    """,
                    (self.workspace_id, str(batch["route_id"])),
                ).fetchone()
                ready = (
                    int(proof["actors"] or 0)
                    >= int(batch["min_runtime_healthy"])
                    and int(proof["publishers"] or 0)
                    >= int(batch["min_publishers"])
                )
                connection.execute(
                    """
                    UPDATE apify_actor_canary_batches
                    SET status = ?, success_count = ?, publisher_count = ?,
                        actual_cost_usd = ?, cost_final = ?,
                        stop_reason = 'apify_start_not_created',
                        completed_at = COALESCE(completed_at, ?), updated_at = ?
                    WHERE workspace_id = ? AND batch_id = ?
                    """,
                    (
                        "activation_ready" if ready else "partial",
                        min(int(proof["actors"] or 0), 3),
                        min(int(proof["publishers"] or 0), 3),
                        float(batch["actual_cost"] or 0),
                        int(
                            int(batch["final_count"] or 0)
                            == int(batch["item_count"] or 0)
                        ),
                        now,
                        now,
                        self.workspace_id,
                        batch_id,
                    ),
                )

            for run_id in discovery_runs:
                run_minimum = connection.execute(
                    """
                    SELECT profile.min_runtime_healthy,
                           profile.min_publishers
                    FROM apify_actor_discovery_runs AS run
                    JOIN apify_actor_route_profiles AS profile
                      ON profile.workspace_id = run.workspace_id
                     AND profile.route_id = run.route_id
                    WHERE run.workspace_id = ? AND run.run_id = ?
                    """,
                    (self.workspace_id, run_id),
                ).fetchone()
                if run_minimum is None:
                    continue
                proof = connection.execute(
                    """
                    SELECT COUNT(DISTINCT revision.actor_id) AS actors,
                           COUNT(DISTINCT lower(revision.publisher)) AS publishers
                    FROM apify_actor_validations AS validation
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = validation.workspace_id
                     AND revision.revision_id = validation.revision_id
                    WHERE validation.workspace_id = ?
                      AND validation.discovery_run_id = ?
                      AND validation.kind = 'route_reference'
                      AND validation.status = 'succeeded'
                      AND validation.semantic_outcome IN (
                          'valid_nonempty', 'valid_empty'
                      )
                    """,
                    (self.workspace_id, run_id),
                ).fetchone()
                ready = (
                    int(proof["actors"] or 0)
                    >= int(run_minimum["min_runtime_healthy"])
                    and int(proof["publishers"] or 0)
                    >= int(run_minimum["min_publishers"])
                )
                connection.execute(
                    """
                    UPDATE apify_actor_discovery_runs
                    SET stage = ?, error_code = NULL, failure_phase = NULL,
                        updated_at = ?
                    WHERE workspace_id = ? AND run_id = ?
                      AND stage IN (
                          'awaiting_canary_approval', 'canary_exhausted',
                          'candidate_shortfall', 'activation_ready'
                      )
                    """,
                    (
                        "activation_ready" if ready else "awaiting_canary_approval",
                        now,
                        self.workspace_id,
                        run_id,
                    ),
                )

            for route_id, route_key, minimum in routes:
                runnable = self._count_runnable_slots(connection, route_id)
                profile_status = (
                    "ready" if runnable >= minimum else "discovery_required"
                )
                compatibility_status = (
                    "ready"
                    if runnable == 3
                    else "degraded"
                    if runnable >= minimum
                    else "blocked"
                )
                compatibility_reason = (
                    None if runnable >= minimum else "discovery_required"
                )
                connection.execute(
                    """
                    UPDATE apify_actor_route_profiles
                    SET status = ?, generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND route_id = ?
                      AND status = 'blocked_unknown_start'
                    """,
                    (profile_status, now, self.workspace_id, route_id),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_routes
                    SET status = ?, blocked_reason = ?,
                        generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND route_key = ?
                      AND blocked_reason IN (
                          'start_outcome_unknown',
                          'apify_start_outcome_unknown',
                          'apify_run_reconcile_required'
                      )
                    """,
                    (
                        compatibility_status,
                        compatibility_reason,
                        now,
                        self.workspace_id,
                        route_key,
                    ),
                )
        return {
            "attempts": attempts,
            "validations": validations,
            "batches": len(batches),
            "routes": len(routes),
        }

    def _resume_finalized_compatibility_stages(self, *, limit: int = 50) -> int:
        """Promote already-paid compatibility proof without another Actor POST."""

        rows = self.store.connect().execute(
            """
            SELECT validation.validation_id, batch.batch_id,
                   batch.pool_stage_id
            FROM apify_actor_validations AS validation
            JOIN apify_actor_canary_batch_items AS item
              ON item.workspace_id = validation.workspace_id
             AND item.validation_id = validation.validation_id
            JOIN apify_actor_canary_batches AS batch
              ON batch.workspace_id = item.workspace_id
             AND batch.batch_id = item.batch_id
            JOIN apify_actor_pool_stages AS stage
              ON stage.workspace_id = batch.workspace_id
             AND stage.stage_id = batch.pool_stage_id
            WHERE validation.workspace_id = ?
              AND batch.goal = 'compatibility_single'
              AND validation.status = 'succeeded'
              AND validation.semantic_outcome = 'valid_nonempty'
              AND validation.cost_final = 1
              AND stage.status IN (
                  'queued', 'validating_route', 'replan_required'
              )
            ORDER BY validation.completed_at, validation.validation_id
            LIMIT ?
            """,
            (self.workspace_id, min(max(int(limit), 1), 100)),
        ).fetchall()
        resumed = 0
        for row in rows:
            validation_id = str(row["validation_id"])
            batch_id = str(row["batch_id"])
            stage_id = str(row["pool_stage_id"])
            try:
                with self._write() as connection:
                    connection.execute(
                        """
                        UPDATE apify_actor_canary_batch_items
                        SET status = 'succeeded',
                            semantic_outcome = 'valid_nonempty',
                            cost_final = 1, updated_at = ?
                        WHERE workspace_id = ? AND batch_id = ?
                          AND validation_id = ?
                        """,
                        (
                            self._now_iso(),
                            self.workspace_id,
                            batch_id,
                            validation_id,
                        ),
                    )
                self.promote_compatibility_observation(
                    validation_id,
                    observed_fields=(
                        "identity",
                        "url",
                        "published_at",
                        "content",
                    ),
                )
                stage = self.prepare_compatibility_stage_activation(stage_id)
                if str(stage["status"]) == "apply_ready":
                    self.finalize_canary_batch(
                        batch_id,
                        stop_reason="staged_pool_apply_ready",
                    )
                    resumed += 1
            except Exception as exc:
                try:
                    from .apify_actor_resilience import (
                        ApifyActorResilienceService,
                    )

                    ApifyActorResilienceService(
                        self.store,
                        workspace_id=self.workspace_id,
                    ).emit_event(
                        phase="cost_reconciliation",
                        outcome="failed",
                        reason_code=str(
                            getattr(exc, "code", None)
                            or "compatibility_promotion_failed"
                        ),
                    )
                except Exception:
                    pass
        return resumed

    def reconcile_terminal_validation_costs(self) -> dict[str, int]:
        """Copy final remote charges into the attempt and validation ledgers.

        This recovery is local and idempotent. It never contacts Apify and
        never starts or retries an Actor.
        """

        attempts = 0
        validations = 0
        batch_items = 0
        batch_ids: set[str] = set()
        cost_events: list[dict[str, Any]] = []
        cycles = 0
        now = self._now_iso()
        with self._write() as connection:
            rows = connection.execute(
                """
                SELECT attempt.id AS attempt_id, attempt.candidate_id,
                       attempt.source_id AS attempt_source_id, attempt.job_id,
                       validation.validation_id, validation.route_id,
                       validation.source_id AS validation_source_id,
                       run.charge_actual_usd
                FROM apify_actor_attempts AS attempt
                JOIN apify_actor_validations AS validation
                  ON validation.workspace_id = attempt.workspace_id
                 AND validation.attempt_id = attempt.id
                JOIN apify_actor_runs AS run
                  ON run.workspace_id = attempt.workspace_id
                 AND run.logical_run_id = attempt.id
                WHERE attempt.workspace_id = ?
                  AND attempt.status <> 'running'
                  AND run.charge_final = 1
                  AND run.charge_actual_usd IS NOT NULL
                  AND (
                      attempt.cost_final = 0
                      OR attempt.actual_cost_usd IS NULL
                      OR validation.cost_usd IS NULL
                      OR validation.cost_final = 0
                      OR ABS(validation.cost_usd - run.charge_actual_usd)
                         > 0.000000001
                  )
                ORDER BY run.updated_at, run.id
                LIMIT 500
                """,
                (self.workspace_id,),
            ).fetchall()
            for row in rows:
                actual = _bounded_actual_cost(
                    float(row["charge_actual_usd"]),
                    maximum=10_000.0,
                )
                attempt_cursor = connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET actual_cost_usd = ?, cost_final = 1, updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                      AND status <> 'running'
                    """,
                    (actual, now, self.workspace_id, str(row["attempt_id"])),
                )
                validation_cursor = connection.execute(
                    """
                    UPDATE apify_actor_validations
                    SET cost_usd = ?, cost_final = 1
                    WHERE workspace_id = ? AND validation_id = ?
                      AND status IN ('succeeded', 'failed', 'cancelled')
                    """,
                    (
                        actual,
                        self.workspace_id,
                        str(row["validation_id"]),
                    ),
                )
                attempts += int(attempt_cursor.rowcount)
                validations += int(validation_cursor.rowcount)
                if int(validation_cursor.rowcount) == 1:
                    cost_events.append(
                        {
                            "route_id": str(row["route_id"]),
                            "source_id": (
                                str(row["validation_source_id"])
                                if row["validation_source_id"]
                                else str(row["attempt_source_id"])
                                if row["attempt_source_id"]
                                else None
                            ),
                            "candidate_id": str(row["candidate_id"]),
                            "job_id": (
                                str(row["job_id"]) if row["job_id"] else None
                            ),
                            "final_cost_usd": actual,
                        }
                    )
                item_rows = connection.execute(
                    """
                    SELECT batch_id
                    FROM apify_actor_canary_batch_items
                    WHERE workspace_id = ? AND validation_id = ?
                    """,
                    (self.workspace_id, str(row["validation_id"])),
                ).fetchall()
                item_cursor = connection.execute(
                    """
                    UPDATE apify_actor_canary_batch_items
                    SET actual_cost_usd = ?, cost_final = 1, updated_at = ?
                    WHERE workspace_id = ? AND validation_id = ?
                    """,
                    (
                        actual,
                        now,
                        self.workspace_id,
                        str(row["validation_id"]),
                    ),
                )
                batch_items += int(item_cursor.rowcount)
                batch_ids.update(str(item["batch_id"]) for item in item_rows)
            for batch_id in batch_ids:
                aggregate = connection.execute(
                    """
                    SELECT COALESCE(SUM(CASE WHEN cost_final = 1
                               THEN COALESCE(actual_cost_usd, 0)
                               ELSE 0 END), 0) AS actual_cost,
                           COUNT(*) AS item_count,
                           COALESCE(SUM(cost_final), 0) AS final_count
                    FROM apify_actor_canary_batch_items
                    WHERE workspace_id = ? AND batch_id = ?
                    """,
                    (self.workspace_id, batch_id),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE apify_actor_canary_batches
                    SET actual_cost_usd = ?, cost_final = ?, updated_at = ?
                    WHERE workspace_id = ? AND batch_id = ?
                    """,
                    (
                        float(aggregate["actual_cost"] or 0),
                        int(
                            int(aggregate["final_count"] or 0)
                            == int(aggregate["item_count"] or 0)
                        ),
                        now,
                        self.workspace_id,
                        batch_id,
                    ),
                )
            ready_cursor = connection.execute(
                """
                UPDATE apify_actor_discovery_runs
                SET stage = 'activation_ready', error_code = NULL,
                    failure_phase = NULL, updated_at = ?
                WHERE workspace_id = ?
                  AND stage IN (
                      'awaiting_canary_approval', 'canary_exhausted',
                      'candidate_shortfall'
                  )
                  AND run_id IN (
                      SELECT validation.discovery_run_id
                      FROM apify_actor_validations AS validation
                      JOIN apify_actor_adapter_revisions AS revision
                        ON revision.workspace_id = validation.workspace_id
                       AND revision.revision_id = validation.revision_id
                      JOIN apify_actor_discovery_runs AS run
                        ON run.workspace_id = validation.workspace_id
                       AND run.run_id = validation.discovery_run_id
                      JOIN apify_actor_route_profiles AS profile
                        ON profile.workspace_id = run.workspace_id
                       AND profile.route_id = run.route_id
                      WHERE validation.workspace_id = ?
                        AND validation.kind = 'route_reference'
                        AND validation.discovery_run_id IS NOT NULL
                        AND validation.status = 'succeeded'
                        AND validation.semantic_outcome IN (
                            'valid_nonempty', 'valid_empty'
                        )
                      GROUP BY validation.discovery_run_id,
                               profile.min_runtime_healthy,
                               profile.min_publishers
                      HAVING COUNT(DISTINCT revision.actor_id)
                                 >= profile.min_runtime_healthy
                         AND COUNT(DISTINCT lower(revision.publisher))
                                 >= profile.min_publishers
                  )
                """,
                (now, self.workspace_id, self.workspace_id),
            )
            exhausted_cursor = connection.execute(
                """
                UPDATE apify_actor_discovery_runs
                SET stage = 'canary_exhausted',
                    error_code = 'route_canary_attempts_exhausted',
                    failure_phase = NULL,
                    updated_at = ?
                WHERE workspace_id = ?
                  AND stage IN (
                      'awaiting_canary_approval', 'canary_exhausted'
                  )
                  AND run_id IN (
                      SELECT validation.discovery_run_id
                      FROM apify_actor_validations AS validation
                      JOIN apify_actor_adapter_revisions AS revision
                        ON revision.workspace_id = validation.workspace_id
                       AND revision.revision_id = validation.revision_id
                      JOIN apify_actor_discovery_runs AS run
                        ON run.workspace_id = validation.workspace_id
                       AND run.run_id = validation.discovery_run_id
                      JOIN apify_actor_route_profiles AS profile
                        ON profile.workspace_id = run.workspace_id
                       AND profile.route_id = run.route_id
                      WHERE validation.workspace_id = ?
                        AND validation.kind = 'route_reference'
                        AND validation.discovery_run_id IS NOT NULL
                      GROUP BY validation.discovery_run_id,
                               profile.min_runtime_healthy,
                               profile.min_publishers
                      HAVING SUM(validation.counts_toward_canary) >= ?
                         AND (
                           COUNT(DISTINCT CASE
                             WHEN validation.status = 'succeeded'
                              AND validation.semantic_outcome IN (
                                  'valid_nonempty', 'valid_empty'
                              )
                             THEN revision.actor_id END)
                               < profile.min_runtime_healthy
                           OR COUNT(DISTINCT CASE
                             WHEN validation.status = 'succeeded'
                              AND validation.semantic_outcome IN (
                                  'valid_nonempty', 'valid_empty'
                              )
                             THEN lower(revision.publisher) END)
                               < profile.min_publishers
                         )
                  )
                """,
                (
                    now,
                    self.workspace_id,
                    self.workspace_id,
                    ROUTE_CANARY_ATTEMPT_LIMIT,
                ),
            )
            cycles = int(ready_cursor.rowcount) + int(
                exhausted_cursor.rowcount
            )
        if cost_events:
            try:
                from .apify_actor_resilience import ApifyActorResilienceService

                resilience = ApifyActorResilienceService(
                    self.store,
                    workspace_id=self.workspace_id,
                )
                for event in cost_events:
                    resilience.emit_event(
                        phase="cost_reconciliation",
                        outcome="succeeded",
                        reason_code="validation_cost_finalized",
                        **event,
                    )
            except Exception:
                # Cost settlement is authoritative; diagnostics are best effort.
                pass
        cycles += self._resume_finalized_compatibility_stages()
        return {
            "attempts": attempts,
            "validations": validations,
            "batch_items": batch_items,
            "batches": len(batch_ids),
            "cycles": cycles,
        }

    async def execute_route(
        self,
        route_id: str,
        source_id: str | None,
        invoke: Callable[
            [RouteSlotSnapshot, RouteExecutionSnapshot],
            RouteInvocationResult[T]
            | Mapping[str, Any]
            | Awaitable[RouteInvocationResult[T] | Mapping[str, Any]],
        ],
        *,
        key_pool_generation: int | None = None,
        job_id: str | None = None,
        frozen_snapshot: RouteExecutionSnapshot | None = None,
    ) -> RouteExecutionResult[T]:
        """Invoke frozen slots strictly in order and fence a successful result."""

        if frozen_snapshot is None:
            snapshot = self.freeze_execution(
                route_id,
                source_id=source_id,
                key_pool_generation=key_pool_generation,
            )
        else:
            snapshot = frozen_snapshot
            if (
                snapshot.workspace_id != self.workspace_id
                or snapshot.route_id != route_id
                or snapshot.source_id != source_id
                or (
                    key_pool_generation is not None
                    and snapshot.key_pool_generation != key_pool_generation
                )
            ):
                raise ActorOpsError(
                    "apify_actor_snapshot_invalid",
                    "Frozen Actor route snapshot does not match this task",
                    status_code=422,
                )
        group_id = f"apify-group-{uuid.uuid4().hex}"
        attempt_ids: list[str] = []
        last_semantic = "actor_failed"

        def publication_value(
            value: T | None,
            *,
            slot: RouteSlotSnapshot,
            outcome: str,
            latest_published_at: str | None,
            latest_item_id: str | None,
        ) -> T | None:
            if not isinstance(value, list):
                return value
            from .apify_actor_route import ApifyActorRoutedList

            return ApifyActorRoutedList(
                value,
                route_generation=snapshot.route_generation,
                workspace_id=self.workspace_id,
                source_id=source_id,
                candidate_id=slot.candidate_id,
                latest_published_at=latest_published_at,
                latest_item_id=latest_item_id,
                semantic_outcome=outcome,
            )  # type: ignore[return-value]

        for index, slot in enumerate(snapshot.slots, start=1):
            attempt_id = self.begin_attempt(
                snapshot,
                slot,
                attempt_group_id=group_id,
                attempt_index=index,
                source_id=source_id,
                job_id=job_id,
            )
            attempt_ids.append(attempt_id)
            try:
                raw_result = invoke(
                    slot,
                    replace(snapshot, attempt_id=attempt_id),
                )
                if inspect.isawaitable(raw_result):
                    raw_result = await raw_result
                result = _coerce_invocation_result(raw_result)
            except ActorOpsError:
                self.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome="actor_exception",
                    error_code="apify_actor_invoke_failed",
                )
                self._record_actor_failure(
                    slot,
                    "apify_actor_invoke_failed",
                    source_id=source_id,
                )
                last_semantic = "actor_exception"
                continue
            except Exception:
                self.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome="actor_exception",
                    error_code="apify_actor_invoke_failed",
                )
                self._record_actor_failure(
                    slot,
                    "apify_actor_invoke_failed",
                    source_id=source_id,
                )
                last_semantic = "actor_exception"
                continue

            semantic = _safe_label(result.semantic_outcome, 128)
            last_semantic = semantic
            if result.failure_scope == "start_outcome_unknown":
                self.finish_unknown_start(
                    snapshot,
                    attempt_id=attempt_id,
                    semantic_outcome=semantic,
                    actual_cost_usd=result.cost_usd,
                    error_code=result.error_code or "apify_start_outcome_unknown",
                )
                raise ActorOpsError(
                    "apify_start_outcome_unknown",
                    "Actor start outcome is unknown; route and key are blocked",
                    retryable=False,
                    status_code=503,
                )
            if result.failure_scope == "key":
                self.finish_attempt(
                    attempt_id,
                    status="cancelled",
                    semantic_outcome=semantic,
                    actual_cost_usd=result.cost_usd,
                    error_code=result.error_code or "apify_key_unavailable",
                )
                raise ActorOpsError(
                    result.error_code or "apify_key_unavailable",
                    "Apify key is unavailable",
                    retryable=True,
                    status_code=503,
                )
            if result.failure_scope == "target":
                self.finish_attempt(
                    attempt_id,
                    status="target_failed",
                    semantic_outcome=semantic,
                    actual_cost_usd=result.cost_usd,
                    error_code=result.error_code,
                )
                self._record_target_failure(
                    snapshot,
                    slot,
                    semantic,
                )
                raise ActorOpsError(
                    result.error_code or "apify_actor_target_failed",
                    "Actor target is unavailable",
                    retryable=False,
                    status_code=422,
                )
            if result.failure_scope == "actor":
                self.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome=semantic,
                    actual_cost_usd=result.cost_usd,
                    error_code=result.error_code,
                )
                self._record_actor_failure(
                    slot,
                    result.error_code or "apify_actor_failed",
                    source_id=source_id,
                )
                continue
            freshness_outcome = semantic
            if source_id is not None:
                from .apify_actor_resilience import ApifyActorResilienceService

                freshness_outcome = ApifyActorResilienceService(
                    self.store,
                    workspace_id=self.workspace_id,
                ).classify_source_result(
                    source_id,
                    candidate_id=slot.candidate_id,
                    latest_published_at=result.latest_published_at,
                    latest_item_id=result.latest_item_id,
                    semantic_outcome=semantic,
                    defer_publication=True,
                )
            if freshness_outcome == "stale_regression":
                self.finish_attempt(
                    attempt_id,
                    status="target_failed",
                    semantic_outcome="stale_regression",
                    actual_cost_usd=result.cost_usd,
                    error_code="apify_actor_stale_regression",
                )
                # Freshness regressions are scoped to this source, not the Actor.
                self._record_target_failure(snapshot, slot, "stale_regression")
                last_semantic = "stale_regression"
                continue
            if freshness_outcome == "no_advance":
                self.finish_attempt(
                    attempt_id,
                    status="valid_empty",
                    semantic_outcome="no_advance",
                    actual_cost_usd=result.cost_usd,
                )
                self.assert_publishable(snapshot)
                return RouteExecutionResult(
                    value=publication_value(
                        result.value,
                        slot=slot,
                        outcome="no_advance",
                        latest_published_at=result.latest_published_at,
                        latest_item_id=result.latest_item_id,
                    ),
                    semantic_outcome="no_advance",
                    slot_name=slot.slot_name,
                    attempt_ids=tuple(attempt_ids),
                )
            if freshness_outcome == "advanced":
                semantic = "valid_nonempty"
                last_semantic = semantic
            if semantic == "suspicious_empty":
                self.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome=semantic,
                    actual_cost_usd=result.cost_usd,
                    error_code="apify_actor_suspicious_empty",
                )
                self._record_target_failure(snapshot, slot, semantic)
                continue
            if semantic not in {"valid_nonempty", "valid_empty"}:
                self.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome=semantic,
                    actual_cost_usd=result.cost_usd,
                    error_code="apify_actor_semantic_invalid",
                )
                self._record_actor_failure(
                    slot,
                    "apify_actor_semantic_invalid",
                    source_id=source_id,
                )
                continue
            self.finish_attempt(
                attempt_id,
                status=("valid_empty" if semantic == "valid_empty" else "succeeded"),
                semantic_outcome=semantic,
                actual_cost_usd=result.cost_usd,
            )
            self._record_actor_success(slot)
            self._record_target_success(snapshot, slot, semantic)
            self.assert_publishable(snapshot)
            return RouteExecutionResult(
                value=publication_value(
                    result.value,
                    slot=slot,
                    outcome=freshness_outcome,
                    latest_published_at=result.latest_published_at,
                    latest_item_id=result.latest_item_id,
                ),
                semantic_outcome=semantic,
                slot_name=slot.slot_name,
                attempt_ids=tuple(attempt_ids),
            )
        raise ActorOpsError(
            "apify_actor_route_exhausted",
            f"All runnable Actor slots failed ({last_semantic})",
            retryable=True,
            status_code=503,
        )

    def begin_validation_attempt(
        self,
        validation_id: str,
        snapshot: RouteExecutionSnapshot,
        slot: RouteSlotSnapshot,
        *,
        job_id: str,
    ) -> str:
        """Atomically attach a running attempt to one queued Canary."""

        with self._write():
            attempt_id = self.begin_attempt(
                snapshot,
                slot,
                attempt_group_id=f"canary:{validation_id}",
                attempt_index=1,
                source_id=snapshot.source_id,
                job_id=job_id,
            )
            self.record_validation(
                validation_id,
                status="running",
                attempt_id=attempt_id,
            )
        return attempt_id

    def reconcile_unfinished_attempts(self) -> dict[str, int]:
        """Fail closed after a Worker restart without replaying paid starts."""

        now = self._now_iso()
        cancelled = 0
        blocked = 0
        blocked_routes: set[tuple[str, str]] = set()
        with self._write() as connection:
            rows = connection.execute(
                """
                SELECT attempt.id, attempt.job_id, attempt.route_key,
                       profile.route_id,
                       GROUP_CONCAT(run.status) AS run_statuses
                FROM apify_actor_attempts AS attempt
                JOIN apify_actor_route_profiles AS profile
                  ON profile.workspace_id = attempt.workspace_id
                 AND profile.route_key = attempt.route_key
                LEFT JOIN apify_actor_runs AS run
                  ON run.workspace_id = attempt.workspace_id
                 AND run.logical_run_id = attempt.id
                WHERE attempt.workspace_id = ?
                  AND attempt.status = 'running'
                  AND attempt.adapter_revision_id IS NOT NULL
                GROUP BY attempt.id, attempt.job_id, attempt.route_key,
                         profile.route_id
                """,
                (self.workspace_id,),
            ).fetchall()
            for row in rows:
                statuses = {
                    value
                    for value in str(row["run_statuses"] or "").split(",")
                    if value
                }
                unsafe = any(
                    status not in APIFY_RUN_TERMINAL_STATUSES
                    for status in statuses
                )
                attempt_status = (
                    "start_outcome_unknown" if unsafe else "cancelled"
                )
                error_code = (
                    "apify_worker_restart_reconcile_required"
                    if unsafe
                    else "apify_worker_restart_result_lost"
                )
                connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET status = ?, semantic_outcome = ?,
                        last_error_code = ?, terminal_at = ?, updated_at = ?
                    WHERE workspace_id = ? AND id = ? AND status = 'running'
                    """,
                    (
                        attempt_status,
                        error_code,
                        error_code,
                        now,
                        now,
                        self.workspace_id,
                        row["id"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_validations
                    SET status = 'failed', semantic_outcome = ?,
                        completed_at = ?
                    WHERE workspace_id = ? AND attempt_id = ?
                      AND status = 'running'
                    """,
                    (error_code, now, self.workspace_id, row["id"]),
                )
                if row["job_id"]:
                    connection.execute(
                        """
                        UPDATE fetch_jobs
                        SET max_attempts = attempts, updated_at = ?
                        WHERE workspace_id = ? AND id = ?
                          AND status = 'running'
                        """,
                        (now, self.workspace_id, row["job_id"]),
                    )
                if unsafe:
                    blocked += 1
                    blocked_routes.add(
                        (str(row["route_id"]), str(row["route_key"]))
                    )
                else:
                    cancelled += 1
            for route_id, route_key in blocked_routes:
                connection.execute(
                    """
                    UPDATE apify_actor_route_profiles
                    SET status = 'blocked_unknown_start',
                        generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND route_id = ?
                    """,
                    (now, self.workspace_id, route_id),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_routes
                    SET status = 'blocked',
                        blocked_reason = 'start_outcome_unknown',
                        generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND route_key = ?
                    """,
                    (now, self.workspace_id, route_key),
                )
            if blocked_routes:
                connection.execute(
                    """
                    UPDATE apify_key_pool_state
                    SET status = 'blocked',
                        blocked_reason = 'start_outcome_unknown',
                        generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (now, self.workspace_id),
                )
        return {
            "cancelled": cancelled,
            "blocked": blocked,
            "routes_blocked": len(blocked_routes),
        }

    def _record_actor_failure(
        self,
        slot: RouteSlotSnapshot,
        error_code: str,
        *,
        source_id: str | None = None,
    ) -> None:
        now = self._now_iso()
        with self._write() as connection:
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = 'open',
                    failure_level = failure_level + 1,
                    failure_count = failure_count + 1,
                    last_attempt_at = ?, last_failure_at = ?,
                    last_error_code = ?, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (
                    now,
                    now,
                    _safe_label(error_code, 128),
                    now,
                    self.workspace_id,
                    slot.candidate_id,
                ),
            )
            if source_id:
                connection.execute(
                    """
                    UPDATE apify_source_route_bindings
                    SET preference_suspended_at = COALESCE(
                            preference_suspended_at, ?
                        ),
                        preference_recovery_successes = 0,
                        updated_at = ?
                    WHERE workspace_id = ? AND source_id = ?
                      AND preferred_candidate_id = ?
                    """,
                    (
                        now,
                        now,
                        self.workspace_id,
                        str(source_id),
                        slot.candidate_id,
                    ),
                )
            self._ensure_discovery_proposal(
                connection,
                slot,
                trigger_reason="runtime_candidate_shortfall",
            )

    def _record_target_success(
        self,
        snapshot: RouteExecutionSnapshot,
        slot: RouteSlotSnapshot,
        semantic_outcome: str,
    ) -> None:
        if snapshot.source_id is None:
            return
        now = self._now_iso()
        with self._write() as connection:
            connection.execute(
                """
                INSERT INTO apify_actor_target_health (
                    workspace_id, route_key, candidate_id, source_id,
                    had_valid_nonempty, consecutive_failures,
                    last_semantic_outcome, last_valid_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(workspace_id, route_key, candidate_id, source_id)
                DO UPDATE SET
                    had_valid_nonempty = MAX(
                        apify_actor_target_health.had_valid_nonempty,
                        excluded.had_valid_nonempty
                    ),
                    consecutive_failures = 0,
                    last_semantic_outcome = excluded.last_semantic_outcome,
                    last_valid_at = excluded.last_valid_at,
                    paused_until = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    self.workspace_id,
                    snapshot.route_key,
                    slot.candidate_id,
                    snapshot.source_id,
                    int(semantic_outcome == "valid_nonempty"),
                    semantic_outcome,
                    now,
                    now,
                ),
            )

    def _record_target_failure(
        self,
        snapshot: RouteExecutionSnapshot,
        slot: RouteSlotSnapshot,
        semantic_outcome: str,
    ) -> None:
        if snapshot.source_id is None:
            return
        now_dt = _as_utc(self._now())
        now = now_dt.isoformat()
        with self._write() as connection:
            existing = connection.execute(
                """
                SELECT consecutive_failures
                FROM apify_actor_target_health
                WHERE workspace_id = ? AND route_key = ?
                  AND candidate_id = ? AND source_id = ?
                """,
                (
                    self.workspace_id,
                    snapshot.route_key,
                    slot.candidate_id,
                    snapshot.source_id,
                ),
            ).fetchone()
            failures = (
                int(existing["consecutive_failures"] or 0) + 1
                if existing is not None
                else 1
            )
            paused_until = (
                (now_dt + timedelta(hours=6)).isoformat()
                if failures >= 2
                else None
            )
            connection.execute(
                """
                INSERT INTO apify_actor_target_health (
                    workspace_id, route_key, candidate_id, source_id,
                    consecutive_failures, last_semantic_outcome,
                    last_failure_at, paused_until, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, route_key, candidate_id, source_id)
                DO UPDATE SET
                    consecutive_failures = excluded.consecutive_failures,
                    last_semantic_outcome = excluded.last_semantic_outcome,
                    last_failure_at = excluded.last_failure_at,
                    paused_until = excluded.paused_until,
                    updated_at = excluded.updated_at
                """,
                (
                    self.workspace_id,
                    snapshot.route_key,
                    slot.candidate_id,
                    snapshot.source_id,
                    failures,
                    semantic_outcome,
                    now,
                    paused_until,
                    now,
                ),
            )

    def _ensure_discovery_proposal(
        self,
        connection: sqlite3.Connection,
        slot: RouteSlotSnapshot,
        *,
        trigger_reason: str,
    ) -> None:
        profile = connection.execute(
            """
            SELECT profile.route_id
            FROM apify_actor_route_profiles AS profile
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = profile.workspace_id
             AND candidate.route_key = profile.route_key
            WHERE candidate.workspace_id = ? AND candidate.id = ?
            """,
            (self.workspace_id, slot.candidate_id),
        ).fetchone()
        if profile is None:
            return
        runnable = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM apify_route_active_slots AS active_slot
                JOIN apify_actor_candidates AS candidate
                  ON candidate.id = active_slot.candidate_id
                WHERE active_slot.workspace_id = ?
                  AND active_slot.route_id = ?
                  AND candidate.state IN (
                      'closed', 'half_open', 'probationary'
                  )
                """,
                (self.workspace_id, profile["route_id"]),
            ).fetchone()[0]
        )
        pending = connection.execute(
            """
            SELECT 1 FROM apify_actor_discovery_runs
            WHERE workspace_id = ? AND route_id = ?
              AND stage IN (
                  'queued', 'searching', 'metadata', 'ranking',
                  'static_validation', 'input_validation',
                  'awaiting_canary_approval'
              )
            LIMIT 1
            """,
            (self.workspace_id, profile["route_id"]),
        ).fetchone()
        if runnable >= 3 or pending is not None:
            return
        now = self._now_iso()
        connection.execute(
            """
            INSERT INTO apify_actor_discovery_runs (
                run_id, workspace_id, route_id, stage,
                trigger_reason, budget_usd, error_code,
                query_count, ai_max_output_tokens, created_at, updated_at
            ) VALUES (
                ?, ?, ?, 'queued', ?, 0.10, NULL, 0,
                (SELECT max_output_tokens
                 FROM apify_actor_discovery_settings
                 WHERE workspace_id = ?), ?, ?
            )
            """,
            (
                f"apify-discovery-{uuid.uuid4().hex}",
                self.workspace_id,
                profile["route_id"],
                _safe_label(trigger_reason, 128),
                self.workspace_id,
                now,
                now,
            ),
        )

    def _record_actor_success(self, slot: RouteSlotSnapshot) -> None:
        now = self._now_iso()
        with self._write() as connection:
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET success_count = success_count + 1,
                    last_attempt_at = ?, last_success_at = ?,
                    last_error_code = NULL, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (now, now, now, self.workspace_id, slot.candidate_id),
            )
        self.promote_eligible_revisions(
            revision_ids=(slot.revision_id,),
            limit=1,
        )

    def _block_unknown_start(self, snapshot: RouteExecutionSnapshot) -> None:
        now = self._now_iso()
        with self._write() as connection:
            connection.execute(
                """
                UPDATE apify_actor_route_profiles
                SET status = 'blocked_unknown_start',
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND route_id = ?
                """,
                (now, self.workspace_id, snapshot.route_id),
            )
            connection.execute(
                """
                UPDATE apify_actor_routes
                SET status = 'blocked', blocked_reason = 'start_outcome_unknown',
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND route_key = ?
                """,
                (now, self.workspace_id, snapshot.route_key),
            )
            connection.execute(
                """
                UPDATE apify_key_pool_state
                SET status = 'blocked', blocked_reason = 'start_outcome_unknown',
                    generation = generation + 1, updated_at = ?
                WHERE workspace_id = ?
                """,
                (now, self.workspace_id),
            )

    def block_unknown_start(self, snapshot: RouteExecutionSnapshot) -> None:
        """Apply the complete route and Key-pool publication barrier."""

        self._block_unknown_start(snapshot)

    def finish_unknown_start(
        self,
        snapshot: RouteExecutionSnapshot,
        *,
        attempt_id: str,
        semantic_outcome: str,
        error_code: str,
        actual_cost_usd: float | None = None,
        validation_id: str | None = None,
    ) -> None:
        """Atomically freeze an unknown start and every paid-run barrier."""

        with self._write():
            self.finish_attempt(
                attempt_id,
                status="start_outcome_unknown",
                semantic_outcome=semantic_outcome,
                actual_cost_usd=actual_cost_usd,
                error_code=error_code,
            )
            if validation_id is not None:
                self.record_validation(
                    validation_id,
                    status="failed",
                    semantic_outcome=semantic_outcome,
                    attempt_id=attempt_id,
                    cost_usd=actual_cost_usd,
                )
            self._block_unknown_start(snapshot)


def _normalize_actor_id(value: str) -> str:
    normalized = str(value).strip().replace("~", "/")
    if not _ACTOR_ID_RE.fullmatch(normalized):
        raise ActorOpsError(
            "apify_actor_id_invalid",
            "Actor ID is invalid",
            status_code=422,
        )
    return normalized


def _manifest_has_explicit_item_identity(
    manifest: ActorManifestV1 | Mapping[str, Any],
) -> bool:
    parsed = parse_actor_manifest(manifest)
    markers = ("video", "post", "tweet", "item", "media", "short", "reel")

    def proves_item(mapping: Any) -> bool:
        return mapping is not None and any(
            any(
                marker in re.sub(r"[^a-z0-9]+", "", pointer.casefold())
                for marker in markers
            )
            for pointer in mapping.pointers
        )

    return proves_item(parsed.output.native_id) and proves_item(parsed.output.url)


def _safe_label(value: Any, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum or any(ord(character) < 0x20 for character in text):
        raise ActorOpsError(
            "apify_actor_value_invalid",
            "Actor control-plane value is invalid",
            status_code=422,
        )
    return text


def _optional_label(value: Any, maximum: int) -> str | None:
    if value is None:
        return None
    result = _safe_label(value, maximum)
    return result or None


def _capability_part(value: str) -> str:
    normalized = str(value).strip().casefold()
    if not _CAPABILITY_PART_RE.fullmatch(normalized):
        raise ActorOpsError(
            "apify_actor_capability_invalid",
            "Actor capability identifier is invalid",
            status_code=422,
        )
    return normalized


def _assert_manifest_route_hosts(
    manifest: ActorManifestV1,
    platform: str,
) -> None:
    allowed = _PLATFORM_OUTPUT_HOSTS.get(str(platform).casefold())
    if not allowed:
        raise ActorOpsError(
            "apify_actor_platform_unsupported",
            "Actor Manifest platform requires a controlled code extension",
            status_code=422,
        )
    if any(
        not any(host == root or host.endswith(f".{root}") for root in allowed)
        for host in manifest.semantics.url_host_allowlist
    ):
        raise ActorOpsError(
            "apify_actor_manifest_host_invalid",
            "Actor Manifest output host is outside the Route allowlist",
            status_code=422,
        )


def _bounded_cost(value: Any, *, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
        or float(value) > maximum
    ):
        raise ActorOpsError(
            "apify_actor_budget_invalid",
            "Actor operation budget is outside the allowed limit",
            status_code=422,
        )
    return round(float(value), 6)


def _bounded_actual_cost(value: Any, *, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
        or float(value) > maximum
    ):
        raise ActorOpsError(
            "apify_actor_cost_invalid",
            "Actor operation cost is outside the allowed limit",
            status_code=422,
        )
    return round(float(value), 6)


def _approval_key_hash(value: Any) -> str:
    approval_id = str(value or "").strip()
    if (
        not 16 <= len(approval_id) <= 128
        or re.fullmatch(r"[A-Za-z0-9._:-]+", approval_id) is None
    ):
        raise ActorOpsError(
            "apify_actor_approval_id_invalid",
            "Paid approval id is invalid",
            status_code=422,
        )
    return hashlib.sha256(approval_id.encode("utf-8")).hexdigest()


def _bounded_safe_json(value: Mapping[str, Any], *, max_bytes: int) -> str:
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise ActorOpsError(
            "apify_actor_metadata_invalid",
            "Actor metadata is not valid JSON",
            status_code=422,
        ) from None
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ActorOpsError(
            "apify_actor_metadata_too_large",
            "Actor metadata exceeds the size limit",
            status_code=422,
        )
    lowered = encoded.casefold()
    if any(
        marker in lowered
        for marker in (
            "authorization",
            "cookie",
            "password",
            "secret_value",
            "api_token",
            "dataset_id",
            "run_id",
            "readme",
        )
    ):
        raise ActorOpsError(
            "apify_actor_metadata_sensitive",
            "Actor metadata contains a forbidden field",
            status_code=422,
        )
    return encoded


def _pricing_exceeds_usd_cap(value: Any, cap_usd: float) -> bool:
    """Fail closed when immutable pricing contains an unsafe USD scalar."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(child, (Mapping, list, tuple)):
                if _pricing_exceeds_usd_cap(child, cap_usd):
                    return True
                continue
            if not str(key).casefold().endswith("usd") or child is None:
                continue
            if isinstance(child, bool) or not isinstance(child, (int, float)):
                return True
            numeric = float(child)
            if not math.isfinite(numeric) or numeric < 0 or numeric > cap_usd:
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_pricing_exceeds_usd_cap(child, cap_usd) for child in value)
    return False


def _safe_json(value: Any, fallback: T) -> Any | T:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback
    return decoded


def _actor_public_name(value: Any, publisher: Any, actor_id: Any) -> str:
    """Return a public label without falling back to the canonical Actor ID."""

    name = _optional_label(value, 160) or ""
    canonical_actor_id = str(actor_id or "").strip()
    if name and name.casefold() != canonical_actor_id.casefold():
        return name
    public_publisher = _optional_label(publisher, 120) or "商城"
    return f"{public_publisher} Actor"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _coerce_invocation_result(
    value: RouteInvocationResult[T] | Mapping[str, Any],
) -> RouteInvocationResult[T]:
    if isinstance(value, RouteInvocationResult):
        raw: Mapping[str, Any] = {
            "value": value.value,
            "semantic_outcome": value.semantic_outcome,
            "cost_usd": value.cost_usd,
            "failure_scope": value.failure_scope,
            "error_code": value.error_code,
            "latest_published_at": value.latest_published_at,
            "latest_item_id": value.latest_item_id,
        }
    elif isinstance(value, Mapping):
        raw = value
    else:
        raise ActorOpsError(
            "apify_actor_invocation_result_invalid",
            "Actor invocation returned an invalid result",
            status_code=502,
        )
    scope = str(raw.get("failure_scope") or "none")
    if scope not in {
        "none",
        "actor",
        "target",
        "key",
        "start_outcome_unknown",
    }:
        raise ActorOpsError(
            "apify_actor_invocation_result_invalid",
            "Actor invocation failure scope is invalid",
            status_code=502,
        )
    cost = raw.get("cost_usd")
    if cost is not None:
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            raise ActorOpsError(
                "apify_actor_invocation_result_invalid",
                "Actor invocation cost is invalid",
                status_code=502,
            )
        cost = float(cost)
    return RouteInvocationResult(
        value=raw.get("value"),
        semantic_outcome=str(raw.get("semantic_outcome") or "valid_nonempty"),
        cost_usd=cost,
        failure_scope=scope,  # type: ignore[arg-type]
        error_code=(
            str(raw["error_code"]) if raw.get("error_code") is not None else None
        ),
        latest_published_at=(
            str(raw["latest_published_at"])
            if raw.get("latest_published_at")
            else None
        ),
        latest_item_id=(
            str(raw["latest_item_id"]) if raw.get("latest_item_id") else None
        ),
    )


__all__ = [
    "ActorOpsError",
    "ApifyActorOpsService",
    "FIRST_ACTIVATION_CONFIRMATION",
    "PAID_CANARY_CONFIRMATION",
    "RouteExecutionResult",
    "RouteExecutionSnapshot",
    "RouteInvocationResult",
    "RouteScheduleGate",
    "RouteSlotSnapshot",
    "SLOT_NAMES",
    "revision_set_hash",
    "source_target_fingerprint",
]
