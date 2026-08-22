"""Pure allowlist evidence projection for Remote MCP diagnostics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .remote_diagnostic_classification import job_status, schedule_state
from .remote_diagnostic_sanitization import (
    safe_code,
    safe_timestamp,
    strict_result_summary,
)


def source_evidence(
    *,
    subject: dict[str, Any],
    schedule: dict[str, Any] | None,
    health: dict[str, Any] | None,
    job: dict[str, Any] | None,
    related_provenance: str | None,
    health_is_historical: bool,
    worker_status: str,
    secret_configured: bool,
    checked_at: datetime,
) -> list[dict[str, Any]]:
    evidence = [
        {"kind": "source_enabled", "value": bool(subject["source_enabled"])},
        {
            "kind": "subscription_enabled",
            "value": bool(subject["subscription_enabled"]),
        },
        {
            "kind": "schedule_status",
            "value": schedule_state(schedule, checked_at=checked_at),
        },
        {"kind": "secret_configured", "value": bool(secret_configured)},
    ]
    if related_provenance is not None:
        evidence.append(
            {"kind": "related_job_provenance", "value": related_provenance}
        )
    if schedule and schedule.get("last_skip_reason"):
        skip_code = safe_code(schedule.get("last_skip_reason"))
        if skip_code:
            evidence.append({"kind": "schedule_skip_reason", "value": skip_code})
    if health:
        evidence.append(
            {
                "kind": "health_evidence_role",
                "value": "historical" if health_is_historical else "current",
            }
        )
        evidence.extend(
            [
                {"kind": "health_status", "value": str(health["status"])},
                {
                    "kind": "consecutive_failures",
                    "value": max(int(health.get("consecutive_failures") or 0), 0),
                },
                {
                    "kind": "last_fetched_count",
                    "value": max(int(health.get("last_fetched_count") or 0), 0),
                },
            ]
        )
        issue_code = safe_code(health.get("last_issue_code"))
        if issue_code:
            evidence.append({"kind": "error_code", "value": issue_code})
        for field in ("last_attempt_at", "last_failure_at", "last_success_at"):
            timestamp = safe_timestamp(health.get(field))
            if timestamp:
                evidence.append({"kind": field, "value": timestamp})
    if job:
        evidence.extend(job_evidence(job, worker_status=worker_status))
    else:
        evidence.append({"kind": "worker_status", "value": worker_status})
    return evidence


def job_evidence(
    job: dict[str, Any],
    *,
    worker_status: str,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {"kind": "job_status", "value": job_status(job)},
        {"kind": "attempts", "value": max(int(job.get("attempts") or 0), 0)},
        {
            "kind": "max_attempts",
            "value": max(int(job.get("max_attempts") or 0), 0),
        },
        {"kind": "worker_status", "value": worker_status},
    ]
    code = safe_code(job.get("error_code"))
    if code:
        evidence.append({"kind": "error_code", "value": code})
    for field in ("created_at", "started_at", "finished_at", "updated_at"):
        timestamp = safe_timestamp(job.get(field))
        if timestamp:
            evidence.append({"kind": field, "value": timestamp})
    result = strict_result_summary(job)
    if result:
        evidence.append({"kind": "result_summary", "value": result})
    return evidence
