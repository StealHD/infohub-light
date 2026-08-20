"""Offline, evidence-bound isolation for unrecoverable legacy Actor costs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from .legacy_cost_evidence import (
    LegacyEvidenceError,
    create_evidence,
    evidence_hash,
    opaque_fact_id,
    public_fact,
    unresolved_actions,
    validate_evidence,
)
from .legacy_cost_mutations import (
    LegacyCostMutationError,
    quarantine_attempt as _quarantine_attempt,
    quarantine_batch as _quarantine_batch,
    quarantine_run as _quarantine_run,
    settle_run as _settle_run,
)


RUN_QUARANTINE_CODE = "apify_historical_cost_quarantined"
ATTEMPT_QUARANTINE_CODE = "apify_historical_attempt_ledger_missing"
BATCH_QUARANTINE_CODE = "apify_historical_evidence_unrecoverable"


class LegacyCostAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteCostObservation:
    kind: Literal["found", "not_found", "unauthorized", "rate_limited", "unavailable"]
    actual_cost_usd: float | None = None

    @classmethod
    def found(cls, amount: float) -> "RemoteCostObservation":
        if amount < 0:
            raise ValueError("remote cost must not be negative")
        return cls("found", float(amount))

    @classmethod
    def not_found(cls) -> "RemoteCostObservation":
        return cls("not_found")


@dataclass(frozen=True)
class LegacyCostFact:
    identity: str
    action: str
    status: str
    updated_at: str
    amount_usd: float


@dataclass(frozen=True)
class LegacyCostReport:
    salt: str
    facts: tuple[LegacyCostFact, ...]
    counts: dict[str, int]
    upper_bound_usd: float
    remaining_remote_runs: int
    scanned_remote_identities: tuple[str, ...] = ()


class LegacyRunCostReader:
    """Minimal remote boundary: only a single authenticated GET per Run."""

    def read(self, remote_run_id: str) -> RemoteCostObservation:  # pragma: no cover - protocol shape
        raise NotImplementedError


def scan_legacy_costs(
    connection: sqlite3.Connection,
    reader: LegacyRunCostReader,
    *,
    limit: int = 20,
    salt: str,
    known_remote_fact_ids: set[str] | None = None,
    retry_remote_fact_ids: set[str] | None = None,
) -> LegacyCostReport:
    """Classify at most ``limit`` terminal remote Runs without writing facts."""

    if not salt or limit < 1 or limit > 20:
        raise ValueError("audit requires a non-empty salt and a limit from 1 through 20")
    facts: list[LegacyCostFact] = []
    remote_rows = _terminal_remote_runs(connection)
    known = known_remote_fact_ids or set()
    retry = retry_remote_fact_ids or set()
    unseen = [row for row in remote_rows if opaque_fact_id(salt, _remote_identity(row)) not in known]
    retry_rows = [
        row for row in remote_rows
        if opaque_fact_id(salt, _remote_identity(row)) in retry
    ]
    selected_rows = (retry_rows + [
        row for row in unseen if opaque_fact_id(salt, _remote_identity(row)) not in retry
    ])[:limit]
    for row in selected_rows:
        observation = reader.read(str(row["remote_run_id"]))
        facts.append(_remote_fact(row, observation))
    facts.extend(_local_blockers(connection))
    facts.extend(_eligible_batches(connection))
    counts = _counts(facts)
    return LegacyCostReport(
        salt=salt,
        facts=tuple(facts),
        counts=counts,
        upper_bound_usd=round(sum(fact.amount_usd for fact in facts if fact.action.startswith("quarantine")), 6),
        remaining_remote_runs=max(
            0,
            len(unseen) - sum(
                opaque_fact_id(salt, _remote_identity(row)) not in retry for row in selected_rows
            ),
        ),
        scanned_remote_identities=tuple(_remote_identity(row) for row in selected_rows),
    )


def build_evidence(report: LegacyCostReport) -> dict[str, object]:
    """Return a value-safe, deterministic proof record suitable for confirmation."""

    return create_evidence(
        salt=report.salt,
        facts=(
            public_fact(
                salt=report.salt,
                identity=fact.identity,
                action=fact.action,
                status=fact.status,
                updated_at=fact.updated_at,
                amount_usd=fact.amount_usd,
            )
            for fact in sorted(report.facts, key=lambda item: item.identity)
        ),
        remaining_remote_runs=report.remaining_remote_runs,
    )


def apply_evidence(
    connection: sqlite3.Connection,
    evidence: dict[str, object],
    *,
    expected_hash: str,
    confirmed_upper_bound_usd: float,
) -> dict[str, int]:
    """Apply only exact evidence; unknown observations and changed rows fail closed."""

    try:
        validate_evidence(evidence)
    except LegacyEvidenceError as error:
        raise LegacyCostAuditError(str(error)) from error
    if expected_hash != evidence_hash(evidence) or expected_hash != evidence.get("evidence_hash"):
        raise LegacyCostAuditError("evidence hash does not match the supplied proof")
    facts = evidence.get("facts")
    salt = evidence.get("salt")
    if not isinstance(facts, list) or not isinstance(salt, str) or not salt:
        raise LegacyCostAuditError("evidence has an invalid shape")
    if unresolved_actions(evidence):
        raise LegacyCostAuditError("evidence contains unresolved remote or inflight facts")
    upper_bound = float(evidence.get("upper_bound_usd", -1))
    if round(float(confirmed_upper_bound_usd), 6) != round(upper_bound, 6):
        raise LegacyCostAuditError("confirmed upper-bound does not match the evidence")
    current = _current_actions(connection, salt)
    selected: list[tuple[dict[str, object], LegacyCostFact]] = []
    for item in facts:
        if not isinstance(item, dict):
            raise LegacyCostAuditError("evidence fact has an invalid shape")
        fact = current.get((str(item.get("fact_id") or ""), str(item.get("action") or "")))
        if fact is None or not _matches(item, fact):
            raise LegacyCostAuditError("legacy fact changed after audit")
        selected.append((item, fact))
    result = {"settled_runs": 0, "quarantined_runs": 0, "quarantined_attempts": 0}
    stamp = datetime.now(timezone.utc).isoformat()
    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        for item, fact in selected:
            action = str(item["action"])
            if action == "provider_cost":
                _settle_run(connection, fact, float(item["amount_usd"]), stamp)
                result["settled_runs"] += 1
            elif action == "quarantine_run":
                _quarantine_run(connection, fact, stamp, RUN_QUARANTINE_CODE)
                result["quarantined_runs"] += 1
            elif action == "quarantine_attempt":
                _quarantine_attempt(connection, fact, stamp, ATTEMPT_QUARANTINE_CODE)
                result["quarantined_attempts"] += 1
            elif action == "quarantine_batch":
                _quarantine_batch(connection, fact, stamp, BATCH_QUARANTINE_CODE)
            elif action != "none":
                raise LegacyCostAuditError("unsupported evidence action")
        if owns_transaction:
            connection.commit()
    except LegacyCostMutationError as error:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise LegacyCostAuditError(str(error)) from error
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise
    return result


def validate_evidence_against_current(
    connection: sqlite3.Connection,
    evidence: dict[str, object],
    *,
    require_complete: bool,
) -> None:
    """Fail closed when a resumable proof no longer covers current legacy facts."""

    try:
        validate_evidence(evidence)
    except LegacyEvidenceError as error:
        raise LegacyCostAuditError(str(error)) from error
    if require_complete and int(evidence["remaining_remote_runs"]) != 0:
        raise LegacyCostAuditError("evidence has unscanned terminal remote Runs")
    if unresolved_actions(evidence):
        raise LegacyCostAuditError("evidence contains unresolved remote or inflight facts")
    salt = str(evidence["salt"])
    current = _current_actions(connection, salt)
    seen: set[tuple[str, str]] = set()
    for item in evidence["facts"]:
        assert isinstance(item, dict)
        key = (str(item["fact_id"]), str(item["action"]))
        fact = current.get(key)
        if fact is None or not _matches(item, fact):
            raise LegacyCostAuditError("legacy fact changed after audit")
        seen.add(key)
    for fact in _local_blockers(connection) + _eligible_batches(connection):
        key = (opaque_fact_id(salt, fact.identity), fact.action)
        if key not in seen:
            raise LegacyCostAuditError("new local legacy cost blocker requires a fresh audit")
    for row in _terminal_remote_runs(connection):
        fact_id = opaque_fact_id(salt, _remote_identity(row))
        if not any(item_id == fact_id for item_id, _ in seen):
            raise LegacyCostAuditError("new terminal remote Run requires a fresh audit")


def _terminal_remote_runs(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT id, remote_run_id, status, updated_at, charge_reserved_usd
           FROM apify_actor_runs
           WHERE charge_final=0 AND remote_run_id IS NOT NULL
             AND status IN ('succeeded','failed','aborted','timed_out','cancelled','start_rejected')
             AND COALESCE(last_error_code, '') != ?
           ORDER BY updated_at, id""",
        (RUN_QUARANTINE_CODE,),
    ).fetchall()


