"""Private, resumable evidence sessions for legacy Actor cost audits."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


EVIDENCE_SCHEMA = "actorops_v2_legacy_cost_audit_v2"
_UNRESOLVED_ACTIONS = frozenset({"remote_blocked", "nonterminal_run", "nonterminal_attempt"})
_KNOWN_ACTIONS = frozenset(
    {
        "provider_cost",
        "quarantine_run",
        "quarantine_attempt",
        "quarantine_batch",
        *_UNRESOLVED_ACTIONS,
    }
)


class LegacyEvidenceError(ValueError):
    """Raised when a private evidence session is malformed or incomplete."""


def opaque_fact_id(salt: str, identity: str) -> str:
    return hashlib.sha256(f"{salt}:{identity}".encode("utf-8")).hexdigest()


def evidence_hash(evidence: dict[str, object]) -> str:
    raw = {key: value for key, value in evidence.items() if key != "evidence_hash"}
    return hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def public_fact(
    *, salt: str, identity: str, action: str, status: str, updated_at: str, amount_usd: float
) -> dict[str, object]:
    return {
        "fact_id": opaque_fact_id(salt, identity),
        "action": action,
        "status": status,
        "updated_at": updated_at,
        "amount_usd": float(amount_usd),
    }


def create_evidence(
    *, salt: str, facts: Iterable[dict[str, object]], remaining_remote_runs: int
) -> dict[str, object]:
    return _finalize(
        {"schema": EVIDENCE_SCHEMA, "salt": salt, "facts": list(facts), "scan_pages": 1},
        remaining_remote_runs=remaining_remote_runs,
    )


def merge_evidence(
    evidence: dict[str, object],
    *,
    facts: Iterable[dict[str, object]],
    refreshed_remote_fact_ids: Iterable[str],
    remaining_remote_runs: int,
    increment_page: bool,
) -> dict[str, object]:
    """Merge a bounded remote page without exposing remote identities on disk."""

    current = validate_evidence(evidence)
    records = {str(item["fact_id"]): dict(item) for item in _facts(current)}
    for fact_id in refreshed_remote_fact_ids:
        records.pop(str(fact_id), None)
    for item in facts:
        normalized = _normalize_fact(item)
        records[str(normalized["fact_id"])] = normalized
    pages = int(current["scan_pages"]) + (1 if increment_page else 0)
    return _finalize(
        {
            "schema": EVIDENCE_SCHEMA,
            "salt": current["salt"],
            "facts": list(records.values()),
            "scan_pages": pages,
        },
        remaining_remote_runs=remaining_remote_runs,
    )


def validate_evidence(evidence: dict[str, object]) -> dict[str, object]:
    if not isinstance(evidence, dict) or evidence.get("schema") != EVIDENCE_SCHEMA:
        raise LegacyEvidenceError("evidence schema is invalid")
    salt = evidence.get("salt")
    if not isinstance(salt, str) or not salt:
        raise LegacyEvidenceError("evidence salt is invalid")
    if not isinstance(evidence.get("scan_pages"), int) or int(evidence["scan_pages"]) < 1:
        raise LegacyEvidenceError("evidence scan page count is invalid")
    if not isinstance(evidence.get("remaining_remote_runs"), int) or int(evidence["remaining_remote_runs"]) < 0:
        raise LegacyEvidenceError("evidence remote-run count is invalid")
    facts = _facts(evidence)
    if len({str(item["fact_id"]) for item in facts}) != len(facts):
        raise LegacyEvidenceError("evidence contains duplicate fact identifiers")
    expected_counts, expected_upper = _summaries(facts)
    if evidence.get("counts") != expected_counts:
        raise LegacyEvidenceError("evidence counts do not match its facts")
    if round(float(evidence.get("upper_bound_usd", -1)), 6) != expected_upper:
        raise LegacyEvidenceError("evidence upper-bound does not match its facts")
    if evidence.get("evidence_hash") != evidence_hash(evidence):
        raise LegacyEvidenceError("evidence hash does not match its contents")
    return evidence


def unresolved_actions(evidence: dict[str, object]) -> set[str]:
    return {
        str(item["action"])
        for item in _facts(validate_evidence(evidence))
        if str(item["action"]) in _UNRESOLVED_ACTIONS
    }


def _finalize(base: dict[str, object], *, remaining_remote_runs: int) -> dict[str, object]:
    salt = base.get("salt")
    if not isinstance(salt, str) or not salt or remaining_remote_runs < 0:
        raise LegacyEvidenceError("evidence session input is invalid")
    facts = sorted((_normalize_fact(item) for item in base["facts"]), key=lambda item: str(item["fact_id"]))
    if len({str(item["fact_id"]) for item in facts}) != len(facts):
        raise LegacyEvidenceError("evidence session contains duplicate facts")
    counts, upper_bound = _summaries(facts)
    evidence: dict[str, object] = {
        "schema": EVIDENCE_SCHEMA,
        "salt": salt,
        "facts": facts,
        "counts": counts,
        "upper_bound_usd": upper_bound,
        "remaining_remote_runs": remaining_remote_runs,
        "scan_pages": base["scan_pages"],
    }
    evidence["evidence_hash"] = evidence_hash(evidence)
    return evidence


def _facts(evidence: dict[str, object]) -> list[dict[str, object]]:
    raw = evidence.get("facts")
    if not isinstance(raw, list):
        raise LegacyEvidenceError("evidence facts are invalid")
    return [_normalize_fact(item) for item in raw]


def _normalize_fact(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise LegacyEvidenceError("evidence fact is invalid")
    fact_id = item.get("fact_id")
    action = item.get("action")
    status = item.get("status")
    updated_at = item.get("updated_at")
    amount = item.get("amount_usd")
    if (
        not isinstance(fact_id, str)
        or len(fact_id) != 64
        or not isinstance(action, str)
        or action not in _KNOWN_ACTIONS
        or not isinstance(status, str)
        or not isinstance(updated_at, str)
        or isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or float(amount) < 0
    ):
        raise LegacyEvidenceError("evidence fact has an invalid shape")
    return {
        "fact_id": fact_id,
        "action": action,
        "status": status,
        "updated_at": updated_at,
        "amount_usd": round(float(amount), 6),
    }


def _summaries(facts: Iterable[dict[str, object]]) -> tuple[dict[str, int], float]:
    counts: dict[str, int] = {}
    upper_bound = 0.0
    for fact in facts:
        action = str(fact["action"])
        counts[action] = counts.get(action, 0) + 1
        if action.startswith("quarantine"):
            upper_bound += float(fact["amount_usd"])
    return dict(sorted(counts.items())), round(upper_bound, 6)


__all__ = [
    "EVIDENCE_SCHEMA",
    "LegacyEvidenceError",
    "create_evidence",
    "evidence_hash",
    "merge_evidence",
    "opaque_fact_id",
    "public_fact",
    "unresolved_actions",
    "validate_evidence",
]
