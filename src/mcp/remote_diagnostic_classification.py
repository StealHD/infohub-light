"""Pure cause and status classification for Remote MCP diagnostics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..storage.service_store import JOB_STATUSES
from .remote_diagnostic_sanitization import (
    mapped_category,
    message_category,
    safe_timestamp,
    strict_result_summary,
)


ACTIVE_JOB_STATUSES = {"queued", "running"}
HEALTH_STATUSES = {"healthy", "degraded", "failing"}
WORKER_STATUSES = {"ready", "stale", "missing"}


def job_status(job: dict[str, Any]) -> str:
    status = str(job.get("status") or "")
    return status if status in JOB_STATUSES else "unknown"


def schedule_state(
    schedule: dict[str, Any] | None,
    *,
    checked_at: datetime,
) -> str:
    if schedule is None:
        return "not_configured"
    if not bool(schedule.get("enabled")):
        return "disabled"
    if schedule.get("last_skip_reason"):
        return "blocked"
    next_run_at = safe_timestamp(schedule.get("next_run_at"))
    if next_run_at and datetime.fromisoformat(next_run_at) <= checked_at:
        return "overdue"
    return "ready"


def classify_records(
    records: tuple[dict[str, Any] | None, ...],
) -> tuple[str | None, str | None, str | None]:
    retained_code: str | None = None
    for record in records:
        if not record:
            continue
        raw_code = (
            record.get("error_code")
            if "error_code" in record
            else record.get("last_issue_code")
        )
        category, safe_code = mapped_category(raw_code)
        retained_code = retained_code or safe_code
        if category:
            return category, safe_code, "confirmed"
    for record in records:
        if not record:
            continue
        raw_message = (
            record.get("error_message")
            if "error_message" in record
            else record.get("last_issue_message")
        )
        category = message_category(raw_message)
        if category:
            return category, retained_code, "likely"
    return None, retained_code, None


def successful_zero_item_attempt(
    *,
    health: dict[str, Any] | None,
    job: dict[str, Any] | None,
    job_only: bool,
) -> bool:
    if (
        not job_only
        and health
        and health.get("status") == "healthy"
        and health.get("last_attempt_at")
        and int(health.get("last_fetched_count") or 0) == 0
    ):
        return True
    if not job or job.get("status") != "succeeded":
        return False
    result = strict_result_summary(job)
    return "fetched_count" in result and result["fetched_count"] == 0


def classify_job(
    *,
    job: dict[str, Any],
    worker_status: str,
) -> tuple[str, str | None, str]:
    if job_status(job) in ACTIVE_JOB_STATUSES and worker_status in {"missing", "stale"}:
        return "worker_unavailable", f"worker_{worker_status}", "confirmed"
    category, code, confidence = classify_records((job,))
    if category and confidence:
        return category, code, confidence
    if successful_zero_item_attempt(health=None, job=job, job_only=True):
        return "no_items", code, "confirmed"
    return "unknown", code, "unknown"


def classify_source(
    *,
    subject: dict[str, Any],
    schedule: dict[str, Any] | None,
    health: dict[str, Any] | None,
    job: dict[str, Any] | None,
    worker_status: str,
    job_overrides_health: bool,
    checked_at: datetime,
) -> tuple[str, str | None, str]:
    if not bool(subject.get("source_enabled")):
        return "source_disabled", "source_disabled", "confirmed"
    if not bool(subject.get("subscription_enabled")):
        return "subscription_disabled", "subscription_disabled", "confirmed"
    current_schedule_state = schedule_state(schedule, checked_at=checked_at)
    if schedule is not None and current_schedule_state in {
        "disabled",
        "blocked",
        "overdue",
    }:
        return "schedule_blocked", "schedule_blocked", "confirmed"
    if (
        job is not None
        and job_status(job) in ACTIVE_JOB_STATUSES
        and worker_status in {"missing", "stale"}
    ):
        return "worker_unavailable", f"worker_{worker_status}", "confirmed"
    records = (job,) if job_overrides_health else (health, job)
    category, retained_code, confidence = classify_records(records)
    if category and confidence:
        return category, retained_code, confidence
    if successful_zero_item_attempt(
        health=None if job_overrides_health else health,
        job=job,
        job_only=job_overrides_health,
    ):
        return "no_items", retained_code, "confirmed"
    return "unknown", retained_code, "unknown"


def selected_job_overrides_health(
    *,
    health: dict[str, Any] | None,
    related_job: dict[str, Any] | None,
    related_provenance: str | None,
) -> bool:
    if related_job is None or health is None:
        return False
    if job_status(related_job) in ACTIVE_JOB_STATUSES:
        return True
    if (
        related_provenance is not None
        and "schedule" in related_provenance
        and related_job.get("id") != health.get("last_job_id")
    ):
        return True
    return bool(
        related_job.get("id") != health.get("last_job_id")
        and health.get("last_job_id") is None
    )


def source_status(
    *,
    health: dict[str, Any] | None,
    job: dict[str, Any] | None,
    category: str,
    job_overrides_health: bool,
) -> str:
    if category in {"source_disabled", "subscription_disabled"}:
        return "disabled"
    if category == "schedule_blocked":
        return "blocked"
    if job_overrides_health and job is not None:
        return job_status(job)
    health_status = str((health or {}).get("status") or "")
    if health_status in HEALTH_STATUSES:
        return health_status
    if job is not None:
        return job_status(job)
    return "unknown"