def _remote_fact(row: sqlite3.Row, observation: RemoteCostObservation) -> LegacyCostFact:
    identity = _remote_identity(row)
    if observation.kind == "found" and observation.actual_cost_usd is not None:
        return LegacyCostFact(identity, "provider_cost", str(row["status"]), str(row["updated_at"]), float(observation.actual_cost_usd))
    if observation.kind == "not_found":
        return LegacyCostFact(identity, "quarantine_run", str(row["status"]), str(row["updated_at"]), float(row["charge_reserved_usd"] or 0))
    return LegacyCostFact(identity, "remote_blocked", str(row["status"]), str(row["updated_at"]), float(row["charge_reserved_usd"] or 0))


def _local_blockers(connection: sqlite3.Connection) -> list[LegacyCostFact]:
    facts: list[LegacyCostFact] = []
    for row in connection.execute(
        """SELECT id, status, updated_at, charge_reserved_usd FROM apify_actor_runs
           WHERE charge_final=0 AND status IN ('reserved','starting','running','aborting','start_outcome_unknown')
           ORDER BY updated_at, id"""
    ):
        facts.append(LegacyCostFact(f"run:{row['id']}:{row['id']}", "nonterminal_run", str(row["status"]), str(row["updated_at"]), float(row["charge_reserved_usd"] or 0)))
    for row in connection.execute(
        """SELECT attempt.id, attempt.status, attempt.updated_at, attempt.reserved_usd
           FROM apify_actor_attempts AS attempt
           WHERE attempt.cost_final=0
             AND attempt.status NOT IN ('succeeded','valid_empty','actor_failed','target_failed','failed','cancelled')
           ORDER BY attempt.updated_at, attempt.id"""
    ):
        facts.append(LegacyCostFact(f"attempt:{row['id']}", "nonterminal_attempt", str(row["status"]), str(row["updated_at"]), float(row["reserved_usd"] or 0)))
    for row in connection.execute(
        """SELECT attempt.id, attempt.status, attempt.updated_at, attempt.reserved_usd
           FROM apify_actor_attempts AS attempt
           WHERE attempt.cost_final=0
             AND attempt.status IN ('succeeded','valid_empty','actor_failed','target_failed','failed','cancelled')
             AND COALESCE(attempt.last_error_code, '') != ?
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_runs AS run
                 WHERE run.logical_run_id=attempt.id AND run.remote_run_id IS NOT NULL
             )
           ORDER BY attempt.updated_at, attempt.id""",
        (ATTEMPT_QUARANTINE_CODE,),
    ):
        facts.append(LegacyCostFact(f"attempt:{row['id']}", "quarantine_attempt", str(row["status"]), str(row["updated_at"]), float(row["reserved_usd"] or 0)))
    return facts


