"""Offline, evidence-bound isolation for unrecoverable legacy Actor costs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


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
) -> LegacyCostReport:
    """Classify at most ``limit`` terminal remote Runs without writing facts."""

    if not salt or limit < 1 or limit > 20:
        raise ValueError("audit requires a non-empty salt and a limit from 1 through 20")
    facts: list[LegacyCostFact] = []
    remote_rows = _terminal_remote_runs(connection)
    for row in remote_rows[:limit]:
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
        remaining_remote_runs=max(0, len(remote_rows) - min(limit, len(remote_rows))),
    )


def build_evidence(report: LegacyCostReport) -> dict[str, object]:
    """Return a value-safe, deterministic proof record suitable for confirmation."""

    facts = [
        {
            "fact_id": _opaque_id(report.salt, fact.identity),
            "action": fact.action,
            "status": fact.status,
            "updated_at": fact.updated_at,
            "amount_usd": fact.amount_usd,
        }
        for fact in sorted(report.facts, key=lambda item: item.identity)
    ]
    evidence: dict[str, object] = {
        "schema": "actorops_v2_legacy_cost_audit_v1",
        "salt": report.salt,
        "facts": facts,
        "counts": report.counts,
        "upper_bound_usd": report.upper_bound_usd,
        "remaining_remote_runs": report.remaining_remote_runs,
    }
    evidence["evidence_hash"] = _evidence_hash(evidence)
    return evidence


def apply_evidence(
    connection: sqlite3.Connection,
    evidence: dict[str, object],
    *,
    expected_hash: str,
    confirmed_upper_bound_usd: float,
) -> dict[str, int]:
    """Apply only exact evidence; unknown observations and changed rows fail closed."""

    if expected_hash != _evidence_hash(evidence) or expected_hash != evidence.get("evidence_hash"):
        raise LegacyCostAuditError("evidence hash does not match the supplied proof")
    facts = evidence.get("facts")
    salt = evidence.get("salt")
    if not isinstance(facts, list) or not isinstance(salt, str) or not salt:
        raise LegacyCostAuditError("evidence has an invalid shape")
    if any(str(item.get("action")) in {"remote_blocked", "nonterminal_run", "nonterminal_attempt"} for item in facts if isinstance(item, dict)):
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
                _quarantine_run(connection, fact, stamp)
                result["quarantined_runs"] += 1
            elif action == "quarantine_attempt":
                _quarantine_attempt(connection, fact, stamp)
                result["quarantined_attempts"] += 1
            elif action == "quarantine_batch":
                _quarantine_batch(connection, fact, stamp)
            elif action != "none":
                raise LegacyCostAuditError("unsupported evidence action")
        if owns_transaction:
            connection.commit()
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise
    return result


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
    identity = f"run:{row['id']}:{row['remote_run_id']}"
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
        identity = f"run:{row['id']}:{row['remote_run_id']}"
        facts.append(LegacyCostFact(identity, "provider_cost", str(row["status"]), str(row["updated_at"]), 0.0))
        facts.append(LegacyCostFact(identity, "quarantine_run", str(row["status"]), str(row["updated_at"]), float(row["charge_reserved_usd"] or 0)))
    return {(_opaque_id(salt, fact.identity), fact.action): fact for fact in facts}


def _matches(item: dict[str, object], fact: LegacyCostFact) -> bool:
    base = (
        str(item.get("action")) == fact.action
        and str(item.get("status")) == fact.status
        and str(item.get("updated_at")) == fact.updated_at
    )
    if fact.action == "provider_cost":
        return base and float(item.get("amount_usd", -1)) >= 0
    return base and round(float(item.get("amount_usd", -1)), 6) == round(fact.amount_usd, 6)


def _settle_run(
    connection: sqlite3.Connection, fact: LegacyCostFact, amount: float, stamp: str
) -> None:
    run_id = fact.identity.split(":", 2)[1]
    changed = connection.execute(
        """UPDATE apify_actor_runs SET charge_actual_usd=?, charge_final=1, updated_at=?
           WHERE id=? AND status=? AND updated_at=? AND charge_final=0
             AND remote_run_id IS NOT NULL""",
        (amount, stamp, run_id, fact.status, fact.updated_at),
    ).rowcount
    if changed != 1:
        raise LegacyCostAuditError("legacy run changed before exact settlement")
    connection.execute(
        """UPDATE apify_actor_attempts SET actual_cost_usd=?, cost_final=1, updated_at=?
           WHERE id=(SELECT logical_run_id FROM apify_actor_runs WHERE id=?)
             AND status IN ('succeeded','valid_empty','actor_failed','target_failed','failed','cancelled')
             AND cost_final=0""",
        (amount, stamp, run_id),
    )


def _quarantine_run(connection: sqlite3.Connection, fact: LegacyCostFact, stamp: str) -> None:
    run_id = fact.identity.split(":", 2)[1]
    changed = connection.execute(
        """UPDATE apify_actor_runs SET last_error_code=?, updated_at=?
           WHERE id=? AND status=? AND updated_at=? AND charge_final=0
             AND remote_run_id IS NOT NULL
             AND COALESCE(last_error_code, '') != ?""",
        (RUN_QUARANTINE_CODE, stamp, run_id, fact.status, fact.updated_at, RUN_QUARANTINE_CODE),
    ).rowcount
    if changed != 1:
        raise LegacyCostAuditError("legacy run changed before quarantine")
    connection.execute(
        """UPDATE apify_actor_attempts SET last_error_code=?, updated_at=?
           WHERE id=(SELECT logical_run_id FROM apify_actor_runs WHERE id=?)
             AND status IN ('succeeded','valid_empty','actor_failed','target_failed','failed','cancelled')
             AND cost_final=0""",
        (RUN_QUARANTINE_CODE, stamp, run_id),
    )


def _quarantine_attempt(connection: sqlite3.Connection, fact: LegacyCostFact, stamp: str) -> None:
    attempt_id = fact.identity.split(":", 1)[1]
    changed = connection.execute(
        """UPDATE apify_actor_attempts SET last_error_code=?, updated_at=?
           WHERE id=? AND status=? AND updated_at=? AND cost_final=0
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_runs AS run
                 WHERE run.logical_run_id=apify_actor_attempts.id
                   AND run.remote_run_id IS NOT NULL
             )
             AND COALESCE(last_error_code, '') != ?""",
        (ATTEMPT_QUARANTINE_CODE, stamp, attempt_id, fact.status, fact.updated_at, ATTEMPT_QUARANTINE_CODE),
    ).rowcount
    if changed != 1:
        raise LegacyCostAuditError("legacy attempt changed before quarantine")


def _quarantine_batch(connection: sqlite3.Connection, fact: LegacyCostFact, stamp: str) -> None:
    batch_id = fact.identity.split(":", 1)[1]
    connection.execute(
        """UPDATE apify_actor_validations SET status='failed', semantic_outcome=?, completed_at=COALESCE(completed_at, ?)
           WHERE validation_id IN (SELECT validation_id FROM apify_actor_canary_batch_items WHERE batch_id=?)
             AND status IN ('queued','running')""",
        (BATCH_QUARANTINE_CODE, stamp, batch_id),
    )
    connection.execute(
        """UPDATE apify_actor_canary_batch_items SET status='failed', semantic_outcome=?, completed_at=COALESCE(completed_at, ?), updated_at=?
           WHERE batch_id=? AND status IN ('planned','preflight_passed','queued','running','blocked_unknown_start')""",
        (BATCH_QUARANTINE_CODE, stamp, stamp, batch_id),
    )
    changed = connection.execute(
        """UPDATE apify_actor_canary_batches SET status='partial', stop_reason=?, completed_at=COALESCE(completed_at, ?), updated_at=?
           WHERE batch_id=? AND status=? AND updated_at=?
             AND NOT EXISTS (
                 SELECT 1 FROM fetch_jobs
                 WHERE job_type='apify_actor_canary_batch' AND status IN ('queued','running')
                   AND json_valid(payload_json)
                   AND json_extract(payload_json, '$.batch_id')=apify_actor_canary_batches.batch_id
             )
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_canary_batch_items AS item
                 JOIN apify_actor_validations AS validation
                   ON validation.workspace_id=item.workspace_id AND validation.validation_id=item.validation_id
                 JOIN apify_actor_runs AS run ON run.logical_run_id=validation.attempt_id
                 WHERE item.batch_id=apify_actor_canary_batches.batch_id
                   AND run.status IN ('reserved','starting','running','aborting','start_outcome_unknown')
             )""",
        (BATCH_QUARANTINE_CODE, stamp, stamp, batch_id, fact.status, fact.updated_at),
    ).rowcount
    if changed != 1:
        raise LegacyCostAuditError("legacy batch changed before quarantine")


def _counts(facts: list[LegacyCostFact]) -> dict[str, int]:
    result: dict[str, int] = {}
    for fact in facts:
        result[fact.action] = result.get(fact.action, 0) + 1
    return dict(sorted(result.items()))


def _opaque_id(salt: str, identity: str) -> str:
    return hashlib.sha256(f"{salt}:{identity}".encode("utf-8")).hexdigest()


def _evidence_hash(evidence: dict[str, object]) -> str:
    raw = {key: value for key, value in evidence.items() if key != "evidence_hash"}
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = [
    "ATTEMPT_QUARANTINE_CODE", "BATCH_QUARANTINE_CODE", "RUN_QUARANTINE_CODE",
    "LegacyCostAuditError", "LegacyCostReport", "LegacyRunCostReader",
    "RemoteCostObservation", "apply_evidence", "build_evidence", "scan_legacy_costs",
]
