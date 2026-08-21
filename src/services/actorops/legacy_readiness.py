"""Offline v1 evidence adapter used only to unlock a safe v2 cutover."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from ..apify_actor_source_proof import current_source_validation_ids


@dataclass(frozen=True, slots=True)
class LegacyBindingReadinessPlan:
    source_id: str
    binding_version: int
    target_fingerprint: str


@dataclass(frozen=True, slots=True)
class LegacyBindingReadinessReport:
    pending_bindings: int = 0
    planned_ready: int = 0
    legacy_mismatch: int = 0
    no_runnable_candidates: int = 0
    candidate_order_mismatch: int = 0
    missing_source_evidence: int = 0


def runnable_legacy_slot_revisions(
    connection: sqlite3.Connection, *, workspace_id: str, route_id: str
) -> tuple[str, ...]:
    """Return only exact revisions that the v1 runtime can currently invoke."""

    rows = connection.execute(
        """SELECT slot.revision_id
           FROM apify_route_active_slots AS slot
           JOIN apify_actor_candidates AS candidate
             ON candidate.workspace_id=slot.workspace_id AND candidate.id=slot.candidate_id
           JOIN apify_actor_adapter_revisions AS revision
             ON revision.workspace_id=slot.workspace_id AND revision.revision_id=slot.revision_id
           WHERE slot.workspace_id=? AND slot.route_id=?
             AND candidate.state IN ('closed','half_open','probationary')
             AND revision.lifecycle IN ('probationary','certified')
             AND revision.build_id IS NOT NULL AND revision.build_number IS NOT NULL
             AND revision.manifest_json IS NOT NULL AND revision.manifest_hash IS NOT NULL
           ORDER BY CASE slot.slot_name
             WHEN 'primary' THEN 0 WHEN 'backup_1' THEN 1 ELSE 2 END""",
        (workspace_id, route_id),
    ).fetchall()
    return tuple(str(row["revision_id"]) for row in rows)


def runnable_v2_candidate_revisions(
    connection: sqlite3.Connection, *, workspace_id: str, route_id: str
) -> tuple[str, ...]:
    """Return the frozen v2 order without exposing any Candidate internals."""

    rows = connection.execute(
        """SELECT candidate_id
           FROM actor_candidates_v2
           WHERE workspace_id=? AND route_id=?
             AND assignment_role IN ('active','standby')
             AND lifecycle IN ('probationary','certified')
             AND build_id IS NOT NULL AND build_number IS NOT NULL
             AND manifest_json IS NOT NULL AND manifest_hash IS NOT NULL
           ORDER BY CASE assignment_role WHEN 'active' THEN 0 ELSE 1 END,
                    priority, candidate_id""",
        (workspace_id, route_id),
    ).fetchall()
    return tuple(str(row["candidate_id"]) for row in rows)


def _ordered_mismatch(expected: tuple[str, ...], actual: tuple[str, ...]) -> bool:
    return expected != actual


def legacy_ready_binding_plans(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    route_id: str | None = None,
) -> tuple[tuple[LegacyBindingReadinessPlan, ...], LegacyBindingReadinessReport]:
    """Plan pending-to-ready promotions proved by current exact v1 source evidence."""

    where_route = " AND v2.route_id=?" if route_id is not None else ""
    values: tuple[Any, ...] = (workspace_id, route_id) if route_id is not None else (workspace_id,)
    rows = connection.execute(
        """SELECT v2.source_id, v2.route_id, v2.target_fingerprint,
                  v2.binding_version, v2.source_v1_generation,
                  v1.binding_id AS legacy_binding_id, v1.route_id AS legacy_route_id,
                  v1.target_fingerprint AS legacy_target_fingerprint,
                  v1.generation AS legacy_generation
           FROM actor_source_bindings_v2 AS v2
           LEFT JOIN apify_source_route_bindings AS v1
             ON v1.workspace_id=v2.workspace_id AND v1.binding_id=v2.binding_id
           WHERE v2.workspace_id=? AND v2.status='pending'""" + where_route + " ORDER BY v2.source_id",
        values,
    ).fetchall()
    pending = len(rows)
    plans: list[LegacyBindingReadinessPlan] = []
    legacy_mismatch = no_runnable = candidate_mismatch = missing_evidence = 0
    for row in rows:
        if (
            row["legacy_binding_id"] is None
            or str(row["legacy_route_id"]) != str(row["route_id"])
            or str(row["legacy_target_fingerprint"]) != str(row["target_fingerprint"])
            or int(row["legacy_generation"]) != int(row["source_v1_generation"])
        ):
            legacy_mismatch += 1
            continue
        expected = runnable_legacy_slot_revisions(
            connection, workspace_id=workspace_id, route_id=str(row["route_id"])
        )
        if not expected:
            no_runnable += 1
            continue
        actual = runnable_v2_candidate_revisions(
            connection, workspace_id=workspace_id, route_id=str(row["route_id"])
        )
        if _ordered_mismatch(expected, actual):
            candidate_mismatch += 1
            continue
        evidence = current_source_validation_ids(
            connection,
            workspace_id=workspace_id,
            route_id=str(row["route_id"]),
            source_id=str(row["source_id"]),
            target_fingerprint=str(row["target_fingerprint"]),
        )
        if not set(expected) <= evidence:
            missing_evidence += 1
            continue
        plans.append(
            LegacyBindingReadinessPlan(
                source_id=str(row["source_id"]),
                binding_version=int(row["binding_version"]),
                target_fingerprint=str(row["target_fingerprint"]),
            )
        )
    return tuple(plans), LegacyBindingReadinessReport(
        pending_bindings=pending,
        planned_ready=len(plans),
        legacy_mismatch=legacy_mismatch,
        no_runnable_candidates=no_runnable,
        candidate_order_mismatch=candidate_mismatch,
        missing_source_evidence=missing_evidence,
    )


def apply_legacy_ready_bindings(repository: Any, plans: tuple[LegacyBindingReadinessPlan, ...]) -> int:
    """Apply caller-reviewed plans through the repository's binding CAS."""

    repository._require_transaction()
    for plan in plans:
        repository.mark_binding_ready(
            plan.source_id,
            expected_binding_version=plan.binding_version,
            expected_target_fingerprint=plan.target_fingerprint,
        )
    return len(plans)


__all__ = [
    "LegacyBindingReadinessPlan",
    "LegacyBindingReadinessReport",
    "apply_legacy_ready_bindings",
    "legacy_ready_binding_plans",
    "runnable_legacy_slot_revisions",
    "runnable_v2_candidate_revisions",
]