def _eligible_batches(connection: sqlite3.Connection) -> list[LegacyCostFact]:
    facts: list[LegacyCostFact] = []
    rows = connection.execute(
        """SELECT batch_id, status, updated_at, max_total_charge_usd
           FROM apify_actor_canary_batches
           WHERE status='running' ORDER BY updated_at, batch_id"""
    ).fetchall()
    for row in rows:
        batch_id = str(row["batch_id"])
        active_job = connection.execute(
            """SELECT 1 FROM fetch_jobs
               WHERE job_type='apify_actor_canary_batch' AND status IN ('queued','running')
                 AND json_valid(payload_json)
                 AND json_extract(payload_json, '$.batch_id')=? LIMIT 1""",
            (batch_id,),
        ).fetchone()
        remote = connection.execute(
            """SELECT 1 FROM apify_actor_canary_batch_items AS item
               JOIN apify_actor_validations AS validation
                 ON validation.workspace_id=item.workspace_id AND validation.validation_id=item.validation_id
               JOIN apify_actor_runs AS run ON run.logical_run_id=validation.attempt_id
               WHERE item.batch_id=? AND run.status IN ('reserved','starting','running','aborting','start_outcome_unknown')
               LIMIT 1""",
            (batch_id,),
        ).fetchone()
        if not active_job and not remote:
            facts.append(LegacyCostFact(f"batch:{batch_id}", "quarantine_batch", str(row["status"]), str(row["updated_at"]), float(row["max_total_charge_usd"] or 0)))
    return facts


