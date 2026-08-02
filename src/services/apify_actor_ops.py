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
from typing import Any, Awaitable, Callable, Generic, Iterator, Literal, Mapping, TypeVar

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
SOURCE_CANARY_BUDGET_USD = 0.06
MEMBER_SUPPORT_CHECKS_PER_DAY = 10
MEMBER_PENDING_DISCOVERY_ROUTES = 20
_RUNNABLE_CANDIDATE_STATES = frozenset({"closed", "half_open", "probationary"})
_READY_BINDING_STATUSES = frozenset({"ready_2of2", "ready_3of3"})
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
_ACTOR_ID_RE = re.compile(
    r"^(?:[A-Za-z0-9]{8,64}|"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,62})$"
)

T = TypeVar("T")


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


class ApifyActorOpsService:
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
                   candidate.state AS candidate_state,
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
        preferred.  When it is unavailable, two exact-Build revisions that
        each completed a successful Canary may be activated in degraded mode
        if they are different Actors from different publishers.  The third
        slot remains empty until a later, independently approved replacement
        is ready.
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
                        -current_matches,
                        lifecycle_cost,
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
        if best is None:
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
                        -current_matches,
                        lifecycle_cost,
                        sum(int(row["position"] or 0) for row in selected_pair),
                        *(row_order[str(row["revision_id"])] for row in selected_pair),
                        *(str(row["revision_id"]) for row in selected_pair),
                    )
                    if expedited_best is None or score < expedited_best[0]:
                        expedited_best = (score, selected_pair)

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
        if best is None and expedited_best is None:
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
        else:
            assert expedited_best is not None
            activation_mode = "expedited_2of3"
            selected = {
                "primary": expedited_best[1][0],
                "backup_1": expedited_best[1][1],
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
                   security_evidence_json, lifecycle, ai_provider, ai_model,
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
        # Revisions created before the explicit proof flag can still carry a
        # conservative, immutable proof: an exact output-schema hash, the
        # successful Build/input checks, and item-specific identity pointers.
        # This keeps Canary admission consistent with Discovery without
        # mutating an existing Revision or trusting a price-event label over
        # the exact Build contract.
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
            "per_run_cap_usd": float(row["per_run_cap_usd"]),
            "status": str(row["status"]),
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

    def replace_active_pool(
        self,
        route_id: str,
        *,
        slots: Mapping[str, str | None],
        expected_generation: int,
        rollback_revision_id: str | None = None,
        per_run_cap_usd: float | None = None,
    ) -> dict[str, Any]:
        if set(slots) != set(SLOT_NAMES):
            raise ActorOpsError(
                "apify_actor_active_pool_incomplete",
                "Active pool requires all three named slots",
                status_code=422,
            )
        requested_slots = {
            name: str(slots[name] or "") for name in SLOT_NAMES
        }
        populated_slot_names = [
            name for name in SLOT_NAMES if requested_slots[name]
        ]
        if len(populated_slot_names) not in {2, 3}:
            raise ActorOpsError(
                "apify_actor_active_pool_incomplete",
                "Active pool requires at least two populated slots",
                status_code=422,
            )
        selected_cap = (
            None
            if per_run_cap_usd is None
            else _bounded_cost(per_run_cap_usd, maximum=100.0)
        )
        now = self._now_iso()
        with self._write() as connection:
            route = self._require_route(connection, route_id)
            if int(route["generation"]) != int(expected_generation):
                raise ActorOpsError(
                    "apify_actor_route_generation_conflict",
                    "Actor route changed; reload before retrying",
                )
            old_slot_rows = connection.execute(
                """
                SELECT slot_name, candidate_id, revision_id
                FROM apify_route_active_slots
                WHERE workspace_id = ? AND route_id = ?
                """,
                (self.workspace_id, route_id),
            ).fetchall()
            old_slots = {
                str(row["slot_name"]): str(row["revision_id"] or "")
                for row in old_slot_rows
            }
            if rollback_revision_id is None and old_slots == requested_slots:
                if selected_cap is None or math.isclose(
                    selected_cap,
                    float(route["per_run_cap_usd"]),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    return self.get_route(route_id)
                connection.execute(
                    """
                    UPDATE apify_actor_route_profiles
                    SET generation = generation + 1,
                        per_run_cap_usd = ?, updated_at = ?
                    WHERE workspace_id = ? AND route_id = ?
                      AND generation = ?
                    """,
                    (
                        selected_cap,
                        now,
                        self.workspace_id,
                        route_id,
                        expected_generation,
                    ),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_routes
                    SET generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND route_key = ?
                    """,
                    (now, self.workspace_id, route["route_key"]),
                )
                return self.get_route(route_id)
            revision_rows: dict[str, sqlite3.Row] = {}
            for slot_name in populated_slot_names:
                row = connection.execute(
                    """
                    SELECT revision.*, candidate.route_key, candidate.state
                    FROM apify_actor_adapter_revisions AS revision
                    JOIN apify_actor_candidates AS candidate
                      ON candidate.id = revision.candidate_id
                    WHERE revision.workspace_id = ? AND revision.revision_id = ?
                    """,
                    (self.workspace_id, requested_slots[slot_name]),
                ).fetchone()
                if row is None or str(row["route_key"]) != str(route["route_key"]):
                    raise ActorOpsError(
                        "apify_actor_revision_not_found",
                        "Actor adapter revision was not found for this route",
                        status_code=404,
                    )
                revision_rows[slot_name] = row
            if rollback_revision_id is not None:
                selected_count = sum(
                    str(row["revision_id"]) == rollback_revision_id
                    for row in revision_rows.values()
                )
                rollback_slot = next(
                    (
                        slot_name
                        for slot_name, row in revision_rows.items()
                        if str(row["revision_id"]) == rollback_revision_id
                    ),
                    None,
                )
                rollback_row = next(
                    (
                        row
                        for row in revision_rows.values()
                        if str(row["revision_id"]) == rollback_revision_id
                    ),
                    None,
                )
                if (
                    selected_count != 1
                    or rollback_row is None
                    or str(rollback_row["lifecycle"])
                    not in {"superseded", "legacy_builtin"}
                ):
                    raise ActorOpsError(
                        "apify_actor_rollback_revision_invalid",
                        "Rollback requires one selected historical revision",
                        status_code=422,
                    )
                changed_slots = {
                    slot_name
                    for slot_name in SLOT_NAMES
                    if old_slots.get(slot_name, "")
                    != requested_slots[slot_name]
                }
                if changed_slots != {rollback_slot}:
                    raise ActorOpsError(
                        "apify_actor_rollback_scope_invalid",
                        "Rollback may change only the selected historical Revision slot",
                        status_code=422,
                    )
            actor_ids = {str(row["actor_id"]) for row in revision_rows.values()}
            publishers = {str(row["publisher"]).casefold() for row in revision_rows.values()}
            if len(actor_ids) != len(populated_slot_names):
                raise ActorOpsError(
                    "apify_actor_active_pool_duplicate",
                    "Active pool Actor IDs must be unique",
                    status_code=422,
                )
            if len(publishers) < int(route["min_publishers"]):
                raise ActorOpsError(
                    "apify_actor_active_pool_publishers",
                    "Active pool does not satisfy publisher diversity",
                    status_code=422,
                )
            effective_lifecycles: dict[str, str] = {}
            expedited = len(populated_slot_names) == 2
            for slot_name, row in revision_rows.items():
                lifecycle = str(row["lifecycle"])
                if (
                    lifecycle == "legacy_builtin"
                    and old_slots.get(slot_name) != str(row["revision_id"])
                    and str(row["revision_id"]) != str(
                        rollback_revision_id or ""
                    )
                ):
                    raise ActorOpsError(
                        "apify_actor_rollback_revision_required",
                        "Historical legacy revisions require an explicit rollback",
                        status_code=422,
                    )
                if lifecycle == "superseded":
                    if str(row["revision_id"]) != str(
                        rollback_revision_id or ""
                    ):
                        raise ActorOpsError(
                            "apify_actor_active_pool_uncertified",
                            "Superseded revisions require an explicit rollback",
                            status_code=422,
                        )
                    prior_lifecycle = str(
                        row["superseded_from_lifecycle"] or ""
                    )
                    allowed_prior = (
                        {"certified"}
                        if slot_name in {"primary", "backup_1"}
                        else {"certified", "probationary"}
                    )
                    if prior_lifecycle not in allowed_prior:
                        raise ActorOpsError(
                            "apify_actor_rollback_evidence_incomplete",
                            "Historical revision lacks the required certification evidence",
                            status_code=412,
                        )
                    lifecycle = prior_lifecycle
                allowed_lifecycle = (
                    {"certified", "probationary"}
                    if expedited
                    else {"certified", "legacy_builtin"}
                    if slot_name in {"primary", "backup_1"}
                    else {"certified", "probationary", "legacy_builtin"}
                )
                if lifecycle not in allowed_lifecycle:
                    raise ActorOpsError(
                        "apify_actor_active_pool_uncertified",
                        "Active pool lifecycle does not satisfy the 2+1 policy",
                        status_code=422,
                    )
                effective_lifecycles[slot_name] = lifecycle
                if str(row["lifecycle"]) != "legacy_builtin":
                    parsed = parse_actor_manifest(str(row["manifest_json"]))
                    if (
                        not row["build_id"]
                        or not row["build_number"]
                        or not row["manifest_hash"]
                    ):
                        raise ActorOpsError(
                            "apify_actor_active_pool_unpinned",
                            "Active pool revisions require an exact Build",
                            status_code=422,
                        )
                    if (
                        parsed.actor_id != str(row["actor_id"])
                        or parsed.build_number != str(row["build_number"])
                        or actor_manifest_hash(parsed) != str(row["manifest_hash"])
                    ):
                        raise ActorOpsError(
                            "apify_actor_revision_integrity_failed",
                            "Actor adapter revision failed its integrity check",
                            status_code=412,
                        )
                    _assert_manifest_route_hosts(parsed, str(route["platform"]))
            if rollback_revision_id is not None:
                rollback_row = next(
                    row
                    for row in revision_rows.values()
                    if str(row["revision_id"]) == rollback_revision_id
                )
                if str(rollback_row["lifecycle"]) == "superseded":
                    connection.execute(
                        """
                        UPDATE apify_actor_adapter_revisions
                        SET lifecycle = superseded_from_lifecycle
                        WHERE workspace_id = ? AND revision_id = ?
                          AND lifecycle = 'superseded'
                          AND superseded_from_lifecycle IN (
                              'probationary', 'certified'
                          )
                        """,
                        (
                            self.workspace_id,
                            rollback_revision_id,
                        ),
                    )
            replaced_revision_ids = {
                revision_id
                for revision_id in old_slots.values()
                if revision_id and revision_id not in set(requested_slots.values())
            }
            if replaced_revision_ids:
                placeholders = ",".join("?" for _ in replaced_revision_ids)
                connection.execute(
                    f"""
                    UPDATE apify_actor_adapter_revisions
                    SET superseded_from_lifecycle = lifecycle,
                        lifecycle = 'superseded',
                        superseded_at = ?
                    WHERE workspace_id = ?
                      AND revision_id IN ({placeholders})
                      AND lifecycle IN ('probationary', 'certified')
                    """,
                    (
                        now,
                        self.workspace_id,
                        *sorted(replaced_revision_ids),
                    ),
                )
            position_offset = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(position), 0) + 1
                    FROM apify_actor_candidates
                    WHERE workspace_id = ? AND route_key = ?
                    """,
                    (self.workspace_id, route["route_key"]),
                ).fetchone()[0]
            )
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = 'disabled', position = position + ?,
                    updated_at = ?
                WHERE workspace_id = ? AND route_key = ?
                """,
                (
                    position_offset,
                    now,
                    self.workspace_id,
                    route["route_key"],
                ),
            )
            for position, slot_name in enumerate(SLOT_NAMES):
                row = revision_rows.get(slot_name)
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO apify_route_active_slots (
                            workspace_id, route_id, slot_name, candidate_id,
                            revision_id, updated_at
                        ) VALUES (?, ?, ?, NULL, NULL, ?)
                        ON CONFLICT(route_id, slot_name) DO UPDATE SET
                            workspace_id = excluded.workspace_id,
                            candidate_id = NULL,
                            revision_id = NULL,
                            updated_at = excluded.updated_at
                        """,
                        (self.workspace_id, route_id, slot_name, now),
                    )
                    continue
                slot_unchanged = old_slots.get(slot_name) == str(
                    row["revision_id"]
                )
                selected_state = (
                    str(row["state"])
                    if slot_unchanged
                    else (
                        "probationary"
                        if effective_lifecycles[slot_name] == "probationary"
                        else "closed"
                    )
                )
                connection.execute(
                    """
                    INSERT INTO apify_route_active_slots (
                        workspace_id, route_id, slot_name, candidate_id,
                        revision_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(route_id, slot_name) DO UPDATE SET
                        workspace_id = excluded.workspace_id,
                        candidate_id = excluded.candidate_id,
                        revision_id = excluded.revision_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        self.workspace_id,
                        route_id,
                        slot_name,
                        row["candidate_id"],
                        row["revision_id"],
                        now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET state = ?, position = ?,
                        updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (
                        selected_state,
                        position,
                        now,
                        self.workspace_id,
                        row["candidate_id"],
                    ),
                )
            connection.execute(
                """
                UPDATE apify_actor_route_profiles
                SET generation = generation + 1,
                    status = CASE
                        WHEN status = 'blocked_unknown_start'
                        THEN status ELSE 'ready' END,
                    per_run_cap_usd = COALESCE(?, per_run_cap_usd),
                    updated_at = ?
                WHERE workspace_id = ? AND route_id = ? AND generation = ?
                """,
                (
                    selected_cap,
                    now,
                    self.workspace_id,
                    route_id,
                    expected_generation,
                ),
            )
            connection.execute(
                """
                UPDATE apify_actor_routes
                SET generation = generation + 1,
                    status = CASE
                        WHEN blocked_reason IN (
                            'start_outcome_unknown',
                            'apify_start_outcome_unknown',
                            'apify_run_reconcile_required'
                        ) THEN status ELSE 'ready' END,
                    blocked_reason = CASE
                        WHEN blocked_reason IN (
                            'start_outcome_unknown',
                            'apify_start_outcome_unknown',
                            'apify_run_reconcile_required'
                        ) THEN blocked_reason ELSE NULL END,
                    updated_at = ?
                WHERE workspace_id = ? AND route_key = ?
                """,
                (now, self.workspace_id, route["route_key"]),
            )
            if any(
                old_slots.get(name, "") != requested_slots[name]
                for name in SLOT_NAMES
            ):
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
            profile_status = "ready" if runnable >= 2 else "candidate_shortfall"
            compatibility_status = (
                "ready" if runnable == 3
                else "degraded" if runnable >= 2
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
                    None if runnable >= 2 else "candidate_shortfall",
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

    def source_capability_ready(
        self,
        route_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        """Return whether a Route can safely bind a new source.

        A full 2+1 pool is preferred. Expedited launch permits two
        Canary-proven exact-Build revisions from different publishers; source
        validation covers the revisions that are actually active.
        """

        active = connection or self.store.connect()
        route = active.execute(
            """
            SELECT status, min_publishers, min_runtime_healthy
            FROM apify_actor_route_profiles
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, route_id),
        ).fetchone()
        if route is None or str(route["status"]) != "ready":
            return False
        rows = active.execute(
            """
            SELECT slot.slot_name, slot.revision_id, revision.actor_id,
                   revision.publisher,
                   revision.lifecycle, revision.build_id,
                   revision.build_number, revision.manifest_hash,
                   candidate.state AS candidate_state
            FROM apify_route_active_slots AS slot
            LEFT JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = slot.workspace_id
             AND candidate.id = slot.candidate_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
            """,
            (self.workspace_id, route_id),
        ).fetchall()
        configured = [row for row in rows if row["revision_id"]]
        if len(configured) < int(route["min_runtime_healthy"]):
            return False
        actor_ids: set[str] = set()
        publishers: set[str] = set()
        for row in configured:
            if (
                str(row["lifecycle"] or "")
                not in {"probationary", "certified"}
                or str(row["candidate_state"] or "")
                not in _RUNNABLE_CANDIDATE_STATES
                or not row["actor_id"]
                or not row["publisher"]
                or not row["build_id"]
                or not row["build_number"]
                or not row["manifest_hash"]
            ):
                return False
            actor_ids.add(str(row["actor_id"]))
            publishers.add(str(row["publisher"]).casefold())
        return (
            len(actor_ids) == len(configured)
            and len(publishers) >= int(route["min_publishers"])
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
        if binding is not None:
            validation_status = str(binding["validation_status"])
            if validation_status in _READY_BINDING_STATUSES:
                expected_hash = revision_set_hash(
                    {
                        str(row["slot_name"]): str(row["revision_id"])
                        for row in rows
                        if row["revision_id"]
                    }
                )
                if str(binding["verified_revision_set_hash"] or "") != expected_hash:
                    validation_status = "revalidation_pending"
            if validation_status not in {
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
                else parse_actor_manifest(str(row["manifest_json"]))
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
            if len(frozen) < int(route["min_runtime_healthy"]):
                raise ActorOpsError(
                    "apify_actor_route_candidate_shortfall",
                    "At least two runnable Actor revisions are required",
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
            self._require_route(connection, route_id)
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
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending_validation', NULL, 1, ?, ?)
                    """,
                    (
                        binding_id,
                        self.workspace_id,
                        source_id,
                        route_id,
                        target_fingerprint,
                        mode,
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
                        validation_status = 'pending_validation',
                        verified_revision_set_hash = NULL,
                        generation = generation + 1, updated_at = ?
                    WHERE workspace_id = ? AND binding_id = ? AND generation = ?
                    """,
                    (
                        route_id,
                        target_fingerprint,
                        mode,
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

    def get_canary_plan(
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
                   profile.per_run_cap_usd, profile.min_publishers
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
            "activation_ready",
        }:
            raise ActorOpsError(
                "apify_actor_discovery_not_awaiting_approval",
                "Actor discovery run is not ready for a paid validation plan",
                status_code=409,
            )

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
              AND validation.discovery_run_id = ?
              AND validation.kind = 'route_reference'
            """,
            (self.workspace_id, str(run["route_id"]), run_id),
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
                   candidate.position, association.created_at
            FROM apify_actor_discovery_run_revisions AS association
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = association.workspace_id
             AND revision.revision_id = association.revision_id
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = revision.workspace_id
             AND candidate.id = revision.candidate_id
            WHERE association.workspace_id = ?
              AND association.run_id = ?
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
              AND NOT EXISTS (
                  SELECT 1
                  FROM apify_actor_validations AS attempted
                  WHERE attempted.workspace_id = revision.workspace_id
                    AND attempted.discovery_run_id = ?
                    AND attempted.revision_id = revision.revision_id
                    AND attempted.kind = 'route_reference'
                    AND attempted.counts_toward_canary = 1
              )
            ORDER BY candidate.position, association.created_at,
                     revision.revision_id
            """,
            (
                self.workspace_id,
                run_id,
                str(run["route_key"]),
                run_id,
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
        best_score: tuple[Any, ...] | None = None
        for size in range(1, maximum + 1):
            for option in combinations(candidates, size):
                actors = proven_actors | {str(row["actor_id"]) for row in option}
                publishers = proven_publishers | {
                    str(row["publisher"]).casefold() for row in option
                }
                reaches_two = len(actors) >= 2 and len(publishers) >= 2
                score: tuple[Any, ...] = (
                    0 if reaches_two else 1,
                    -size,
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
            len(proven_actors) >= 2 and len(proven_publishers) >= 2
        )
        reachable = activation_ready or (
            len(combined_actors) >= 2 and len(combined_publishers) >= 2
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

    def create_canary_batch(
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
                    "The current candidates cannot produce two safe providers",
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
                WHERE workspace_id = ? AND discovery_run_id = ?
                  AND status IN ('queued', 'preflighting', 'running')
                LIMIT 1
                """,
                (self.workspace_id, run_id),
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
                 AND validation.discovery_run_id = run.run_id
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
        return result

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
            _bounded_actual_cost(actual_cost_usd, maximum=0.02)
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
            ready = actor_count >= 2 and publisher_count >= 2
            batch_status = "activation_ready" if ready else "partial"
            # Batch counters are bounded by the three-item batch schema even
            # when older Route evidence contains more historical Actors.
            stored_actor_count = min(actor_count, BATCH_CANARY_MAX_CANDIDATES)
            stored_publisher_count = min(
                publisher_count,
                BATCH_CANARY_MAX_CANDIDATES,
            )
            final_cost = float(evidence["actual_cost"] or 0)
            all_final = int(evidence["final_count"] or 0) == int(
                evidence["item_count"] or 0
            )
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
                            "two_providers_ready"
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
        now = self._now_iso()
        with self._write() as connection:
            current = connection.execute(
                """
                SELECT status, kind, discovery_run_id, route_id, revision_id
                FROM apify_actor_validations
                WHERE workspace_id = ? AND validation_id = ?
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
                    and int(cycle["succeeded_actors"] or 0) >= 2
                    and int(cycle["succeeded_publishers"] or 0) >= 2
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
                        int(cycle["succeeded_actors"] or 0) < 2
                        or int(cycle["succeeded_publishers"] or 0) < 2
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
        return self.get_validation(validation_id)

    def get_validation(self, validation_id: str) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT validation_id, route_id, source_id, revision_id, kind,
                   status, semantic_outcome, cost_usd, cost_final,
                   counts_toward_canary, created_at, completed_at
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
                    "At least two active Actor revisions are required",
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
                "ready_3of3" if len(revision_ids) == 3 else "ready_2of2"
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
        return self.get_discovery_run(run_id)

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
        return self.get_discovery_run(run_id)

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

    def reconcile_terminal_validation_costs(self) -> dict[str, int]:
        """Copy final remote charges into the attempt and validation ledgers.

        This recovery is local and idempotent. It never contacts Apify and
        never starts or retries an Actor.
        """

        attempts = 0
        validations = 0
        cycles = 0
        now = self._now_iso()
        with self._write() as connection:
            rows = connection.execute(
                """
                SELECT attempt.id AS attempt_id,
                       validation.validation_id,
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
                      WHERE validation.workspace_id = ?
                        AND validation.kind = 'route_reference'
                        AND validation.discovery_run_id IS NOT NULL
                        AND validation.status = 'succeeded'
                        AND validation.semantic_outcome IN (
                            'valid_nonempty', 'valid_empty'
                        )
                      GROUP BY validation.discovery_run_id
                      HAVING COUNT(DISTINCT revision.actor_id) >= 2
                         AND COUNT(DISTINCT lower(revision.publisher)) >= 2
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
                      WHERE validation.workspace_id = ?
                        AND validation.kind = 'route_reference'
                        AND validation.discovery_run_id IS NOT NULL
                      GROUP BY validation.discovery_run_id
                      HAVING SUM(validation.counts_toward_canary) >= ?
                         AND (
                           COUNT(DISTINCT CASE
                             WHEN validation.status = 'succeeded'
                              AND validation.semantic_outcome IN (
                                  'valid_nonempty', 'valid_empty'
                              )
                             THEN revision.actor_id END) < 2
                           OR COUNT(DISTINCT CASE
                             WHEN validation.status = 'succeeded'
                              AND validation.semantic_outcome IN (
                                  'valid_nonempty', 'valid_empty'
                              )
                             THEN lower(revision.publisher) END) < 2
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
        return {
            "attempts": attempts,
            "validations": validations,
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
                self._record_actor_failure(slot, "apify_actor_invoke_failed")
                last_semantic = "actor_exception"
                continue
            except Exception:
                self.finish_attempt(
                    attempt_id,
                    status="actor_failed",
                    semantic_outcome="actor_exception",
                    error_code="apify_actor_invoke_failed",
                )
                self._record_actor_failure(slot, "apify_actor_invoke_failed")
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
                )
                continue
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
                self._record_actor_failure(slot, "apify_actor_semantic_invalid")
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
                value=result.value,
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


def _safe_json(value: Any, fallback: T) -> Any | T:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback
    return decoded


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
