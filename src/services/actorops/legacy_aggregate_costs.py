"""Derive terminal v1 aggregate costs only from settled shared Run evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


EVIDENCE_SCHEMA = "actorops_v1_historical_aggregate_cost_v1"
_ATTEMPT_TERMINAL = frozenset(
    {"succeeded", "valid_empty", "actor_failed", "target_failed", "failed", "cancelled"}
)
_VALIDATION_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
_ITEM_TERMINAL = frozenset({"succeeded", "failed", "not_needed_no_charge"})
_BATCH_TERMINAL = frozenset({"activation_ready", "partial", "failed", "cancelled"})
_TABLE_ORDER = {
    "apify_actor_attempts": 0,
    "apify_actor_validations": 1,
    "apify_actor_canary_batch_items": 2,
    "apify_actor_canary_batches": 3,
}


class HistoricalCostFinalizationError(RuntimeError):
    """A historical cost cannot be finalized from exact local evidence."""


@dataclass(frozen=True)
class HistoricalCostFact:
    identity: str
    table: str
    key: tuple[object, ...]
    status: str
    version: str
    actual_column: str | None
    current_amount: float | None
    derived_amount: float | None
    action: str


@dataclass(frozen=True)
class HistoricalCostReport:
    salt: str
    facts: tuple[HistoricalCostFact, ...]

    @property
    def finalizable(self) -> tuple[HistoricalCostFact, ...]:
        return tuple(fact for fact in self.facts if fact.action == "finalize")

    @property
    def blockers(self) -> tuple[HistoricalCostFact, ...]:
        return tuple(fact for fact in self.facts if fact.action == "blocked")

    @property
    def finalizable_count(self) -> int:
        return len(self.finalizable)

    @property
    def blocker_count(self) -> int:
        return len(self.blockers)


def scan_historical_costs(
    connection: sqlite3.Connection, *, salt: str
) -> HistoricalCostReport:
    """Return a fixed-point, local-only proof plan for terminal v1 ledgers."""

    if not salt:
        raise ValueError("historical cost evidence requires a non-empty salt")
    tables = _tables(connection)
    facts: list[HistoricalCostFact] = []
    attempts = _attempt_amounts(connection, tables, facts)
    validations = _validation_amounts(connection, tables, facts, attempts)
    items = _item_amounts(connection, tables, facts, validations)
    _batch_amounts(connection, tables, facts, items)
    _unhandled_cost_blockers(connection, tables, facts)
    return HistoricalCostReport(salt=salt, facts=tuple(sorted(facts, key=_fact_sort_key)))


def build_evidence(report: HistoricalCostReport) -> dict[str, object]:
    """Create a redacted, deterministic proof session for an offline apply."""

    facts = [_public_fact(report.salt, fact) for fact in report.facts]
    counts = _counts(report.finalizable)
    evidence: dict[str, object] = {
        "schema": EVIDENCE_SCHEMA,
        "salt": report.salt,
        "facts": facts,
        "counts": counts,
        "finalizable_count": report.finalizable_count,
        "blocker_count": report.blocker_count,
    }
    evidence["evidence_hash"] = _evidence_hash(evidence)
    return evidence


def validate_evidence(evidence: dict[str, object]) -> dict[str, object]:
    """Validate the private evidence shape before it can gate a write."""

    if not isinstance(evidence, dict) or evidence.get("schema") != EVIDENCE_SCHEMA:
        raise HistoricalCostFinalizationError("historical cost evidence schema is invalid")
    salt = evidence.get("salt")
    facts = evidence.get("facts")
    if not isinstance(salt, str) or not salt or not isinstance(facts, list):
        raise HistoricalCostFinalizationError("historical cost evidence shape is invalid")
    normalized = [_normalize_public_fact(item) for item in facts]
    if len({str(item["fact_id"]) for item in normalized}) != len(normalized):
        raise HistoricalCostFinalizationError("historical cost evidence has duplicate facts")
    finalizable = [item for item in normalized if item["action"] == "finalize"]
    counts: dict[str, int] = {}
    for item in finalizable:
        table = str(item["table"])
        counts[table] = counts.get(table, 0) + 1
    if evidence.get("counts") != dict(sorted(counts.items())):
        raise HistoricalCostFinalizationError("historical cost evidence counts are invalid")
    if evidence.get("finalizable_count") != len(finalizable):
        raise HistoricalCostFinalizationError("historical cost evidence finalizable count is invalid")
    if evidence.get("blocker_count") != len(normalized) - len(finalizable):
        raise HistoricalCostFinalizationError("historical cost evidence blocker count is invalid")
    if evidence.get("evidence_hash") != _evidence_hash(evidence):
        raise HistoricalCostFinalizationError("historical cost evidence hash is invalid")
    return evidence


def apply_evidence(
    connection: sqlite3.Connection,
    evidence: dict[str, object],
    *,
    expected_hash: str,
    stamp: str | None = None,
) -> dict[str, int]:
    """CAS-finalize an unchanged complete proof; never rewrite a known amount."""

    validate_evidence(evidence)
    if expected_hash != evidence.get("evidence_hash"):
        raise HistoricalCostFinalizationError("evidence hash does not match the supplied proof")
    if int(evidence["blocker_count"]):
        raise HistoricalCostFinalizationError("historical cost evidence contains blockers")
    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        report = scan_historical_costs(connection, salt=str(evidence["salt"]))
        if build_evidence(report) != evidence:
            raise HistoricalCostFinalizationError("historical cost facts changed after scan")
        resolved_stamp = stamp or datetime.now(timezone.utc).isoformat()
        for fact in report.finalizable:
            _finalize_fact(connection, fact, stamp=resolved_stamp)
        remaining = scan_historical_costs(connection, salt=str(evidence["salt"]))
        if remaining.finalizable_count or remaining.blocker_count:
            raise HistoricalCostFinalizationError("historical cost finalization did not converge")
        if owns_transaction:
            connection.commit()
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise
    return _counts(report.finalizable)


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }


def _attempt_amounts(
    connection: sqlite3.Connection,
    tables: set[str],
    facts: list[HistoricalCostFact],
) -> dict[str, float]:
    values: dict[str, float] = {}
    if not {"apify_actor_attempts", "apify_actor_runs"} <= tables:
        return values
    rows = connection.execute(
        """SELECT id, status, actual_cost_usd, cost_final, updated_at
           FROM apify_actor_attempts ORDER BY updated_at, id"""
    ).fetchall()
    for row in rows:
        attempt_id = str(row["id"])
        current = _amount(row["actual_cost_usd"])
        if bool(row["cost_final"]):
            if str(row["status"]) in _ATTEMPT_TERMINAL and current is not None:
                values[attempt_id] = current
            continue
        amount = _settled_run_amount(connection, attempt_id)
        valid = (
            str(row["status"]) in _ATTEMPT_TERMINAL
            and amount is not None
            and (current is None or _same_amount(current, amount))
        )
        fact = _fact(
            f"attempt:{attempt_id}", "apify_actor_attempts", (attempt_id,), row,
            "actual_cost_usd", current, amount, "finalize" if valid else "blocked",
        )
        facts.append(fact)
        if valid and amount is not None:
            values[attempt_id] = amount
    return values


def _settled_run_amount(connection: sqlite3.Connection, attempt_id: str) -> float | None:
    rows = connection.execute(
        """SELECT remote_run_id, dataset_id, status, charge_reserved_usd,
                  charge_actual_usd, charge_final
           FROM apify_actor_runs WHERE logical_run_id=? ORDER BY id""",
        (attempt_id,),
    ).fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    amount = _amount(row["charge_actual_usd"])
    if (
        str(row["status"]) not in {"succeeded", "failed", "aborted", "timed_out", "cancelled", "start_rejected"}
        or not bool(row["charge_final"])
        or amount is None
    ):
        return None
    if row["remote_run_id"] is None and (
        str(row["status"]) != "start_rejected"
        or row["dataset_id"] is not None
        or not _same_amount(_amount(row["charge_reserved_usd"]) or 0.0, 0.0)
        or not _same_amount(amount, 0.0)
    ):
        return None
    return amount


def _validation_amounts(
    connection: sqlite3.Connection,
    tables: set[str],
    facts: list[HistoricalCostFact],
    attempts: dict[str, float],
) -> dict[str, float]:
    values: dict[str, float] = {}
    if "apify_actor_validations" not in tables:
        return values
    rows = connection.execute(
        """SELECT validation_id, attempt_id, status, cost_usd, cost_final,
                  created_at, completed_at
           FROM apify_actor_validations ORDER BY created_at, validation_id"""
    ).fetchall()
    for row in rows:
        validation_id = str(row["validation_id"])
        current = _amount(row["cost_usd"])
        if bool(row["cost_final"]):
            if str(row["status"]) in _VALIDATION_TERMINAL and current is not None:
                values[validation_id] = current
            continue
        attempt_id = str(row["attempt_id"]) if row["attempt_id"] is not None else None
        amount = attempts.get(attempt_id) if attempt_id else None
        if attempt_id is None and str(row["status"]) in {"failed", "cancelled"} and (current is None or _same_amount(current, 0.0)):
            amount = 0.0
        valid = (
            str(row["status"]) in _VALIDATION_TERMINAL
            and amount is not None
            and (current is None or _same_amount(current, amount))
        )
        facts.append(_fact(
            f"validation:{validation_id}", "apify_actor_validations", (validation_id,), row,
            "cost_usd", current, amount, "finalize" if valid else "blocked",
        ))
        if valid and amount is not None:
            values[validation_id] = amount
    return values


def _item_amounts(
    connection: sqlite3.Connection,
    tables: set[str],
    facts: list[HistoricalCostFact],
    validations: dict[str, float],
) -> dict[str, list[float | None]]:
    values: dict[str, list[float | None]] = {}
    if "apify_actor_canary_batch_items" not in tables:
        return values
    rows = connection.execute(
        """SELECT batch_id, ordinal, validation_id, status, actual_cost_usd,
                  cost_final, updated_at
           FROM apify_actor_canary_batch_items ORDER BY updated_at, batch_id, ordinal"""
    ).fetchall()
    for row in rows:
        batch_id = str(row["batch_id"])
        current = _amount(row["actual_cost_usd"])
        if bool(row["cost_final"]):
            values.setdefault(batch_id, []).append(
                current if str(row["status"]) in _ITEM_TERMINAL else None
            )
            continue
        amount = validations.get(str(row["validation_id"]))
        valid = (
            str(row["status"]) in _ITEM_TERMINAL
            and amount is not None
            and (current is None or _same_amount(current, amount))
        )
        facts.append(_fact(
            f"batch_item:{batch_id}:{row['ordinal']}", "apify_actor_canary_batch_items",
            (batch_id, int(row["ordinal"])), row, "actual_cost_usd", current, amount,
            "finalize" if valid else "blocked",
        ))
        values.setdefault(batch_id, []).append(amount if valid else None)
    return values


def _batch_amounts(
    connection: sqlite3.Connection,
    tables: set[str],
    facts: list[HistoricalCostFact],
    items: dict[str, list[float | None]],
) -> None:
    if "apify_actor_canary_batches" not in tables:
        return
    rows = connection.execute(
        """SELECT batch_id, status, planned_count, actual_cost_usd, cost_final, updated_at
           FROM apify_actor_canary_batches WHERE cost_final=0 ORDER BY updated_at, batch_id"""
    ).fetchall()
    for row in rows:
        batch_id = str(row["batch_id"])
        amounts = items.get(batch_id, [])
        settled_children = (
            bool(amounts)
            and len(amounts) == int(row["planned_count"])
            and all(value is not None for value in amounts)
        )
        child_amount = round(sum(value for value in amounts if value is not None), 6) if settled_children else None
        current = _amount(row["actual_cost_usd"])
        amount = (
            current
            if child_amount is not None and current is not None and current >= child_amount
            else child_amount if current is None else None
        )
        valid = (
            str(row["status"]) in _BATCH_TERMINAL
            and amount is not None
            and (current is None or _same_amount(current, amount))
        )
        facts.append(_fact(
            f"batch:{batch_id}", "apify_actor_canary_batches", (batch_id,), row,
            "actual_cost_usd", current, amount, "finalize" if valid else "blocked",
        ))


def _unhandled_cost_blockers(
    connection: sqlite3.Connection, tables: set[str], facts: list[HistoricalCostFact]
) -> None:
    for table, key_columns in (
        ("apify_actor_freshness_checks", ("check_id",)),
        ("apify_actor_freshness_results", ("check_id", "candidate_id")),
    ):
        if table not in tables:
            continue
        fields = ", ".join((*key_columns, "status", "cost_final"))
        for row in connection.execute(
            f"SELECT {fields} FROM {table} WHERE cost_final=0 ORDER BY {', '.join(key_columns)}"
        ):
            identity = f"{table}:{':'.join(str(row[column]) for column in key_columns)}"
            facts.append(HistoricalCostFact(
                identity=identity, table=table,
                key=tuple(row[column] for column in key_columns), status=str(row["status"]),
                version="", actual_column=None, current_amount=None, derived_amount=None,
                action="blocked",
            ))


def _fact(
    identity: str, table: str, key: tuple[object, ...], row: sqlite3.Row,
    column: str, current: float | None, derived: float | None, action: str,
) -> HistoricalCostFact:
    version = str(row["updated_at"] if "updated_at" in row.keys() else row["completed_at"] or row["created_at"])
    return HistoricalCostFact(
        identity=identity, table=table, key=key, status=str(row["status"]),
        version=version, actual_column=column, current_amount=current,
        derived_amount=derived, action=action,
    )


def _finalize_fact(connection: sqlite3.Connection, fact: HistoricalCostFact, *, stamp: str) -> None:
    assert fact.actual_column is not None and fact.derived_amount is not None
    key_columns = {
        "apify_actor_attempts": ("id",),
        "apify_actor_validations": ("validation_id",),
        "apify_actor_canary_batch_items": ("batch_id", "ordinal"),
        "apify_actor_canary_batches": ("batch_id",),
    }[fact.table]
    predicates = [f"{column}=?" for column in key_columns]
    values: list[object] = list(fact.key)
    predicates.extend(("status=?", "cost_final=0"))
    values.append(fact.status)
    if fact.current_amount is None:
        predicates.append(f"{fact.actual_column} IS NULL")
    else:
        predicates.append(f"{fact.actual_column}=?")
        values.append(fact.current_amount)
    set_values: list[object] = [fact.derived_amount]
    set_clause = f"{fact.actual_column}=?, cost_final=1"
    if fact.table != "apify_actor_validations":
        set_clause += ", updated_at=?"
        set_values.append(stamp)
    changed = connection.execute(
        f"UPDATE {fact.table} SET {set_clause} WHERE {' AND '.join(predicates)}",
        (*set_values, *values),
    ).rowcount
    if changed != 1:
        raise HistoricalCostFinalizationError("historical cost fact changed before finalization")


def _public_fact(salt: str, fact: HistoricalCostFact) -> dict[str, object]:
    return {
        "fact_id": _opaque_id(salt, fact.identity),
        "table": fact.table,
        "action": fact.action,
        "status": fact.status,
        "version": fact.version,
        "amount_usd": round(float(fact.derived_amount or 0.0), 6),
    }


def _normalize_public_fact(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HistoricalCostFinalizationError("historical cost evidence fact is invalid")
    fact_id = value.get("fact_id")
    table = value.get("table")
    action = value.get("action")
    status = value.get("status")
    version = value.get("version")
    amount = value.get("amount_usd")
    if (
        not isinstance(fact_id, str) or len(fact_id) != 64
        or table not in {*_TABLE_ORDER, "apify_actor_freshness_checks", "apify_actor_freshness_results"}
        or action not in {"finalize", "blocked"}
        or not isinstance(status, str) or not isinstance(version, str)
        or isinstance(amount, bool) or not isinstance(amount, (int, float)) or float(amount) < 0
    ):
        raise HistoricalCostFinalizationError("historical cost evidence fact has an invalid shape")
    return {
        "fact_id": fact_id, "table": table, "action": action, "status": status,
        "version": version, "amount_usd": round(float(amount), 6),
    }


def _counts(facts: tuple[HistoricalCostFact, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fact in facts:
        counts[fact.table] = counts.get(fact.table, 0) + 1
    return dict(sorted(counts.items()))


def _fact_sort_key(fact: HistoricalCostFact) -> tuple[int, str]:
    return (_TABLE_ORDER.get(fact.table, 99), fact.identity)


def _opaque_id(salt: str, identity: str) -> str:
    return hashlib.sha256(f"{salt}:{identity}".encode("utf-8")).hexdigest()


def _evidence_hash(evidence: dict[str, object]) -> str:
    value = {key: item for key, item in evidence.items() if key != "evidence_hash"}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _amount(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
        return None
    return round(float(value), 6)


def _same_amount(left: float, right: float) -> bool:
    return round(left, 6) == round(right, 6)


__all__ = [
    "EVIDENCE_SCHEMA", "HistoricalCostFinalizationError", "HistoricalCostReport",
    "apply_evidence", "build_evidence", "scan_historical_costs", "validate_evidence",
]