def _current_actions(
    connection: sqlite3.Connection, salt: str
) -> dict[tuple[str, str], LegacyCostFact]:
    facts = _local_blockers(connection) + _eligible_batches(connection)
    for row in _terminal_remote_runs(connection):
        identity = _remote_identity(row)
        facts.append(LegacyCostFact(identity, "provider_cost", str(row["status"]), str(row["updated_at"]), 0.0))
        facts.append(LegacyCostFact(identity, "quarantine_run", str(row["status"]), str(row["updated_at"]), float(row["charge_reserved_usd"] or 0)))
        facts.append(LegacyCostFact(identity, "remote_blocked", str(row["status"]), str(row["updated_at"]), float(row["charge_reserved_usd"] or 0)))
    return {(opaque_fact_id(salt, fact.identity), fact.action): fact for fact in facts}


def _matches(item: dict[str, object], fact: LegacyCostFact) -> bool:
    base = (
        str(item.get("action")) == fact.action
        and str(item.get("status")) == fact.status
        and str(item.get("updated_at")) == fact.updated_at
    )
    if fact.action == "provider_cost":
        return base and float(item.get("amount_usd", -1)) >= 0
    return base and round(float(item.get("amount_usd", -1)), 6) == round(fact.amount_usd, 6)


def _remote_identity(row: sqlite3.Row) -> str:
    return f"run:{row['id']}:{row['remote_run_id']}"


def _counts(facts: list[LegacyCostFact]) -> dict[str, int]:
    result: dict[str, int] = {}
    for fact in facts:
        result[fact.action] = result.get(fact.action, 0) + 1
    return dict(sorted(result.items()))
__all__ = [
    "ATTEMPT_QUARANTINE_CODE", "BATCH_QUARANTINE_CODE", "RUN_QUARANTINE_CODE",
    "LegacyCostAuditError", "LegacyCostReport", "LegacyRunCostReader",
    "RemoteCostObservation", "apply_evidence", "build_evidence", "scan_legacy_costs",
    "validate_evidence_against_current",
]
